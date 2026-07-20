from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .slots import SlotStatus

LOGGER = logging.getLogger(__name__)

_SESSION_ID = re.compile(r"^[0-9a-fA-F-]{20,}$")
_LIFECYCLE_STATUS = {
    "task_started": SlotStatus.RUNNING,
    "task_complete": SlotStatus.COMPLETED,
    "turn_aborted": SlotStatus.ERROR,
}


@dataclass(frozen=True)
class SessionLogObservation:
    session_id: str
    status: SlotStatus
    event_type: str
    observed_at: float
    event_timestamp: float | None
    event_offset: int
    path: str


def _event_timestamp(value) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        return datetime.fromisoformat(normalized).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def parse_lifecycle_line(
    line: str,
    *,
    session_id: str,
    event_offset: int,
    path: str,
) -> SessionLogObservation | None:
    """Parse one JSONL event without interpreting message text or UI state."""
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict) or record.get("type") != "event_msg":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    event_type = payload.get("type")
    status = _LIFECYCLE_STATUS.get(event_type)
    if status is None:
        return None
    return SessionLogObservation(
        session_id=session_id,
        status=status,
        event_type=event_type,
        observed_at=time.monotonic(),
        event_timestamp=_event_timestamp(record.get("timestamp")),
        event_offset=event_offset,
        path=path,
    )


class SessionLogReader:
    """Read Codex rollout JSONL files in a read-only, tail-oriented way."""

    def __init__(self, root: str | Path | None = None, max_tail_bytes: int = 4 * 1024 * 1024):
        self.root = Path(root or (Path.home() / ".codex" / "sessions"))
        self.max_tail_bytes = max(64 * 1024, max_tail_bytes)
        self._paths: dict[str, Path] = {}

    def find_path(self, session_id: str) -> Path | None:
        if not _SESSION_ID.fullmatch(session_id):
            return None
        cached = self._paths.get(session_id)
        if cached is not None and cached.is_file():
            return cached
        if not self.root.is_dir():
            return None
        matches = sorted(
            self.root.rglob(f"*{session_id}.jsonl"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        if not matches:
            return None
        self._paths[session_id] = matches[0]
        return matches[0]

    def read_latest(self, session_id: str) -> SessionLogObservation | None:
        path = self.find_path(session_id)
        if path is None:
            return None
        try:
            lines = self._tail_lines(path)
        except OSError:
            LOGGER.debug("could not read session log %s", path, exc_info=True)
            return None
        for offset, raw_line in reversed(lines):
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError:
                continue
            observation = parse_lifecycle_line(
                line,
                session_id=session_id,
                event_offset=offset,
                path=str(path),
            )
            if observation is not None:
                return observation
        return None

    def _tail_lines(self, path: Path) -> list[tuple[int, bytes]]:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            start = max(0, size - self.max_tail_bytes)
            stream.seek(start)
            if start:
                stream.readline()
            lines: list[tuple[int, bytes]] = []
            while True:
                offset = stream.tell()
                line = stream.readline()
                if not line:
                    break
                lines.append((offset, line))
            return lines


class SessionLogMonitor:
    def __init__(self, controller, root: str | Path | None = None, interval: float = 0.8) -> None:
        self.controller = controller
        self.reader = SessionLogReader(root=root)
        self.interval = max(0.25, interval)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_event: dict[str, tuple[str, int]] = {}

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="codex-session-log-monitor",
            daemon=True,
        )
        self._thread.start()
        LOGGER.info("Codex session log monitor started (interval=%.2fs)", self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                observations = []
                for slot in self.controller.slots.all():
                    if not slot.bound:
                        continue
                    observation = self.reader.read_latest(slot.session_id)
                    if observation is None:
                        continue
                    signature = (observation.path, observation.event_offset)
                    if self._last_event.get(slot.session_id) == signature:
                        continue
                    self._last_event[slot.session_id] = signature
                    observations.append(observation)
                if observations:
                    self.controller.observe_session_logs(observations)
            except Exception:
                LOGGER.exception("Codex session log monitor failed")
            self._stop.wait(self.interval)

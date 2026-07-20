from __future__ import annotations

import logging
import time
from collections import Counter
from enum import IntEnum
from threading import RLock

from .desktop import DesktopAdapter, DesktopError
from .protocol import (
    EVENT_KEY_DOWN,
    EVENT_KEY_LONG,
    EVENT_KEY_UP,
    EVENT_SEND,
    EVENT_SPEAK_REPLY,
    TYPE_BEEP,
    TYPE_EVENT,
    TYPE_LED_MASK,
    TYPE_MODE,
    TYPE_SELECTED_SLOT,
    TYPE_SLOT_STATUS,
    Frame,
)
from .slots import SessionIdentity, SlotRegistry, SlotStatus
from .session_log import SessionLogObservation
from .status_monitor import ConversationObservation, normalize_title

LOGGER = logging.getLogger(__name__)


class Mode(IntEnum):
    SELECT = 0
    OPERATE = 1


class Controller:
    def __init__(
        self,
        adapter: DesktopAdapter,
        transport=None,
        reply_reader=None,
        speaker=None,
    ) -> None:
        self.adapter = adapter
        self.transport = transport
        self.reply_reader = reply_reader
        self.speaker = speaker
        self.slots = SlotRegistry()
        self.mode = Mode.SELECT
        self.selected_slot = 0
        self._open_slot: int | None = None
        self._long_seen = [False] * 5
        self._desktop_token: int | None = None
        self._sent_at: dict[int, float] = {}
        self._sent_wall_at: dict[int, float] = {}
        self._observed_running: set[int] = set()
        self._idle_streak: dict[int, int] = {}
        self._pre_send_status: dict[int, SlotStatus] = {}
        self._latest_observations: dict[str, ConversationObservation] = {}
        self._file_status_sessions: set[str] = set()
        self._lock = RLock()

    def set_transport(self, transport) -> None:
        self.transport = transport

    def on_frame(self, frame: Frame) -> None:
        if frame.frame_type != TYPE_EVENT or len(frame.payload) != 2:
            return
        event_code, key_id = frame.payload
        LOGGER.info("FPGA event code=0x%02x key=%d", event_code, key_id)
        self.handle_event(event_code, key_id)

    def handle_event(self, event_code: int, key_id: int) -> None:
        with self._lock:
            try:
                self._check_desktop_restart()
                if event_code == EVENT_SEND:
                    self._send_current_message()
                elif event_code == EVENT_SPEAK_REPLY:
                    if key_id not in range(4):
                        LOGGER.warning("ignored invalid speech slot: %d", key_id)
                    else:
                        self._long_seen[key_id] = True
                        self.speak_last_reply(key_id)
                elif key_id not in range(5):
                    LOGGER.warning("ignored invalid key id: %d", key_id)
                elif event_code == EVENT_KEY_DOWN:
                    self._long_seen[key_id] = False
                    self._key_down(key_id)
                elif event_code == EVENT_KEY_LONG:
                    self._long_seen[key_id] = True
                    self._key_long(key_id)
                elif event_code == EVENT_KEY_UP:
                    self._key_up(key_id)
            except Exception as exc:
                LOGGER.exception("desktop action failed: %s", exc)
                if self.slots.get(self.selected_slot).bound:
                    self.set_status(self.selected_slot, SlotStatus.ERROR)
                self._sync_leds(error=True)

    def bind_current(self, index: int) -> dict:
        self._check_desktop_restart()
        identity = self.adapter.capture_current()
        slot = self.slots.bind(index, identity)
        self.selected_slot = index
        self._sync_all()
        return slot.as_dict()

    def bind_identity(self, index: int, identity: SessionIdentity) -> dict:
        slot = self.slots.bind(index, identity)
        self._clear_tracking(index)
        self.selected_slot = index
        self._sync_all()
        return slot.as_dict()

    def activate_slot(self, index: int) -> dict:
        self._check_desktop_restart()
        slot = self.slots.get(index)
        self.adapter.activate(slot)
        self.selected_slot = index
        self._open_slot = index
        self._send_selected()
        self._sync_leds()
        return slot.as_dict()

    def toggle_slot_page(self, index: int) -> dict:
        slot = self.slots.get(index)
        if not slot.bound:
            return slot.as_dict()
        if self._open_slot == index:
            close_page = getattr(self.adapter, "close_page", None)
            if close_page is None:
                raise DesktopError("desktop adapter does not support closing a page")
            close_page()
            self._open_slot = None
            self._sync_leds()
            return slot.as_dict()
        return self.activate_slot(index)

    def clear_slot(self, index: int) -> dict:
        old_session_id = self.slots.get(index).session_id
        slot = self.slots.clear(index)
        if old_session_id:
            self._file_status_sessions.discard(old_session_id)
        if self._open_slot == index:
            self._open_slot = None
        self._clear_tracking(index)
        self._send_status(index)
        self._sync_leds()
        return slot.as_dict()

    def set_status(self, index: int, status: SlotStatus) -> dict:
        current_slot = self.slots.get(index)
        if status == SlotStatus.RUNNING and index not in self._sent_at:
            self._sent_at[index] = time.monotonic()
            self._pre_send_status[index] = current_slot.status
        slot, completed = self.slots.set_status(index, status)
        if status not in (SlotStatus.RUNNING, SlotStatus.UNKNOWN):
            self._clear_tracking(index)
        self._send_status(index)
        if completed:
            self._send(TYPE_BEEP, bytes((0, 120)))
        self._sync_leds()
        return slot.as_dict()

    def set_mode(self, mode: Mode) -> None:
        self.mode = Mode(mode)
        self._send(TYPE_MODE, bytes((int(self.mode),)))
        self._sync_leds()

    def snapshot(self) -> dict:
        return {
            "mode": int(self.mode),
            "selected_slot": self.selected_slot,
            "slots": [self._slot_snapshot(slot) for slot in self.slots.all()],
        }

    def sync(self) -> None:
        self._sync_all()

    def shutdown(self) -> None:
        self.adapter.release_all()
        if self.speaker is not None:
            self.speaker.stop()

    def speak_last_reply(self, index: int) -> bool:
        if self.mode != Mode.SELECT:
            return False
        slot = self.slots.get(index)
        if (
            not slot.bound
            or slot.status != SlotStatus.COMPLETED
            or self.reply_reader is None
            or self.speaker is None
        ):
            return False
        message = self.reply_reader.read_last_reply(slot.session_id)
        if not message:
            LOGGER.warning("no completed reply found for session %s", slot.session_id)
            return False
        return bool(self.speaker.speak(message))

    def observe_conversations(self, observations: list[ConversationObservation]) -> None:
        """Apply evidence from the ChatGPT conversation list conservatively.

        A completion is accepted only for a slot that was sent by this
        controller and whose list item is either uniquely identified by title
        or is the only completed candidate. This prevents one background
        conversation from completing another slot by accident.
        """
        with self._lock:
            title_counts = Counter(
                normalize_title(observation.title)
                for observation in observations
                if normalize_title(observation.title)
            )
            self._latest_observations = {}
            for observation in observations:
                title = normalize_title(observation.title)
                if title and title_counts[title] == 1:
                    self._latest_observations[title] = observation
            matched: dict[int, ConversationObservation] = {}
            unmatched_completed: list[ConversationObservation] = []

            for observation in observations:
                title = normalize_title(observation.title)
                if not title or title_counts[title] != 1:
                    if observation.status == SlotStatus.COMPLETED:
                        LOGGER.warning(
                            "ignoring completion for duplicated conversation title: %r",
                            observation.title,
                        )
                    continue
                candidates = self._slots_for_observation(observation)
                if len(candidates) == 1:
                    matched[candidates[0].index] = observation
                elif observation.status == SlotStatus.COMPLETED:
                    unmatched_completed.append(observation)

            for index, observation in matched.items():
                self._apply_observation(index, observation)

            pending = [
                slot
                for slot in self.slots.all()
                if slot.bound
                and slot.session_id not in self._file_status_sessions
                and slot.status in (SlotStatus.RUNNING, SlotStatus.UNKNOWN)
                and slot.index in self._sent_at
            ]
            if len(pending) == 1 and len(unmatched_completed) == 1:
                self._apply_observation(pending[0].index, unmatched_completed[0])
            elif len(pending) > 1 and unmatched_completed:
                LOGGER.warning(
                    "completion status is ambiguous for %d running slots; "
                    "keeping their current status",
                    len(pending),
                )

            self._apply_idle_completion_fallback(observations, pending)

    def observe_session_logs(self, observations: list[SessionLogObservation]) -> None:
        """Apply lifecycle events from Codex JSONL logs.

        A session with a readable rollout log becomes file-authoritative. UI
        observations are ignored for that session so a stale icon cannot
        overwrite a real task_started/task_complete event.
        """
        with self._lock:
            for observation in observations:
                slot = self.slots.find(observation.session_id)
                if slot is None:
                    continue
                self._file_status_sessions.add(observation.session_id)
                if observation.status == SlotStatus.COMPLETED:
                    sent_wall_at = self._sent_wall_at.get(slot.index)
                    if (
                        sent_wall_at is not None
                        and (
                            observation.event_timestamp is None
                            or observation.event_timestamp < sent_wall_at
                        )
                    ):
                        LOGGER.debug(
                            "ignoring stale file completion for slot %d", slot.index
                        )
                        continue
                    if sent_wall_at is None and slot.status != SlotStatus.RUNNING:
                        self._set_status_silent(slot.index, SlotStatus.COMPLETED)
                        continue
                self.set_status(slot.index, observation.status)

    def _slots_for_observation(self, observation: ConversationObservation):
        title = normalize_title(observation.title)
        if not title:
            return []
        return [
            slot
            for slot in self.slots.all()
            if slot.bound and normalize_title(slot.title) == title
        ]

    def _apply_observation(self, index: int, observation: ConversationObservation) -> None:
        slot = self.slots.get(index)
        if slot.session_id in self._file_status_sessions:
            return
        if observation.status != SlotStatus.IDLE:
            self._idle_streak.pop(index, None)
        if observation.status == SlotStatus.RUNNING:
            if index in self._sent_at:
                self._observed_running.add(index)
            if slot.status in (SlotStatus.IDLE, SlotStatus.UNKNOWN):
                self.set_status(index, SlotStatus.RUNNING)
            return

        if observation.status == SlotStatus.COMPLETED:
            sent_at = self._sent_at.get(index)
            if sent_at is None or observation.observed_at < sent_at:
                return
            was_completed_before_send = (
                self._pre_send_status.get(index) == SlotStatus.COMPLETED
            )
            if index not in self._observed_running and was_completed_before_send:
                return
            self.set_status(index, SlotStatus.COMPLETED)
            return

        if (
            observation.status == SlotStatus.IDLE
            and slot.status == SlotStatus.RUNNING
            and index in self._sent_at
        ):
            # The list says the item is no longer running, but the completion
            # marker was missed. Expose uncertainty instead of beeping falsely.
            self.set_status(index, SlotStatus.UNKNOWN)

    def _apply_idle_completion_fallback(
        self,
        observations: list[ConversationObservation],
        pending: list,
    ) -> None:
        """Handle ChatGPT versions that replace the completion dot with age.

        This is deliberately limited to one controller-tracked running slot.
        It cannot safely choose among multiple background sessions.
        """
        if len(pending) != 1:
            for slot in pending:
                self._idle_streak.pop(slot.index, None)
            return

        slot = pending[0]
        if slot.session_id in self._file_status_sessions:
            return
        title = normalize_title(slot.title)
        sent_at = self._sent_at.get(slot.index)
        title_observations = [
            observation
            for observation in observations
            if normalize_title(observation.title) == title
        ]
        if (
            not title
            or sent_at is None
            or not title_observations
            or any(observation.status != SlotStatus.IDLE for observation in title_observations)
            or max(observation.observed_at for observation in title_observations) < sent_at
        ):
            self._idle_streak.pop(slot.index, None)
            return

        self._idle_streak[slot.index] = self._idle_streak.get(slot.index, 0) + 1
        if self._idle_streak[slot.index] < 2:
            return
        LOGGER.info(
            "session %s has been idle for two polls after sending; "
            "using idle completion fallback",
            slot.session_id,
        )
        self.set_status(slot.index, SlotStatus.COMPLETED)

    def _key_down(self, key_id: int) -> None:
        if self.mode != Mode.OPERATE:
            return
        if key_id == 0:
            self.adapter.right_alt_down()
        elif key_id == 1:
            self.adapter.backspace()
        elif key_id == 2:
            self.adapter.right_down()
        elif key_id == 3:
            self.adapter.left_down()

    def _key_long(self, key_id: int) -> None:
        if self.mode == Mode.SELECT and key_id in range(4):
            self.bind_current(key_id)
        elif self.mode == Mode.OPERATE and key_id == 4:
            self.clear_slot(self.selected_slot)
            self.set_mode(Mode.SELECT)

    def _key_up(self, key_id: int) -> None:
        was_long = self._long_seen[key_id]
        if self.mode == Mode.OPERATE:
            if key_id == 0:
                self.adapter.right_alt_up()
            elif key_id == 1:
                backspace_up = getattr(self.adapter, "backspace_up", None)
                if backspace_up is not None:
                    backspace_up()
            elif key_id == 2:
                self.adapter.right_up()
            elif key_id == 3:
                self.adapter.left_up()

        if key_id == 4:
            if not was_long:
                self.set_mode(Mode.OPERATE if self.mode == Mode.SELECT else Mode.SELECT)
            return
        if self.mode == Mode.SELECT and key_id in range(4) and not was_long:
            self.toggle_slot_page(key_id)

    def _check_desktop_restart(self) -> None:
        token_reader = getattr(self.adapter, "process_token", None)
        if token_reader is None:
            return
        token = token_reader()
        if token is None:
            return
        if self._desktop_token is not None and token != self._desktop_token:
            LOGGER.info("desktop process changed; clearing session slots")
            self.slots.clear_all()
            self._file_status_sessions.clear()
            self.mode = Mode.SELECT
            self.selected_slot = 0
            self._open_slot = None
            self._sync_all()
        self._desktop_token = token

    def _send_current_message(self) -> None:
        if self.mode != Mode.OPERATE:
            return
        identity = self.adapter.capture_current()
        slot = self.slots.find(identity.session_id)
        if slot is None:
            slot = self.slots.first_empty()
            if slot is not None:
                self.slots.bind(slot.index, identity)
        elif identity.title and not slot.title:
            slot.title = identity.title
        if slot is not None:
            self._sent_wall_at[slot.index] = time.time()
        self.adapter.send_enter()
        if slot is not None:
            self.selected_slot = slot.index
            self._sent_at[slot.index] = time.monotonic()
            self._pre_send_status[slot.index] = self._latest_status_for(identity.title)
            self._observed_running.discard(slot.index)
            self._idle_streak.pop(slot.index, None)
            self.set_status(slot.index, SlotStatus.RUNNING)
            self._send_selected()

    def _latest_status_for(self, title: str) -> SlotStatus:
        observation = self._latest_observations.get(normalize_title(title))
        return observation.status if observation is not None else SlotStatus.UNKNOWN

    def _clear_tracking(self, index: int) -> None:
        self._sent_at.pop(index, None)
        self._sent_wall_at.pop(index, None)
        self._observed_running.discard(index)
        self._idle_streak.pop(index, None)
        self._pre_send_status.pop(index, None)

    def _sync_all(self) -> None:
        self._send(TYPE_MODE, bytes((int(self.mode),)))
        self._send_selected()
        for index in range(4):
            self._send_status(index)
        self._sync_leds()

    def _send_status(self, index: int) -> None:
        slot = self.slots.get(index)
        self._send(TYPE_SLOT_STATUS, bytes((index, int(slot.status))))

    def _send_selected(self) -> None:
        self._send(TYPE_SELECTED_SLOT, bytes((self.selected_slot,)))

    def _sync_leds(self, error: bool = False) -> None:
        mask = 1 if self.mode == Mode.SELECT else 2
        mask |= 1 << (self.selected_slot + 2)
        if error:
            mask |= 0x80
        self._send(TYPE_LED_MASK, bytes((mask,)))

    def _send(self, frame_type: int, payload: bytes) -> None:
        if self.transport is not None:
            self.transport.send(frame_type, payload)

    def _set_status_silent(self, index: int, status: SlotStatus) -> None:
        self.slots.set_status(index, status)
        self._send_status(index)
        self._sync_leds()

    def _slot_snapshot(self, slot) -> dict:
        data = slot.as_dict()
        data["status_source"] = (
            "file" if slot.session_id in self._file_status_sessions else "ui"
        )
        return data

import json
import tempfile
import unittest
from pathlib import Path

from codex_micro.session_log import SessionLogReader, parse_lifecycle_line
from codex_micro.slots import SlotStatus


SESSION_ID = "11111111-2222-3333-4444-555555555555"


def event_line(
    event_type: str,
    timestamp: str = "2026-07-20T03:00:00.000Z",
    last_agent_message: str | None = None,
) -> str:
    payload = {"type": event_type}
    if last_agent_message is not None:
        payload["last_agent_message"] = last_agent_message
    return json.dumps({"timestamp": timestamp, "type": "event_msg", "payload": payload})


class SessionLogTests(unittest.TestCase):
    def test_parse_lifecycle_events(self):
        started = parse_lifecycle_line(
            event_line("task_started"),
            session_id=SESSION_ID,
            event_offset=10,
            path="session.jsonl",
        )
        complete = parse_lifecycle_line(
            event_line("task_complete"),
            session_id=SESSION_ID,
            event_offset=20,
            path="session.jsonl",
        )
        aborted = parse_lifecycle_line(
            event_line("turn_aborted"),
            session_id=SESSION_ID,
            event_offset=30,
            path="session.jsonl",
        )
        self.assertEqual(started.status, SlotStatus.RUNNING)
        self.assertEqual(complete.status, SlotStatus.COMPLETED)
        self.assertEqual(aborted.status, SlotStatus.ERROR)

    def test_non_lifecycle_line_is_ignored(self):
        observation = parse_lifecycle_line(
            json.dumps({"type": "response_item", "payload": {"type": "message"}}),
            session_id=SESSION_ID,
            event_offset=0,
            path="session.jsonl",
        )
        self.assertIsNone(observation)

    def test_reader_returns_latest_lifecycle_event(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sessions"
            root.mkdir()
            path = root / f"rollout-{SESSION_ID}.jsonl"
            path.write_text(
                "\n".join(
                    [
                        event_line("task_started"),
                        json.dumps({"type": "response_item", "payload": {"type": "message"}}),
                        event_line("task_complete", "2026-07-20T03:00:01.000Z"),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            observation = SessionLogReader(root=root).read_latest(SESSION_ID)
            self.assertIsNotNone(observation)
            self.assertEqual(observation.status, SlotStatus.COMPLETED)
            self.assertEqual(observation.event_type, "task_complete")

    def test_reader_returns_reply_from_latest_completed_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sessions"
            root.mkdir()
            path = root / f"rollout-{SESSION_ID}.jsonl"
            path.write_text(
                "\n".join(
                    [
                        event_line("task_complete", last_agent_message="old reply"),
                        event_line("task_started"),
                        event_line(
                            "task_complete",
                            "2026-07-20T03:00:01.000Z",
                            "latest reply",
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(SessionLogReader(root=root).read_last_reply(SESSION_ID), "latest reply")


if __name__ == "__main__":
    unittest.main()

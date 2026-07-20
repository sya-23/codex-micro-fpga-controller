import unittest
import time

from codex_micro.core import Controller, Mode
from codex_micro.protocol import (
    EVENT_KEY_DOWN,
    EVENT_KEY_LONG,
    EVENT_KEY_UP,
    EVENT_SEND,
    TYPE_BEEP,
)
from codex_micro.slots import SessionIdentity, SlotStatus
from codex_micro.status_monitor import ConversationObservation
from codex_micro.session_log import SessionLogObservation
from codex_micro.transport import MemoryTransport


class FakeAdapter:
    def __init__(self):
        self.actions = []
        self.identities = []
        self.token = "desktop-1"

    def process_token(self):
        return self.token

    def capture_current(self):
        if self.identities:
            return self.identities.pop(0)
        return SessionIdentity("current", "codex://current")

    def activate(self, slot): self.actions.append(("activate", slot.index))
    def right_alt_down(self): self.actions.append("alt_down")
    def right_alt_up(self): self.actions.append("alt_up")
    def backspace(self): self.actions.append("backspace")
    def delete(self): self.actions.append("backspace")
    def left_down(self): self.actions.append("left_down")
    def left_up(self): self.actions.append("left_up")
    def right_down(self): self.actions.append("right_down")
    def right_up(self): self.actions.append("right_up")
    def close_page(self): self.actions.append("close_page")
    def send_enter(self): self.actions.append("send")
    def release_all(self): self.actions.append("release_all")


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()
        self.transport = MemoryTransport()
        self.controller = Controller(self.adapter, self.transport)

    def test_long_key_binds_and_short_key_activates(self):
        self.adapter.identities.append(SessionIdentity("s0", "codex://s0"))
        self.controller.handle_event(EVENT_KEY_DOWN, 0)
        self.controller.handle_event(EVENT_KEY_LONG, 0)
        self.controller.handle_event(EVENT_KEY_UP, 0)
        self.assertEqual(self.controller.slots.get(0).session_id, "s0")

        self.controller.handle_event(EVENT_KEY_DOWN, 0)
        self.controller.handle_event(EVENT_KEY_UP, 0)
        self.assertIn(("activate", 0), self.adapter.actions)

    def test_second_click_on_same_slot_closes_page(self):
        self.controller.bind_identity(0, SessionIdentity("s0", "codex://s0"))

        self.controller.handle_event(EVENT_KEY_DOWN, 0)
        self.controller.handle_event(EVENT_KEY_UP, 0)
        self.controller.handle_event(EVENT_KEY_DOWN, 0)
        self.controller.handle_event(EVENT_KEY_UP, 0)

        self.assertEqual(self.adapter.actions, [("activate", 0), "close_page"])
        self.assertIsNone(self.controller._open_slot)

    def test_k4_short_toggles_mode_and_operation_keys(self):
        self.controller.handle_event(EVENT_KEY_DOWN, 4)
        self.controller.handle_event(EVENT_KEY_UP, 4)
        self.assertEqual(self.controller.mode, Mode.OPERATE)

        self.controller.handle_event(EVENT_KEY_DOWN, 0)
        self.controller.handle_event(EVENT_KEY_UP, 0)
        self.assertIn("alt_down", self.adapter.actions)
        self.assertIn("alt_up", self.adapter.actions)

    def test_operation_direction_mapping(self):
        self.controller.set_mode(Mode.OPERATE)
        self.controller.handle_event(EVENT_KEY_DOWN, 2)
        self.controller.handle_event(EVENT_KEY_UP, 2)
        self.controller.handle_event(EVENT_KEY_DOWN, 3)
        self.controller.handle_event(EVENT_KEY_UP, 3)
        self.assertEqual(
            self.adapter.actions[-4:],
            ["right_down", "right_up", "left_down", "left_up"],
        )

    def test_operation_k1_is_backspace(self):
        self.controller.set_mode(Mode.OPERATE)
        self.controller.handle_event(EVENT_KEY_DOWN, 1)
        self.assertIn("backspace", self.adapter.actions)

    def test_send_auto_binds_first_empty_slot(self):
        self.controller.set_mode(Mode.OPERATE)
        self.adapter.identities.append(SessionIdentity("new", "codex://new"))
        self.controller.handle_event(EVENT_SEND, 0xFF)
        slot = self.controller.slots.get(0)
        self.assertEqual(slot.session_id, "new")
        self.assertEqual(slot.status, SlotStatus.RUNNING)
        self.assertIn("send", self.adapter.actions)

    def test_completed_transition_emits_one_beep(self):
        self.controller.bind_identity(0, SessionIdentity("s0", "codex://s0"))
        before = len(self.transport.frames)
        self.controller.set_status(0, SlotStatus.COMPLETED)
        first = len(self.transport.frames)
        self.controller.set_status(0, SlotStatus.COMPLETED)
        second = len(self.transport.frames)
        self.assertEqual(first - before, 3)
        self.assertEqual(second - first, 2)

    def test_desktop_restart_clears_bindings(self):
        self.controller.handle_event(EVENT_KEY_DOWN, 4)
        self.controller.bind_identity(0, SessionIdentity("s0", "codex://s0"))
        self.adapter.token = "desktop-2"
        self.controller.handle_event(EVENT_KEY_DOWN, 4)
        self.assertFalse(self.controller.slots.get(0).bound)
        self.assertEqual(self.controller.mode, Mode.SELECT)

    def test_list_completion_is_applied_to_matching_sent_session(self):
        self.controller.set_mode(Mode.OPERATE)
        self.adapter.identities.append(SessionIdentity("s0", "codex://s0", "会话A"))
        self.controller.handle_event(EVENT_SEND, 0xFF)
        self.controller.observe_conversations(
            [ConversationObservation("会话A", SlotStatus.RUNNING, time.monotonic() + 1)]
        )
        self.controller.observe_conversations(
            [ConversationObservation("会话A", SlotStatus.COMPLETED, time.monotonic() + 2)]
        )
        self.assertEqual(self.controller.slots.get(0).status, SlotStatus.COMPLETED)
        beep_frames = [frame for frame in self.transport.frames if frame[2] == TYPE_BEEP]
        self.assertEqual(len(beep_frames), 1)

    def test_old_completed_marker_is_ignored_until_running_is_seen(self):
        self.controller.bind_identity(0, SessionIdentity("s0", "codex://s0", "会话A"))
        self.controller.observe_conversations(
            [ConversationObservation("会话A", SlotStatus.COMPLETED, time.monotonic() - 1)]
        )
        self.controller.set_mode(Mode.OPERATE)
        self.adapter.identities.append(SessionIdentity("s0", "codex://s0", "会话A"))
        self.controller.handle_event(EVENT_SEND, 0xFF)
        self.controller.observe_conversations(
            [ConversationObservation("会话A", SlotStatus.COMPLETED, time.monotonic() + 1)]
        )
        self.assertEqual(self.controller.slots.get(0).status, SlotStatus.RUNNING)

    def test_ambiguous_completion_does_not_change_two_running_slots(self):
        self.controller.bind_identity(0, SessionIdentity("s0", "codex://s0", "同名"))
        self.controller.bind_identity(1, SessionIdentity("s1", "codex://s1", "同名"))
        self.controller.set_mode(Mode.OPERATE)
        self.adapter.identities.extend(
            [
                SessionIdentity("s0", "codex://s0", "同名"),
                SessionIdentity("s1", "codex://s1", "同名"),
            ]
        )
        self.controller.handle_event(EVENT_SEND, 0xFF)
        self.controller.handle_event(EVENT_SEND, 0xFF)
        self.controller.observe_conversations(
            [ConversationObservation("同名", SlotStatus.RUNNING, time.monotonic() + 1)]
        )
        self.controller.observe_conversations(
            [ConversationObservation("同名", SlotStatus.COMPLETED, time.monotonic() + 2)]
        )
        self.assertEqual(self.controller.slots.get(0).status, SlotStatus.RUNNING)
        self.assertEqual(self.controller.slots.get(1).status, SlotStatus.RUNNING)

    def test_duplicate_list_titles_do_not_complete_a_single_slot(self):
        self.controller.bind_identity(0, SessionIdentity("s0", "codex://s0", "同名"))
        self.controller.set_mode(Mode.OPERATE)
        self.adapter.identities.append(SessionIdentity("s0", "codex://s0", "同名"))
        self.controller.handle_event(EVENT_SEND, 0xFF)
        now = time.monotonic() + 1
        self.controller.observe_conversations(
            [
                ConversationObservation("同名", SlotStatus.COMPLETED, now),
                ConversationObservation("同名", SlotStatus.IDLE, now),
            ]
        )
        self.assertEqual(self.controller.slots.get(0).status, SlotStatus.RUNNING)

    def test_one_running_slot_can_fall_back_from_idle_list_rows_to_completed(self):
        self.controller.bind_identity(0, SessionIdentity("s0", "codex://s0", "同名"))
        self.controller.set_mode(Mode.OPERATE)
        self.adapter.identities.append(SessionIdentity("s0", "codex://s0", "同名"))
        self.controller.handle_event(EVENT_SEND, 0xFF)
        now = time.monotonic() + 1
        idle_rows = [
            ConversationObservation("同名", SlotStatus.IDLE, now),
            ConversationObservation("同名", SlotStatus.IDLE, now),
        ]
        self.controller.observe_conversations(idle_rows)
        self.assertEqual(self.controller.slots.get(0).status, SlotStatus.RUNNING)
        self.controller.observe_conversations(
            [
                ConversationObservation("同名", SlotStatus.IDLE, now + 1),
                ConversationObservation("同名", SlotStatus.IDLE, now + 1),
            ]
        )
        self.assertEqual(self.controller.slots.get(0).status, SlotStatus.COMPLETED)

    def test_session_log_status_is_authoritative_over_ui(self):
        self.controller.bind_identity(0, SessionIdentity("s0", "codex://s0", "会话A"))
        self.controller.observe_session_logs(
            [
                SessionLogObservation(
                    session_id="s0",
                    status=SlotStatus.RUNNING,
                    event_type="task_started",
                    observed_at=time.monotonic(),
                    event_timestamp=time.time(),
                    event_offset=10,
                    path="session.jsonl",
                )
            ]
        )
        self.controller.observe_conversations(
            [ConversationObservation("会话A", SlotStatus.COMPLETED, time.monotonic())]
        )
        self.assertEqual(self.controller.slots.get(0).status, SlotStatus.RUNNING)

        self.controller.observe_session_logs(
            [
                SessionLogObservation(
                    session_id="s0",
                    status=SlotStatus.COMPLETED,
                    event_type="task_complete",
                    observed_at=time.monotonic(),
                    event_timestamp=time.time() + 1,
                    event_offset=20,
                    path="session.jsonl",
                )
            ]
        )
        self.assertEqual(self.controller.slots.get(0).status, SlotStatus.COMPLETED)
        self.assertEqual(self.controller.snapshot()["slots"][0]["status_source"], "file")

    def test_stale_file_completion_does_not_complete_new_send(self):
        self.controller.set_mode(Mode.OPERATE)
        self.adapter.identities.append(SessionIdentity("s0", "codex://s0", "会话A"))
        self.controller.handle_event(EVENT_SEND, 0xFF)
        self.controller.observe_session_logs(
            [
                SessionLogObservation(
                    session_id="s0",
                    status=SlotStatus.COMPLETED,
                    event_type="task_complete",
                    observed_at=time.monotonic(),
                    event_timestamp=time.time() - 60,
                    event_offset=10,
                    path="session.jsonl",
                )
            ]
        )
        self.assertEqual(self.controller.slots.get(0).status, SlotStatus.RUNNING)


if __name__ == "__main__":
    unittest.main()

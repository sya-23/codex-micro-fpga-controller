import time
import unittest
from unittest.mock import Mock

from codex_micro.desktop import DesktopAdapter, VK_BACK, VK_LEFT


class DesktopRepeatTests(unittest.TestCase):
    def test_left_key_repeats_until_release(self):
        adapter = DesktopAdapter(dry_run=True)
        adapter.keyboard.press = Mock()

        adapter.left_down()
        time.sleep(0.25)
        adapter.left_up()
        count_at_release = adapter.keyboard.press.call_count
        time.sleep(0.08)

        self.assertGreaterEqual(count_at_release, 2)
        self.assertEqual(adapter.keyboard.press.call_count, count_at_release)
        self.assertNotIn(VK_LEFT, adapter._repeat_controls)

    def test_backspace_repeats_until_release(self):
        adapter = DesktopAdapter(dry_run=True)
        adapter.keyboard.press = Mock()

        adapter.backspace()
        time.sleep(0.25)
        adapter.backspace_up()
        count_at_release = adapter.keyboard.press.call_count
        time.sleep(0.08)

        self.assertGreaterEqual(count_at_release, 2)
        self.assertEqual(adapter.keyboard.press.call_count, count_at_release)
        self.assertNotIn(VK_BACK, adapter._repeat_controls)

    def test_close_page_minimizes_without_closing_app(self):
        adapter = DesktopAdapter(dry_run=True)
        adapter.window.minimize = Mock(return_value=True)

        adapter.close_page()

        adapter.window.minimize.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

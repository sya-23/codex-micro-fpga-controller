import unittest

from codex_micro.status_monitor import (
    ChatGPTListReader,
    ConversationObservation,
    classify_icon_pixels,
    split_title_age,
)
from codex_micro.slots import SlotStatus


class StatusMonitorTests(unittest.TestCase):
    def test_split_title_and_age(self):
        self.assertEqual(split_title_age("回复你好17m"), ("回复你好", True))
        self.assertEqual(split_title_age("New chat1mo"), ("New chat", True))
        self.assertEqual(split_title_age("回复问候"), ("回复问候", False))

    def test_blue_icon_is_completed_and_gray_ring_is_running(self):
        gray_ring = [(40, 48, 56)] * 100 + [(140, 148, 170)] * 30
        blue_dot = [(40, 48, 56)] * 100 + [(50, 130, 240)] * 30
        self.assertEqual(classify_icon_pixels(gray_ring), SlotStatus.RUNNING)
        self.assertEqual(classify_icon_pixels(blue_dot), SlotStatus.COMPLETED)

    def test_reader_uses_list_item_relative_status_image(self):
        class Rect:
            left, top, right, bottom = 0, 0, 100, 40

        class Info:
            control_type = "Image"
            class_name = "icon-xs shrink-0"

        class Image:
            element_info = Info()

            @staticmethod
            def rectangle():
                return Rect()

        class ItemInfo:
            name = "测试会话17m"

        class Item:
            element_info = ItemInfo()

            @staticmethod
            def descendants(**kwargs):
                if kwargs.get("control_type") == "ListItem":
                    return []
                return [Image()]

            @staticmethod
            def rectangle():
                return Rect()

        reader = ChatGPTListReader(
            window_factory=lambda: type(
                "Window",
                (),
                {"descendants": lambda self, **kwargs: [Item()]},
            )(),
            screen_capture=lambda _rect: [(40, 48, 56)] * 100
            + [(140, 148, 170)] * 30,
        )
        result = reader.read()
        self.assertEqual(result[0].title, "测试会话")
        self.assertEqual(result[0].status, SlotStatus.RUNNING)


if __name__ == "__main__":
    unittest.main()

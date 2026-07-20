import unittest

from codex_micro.speech import prepare_speech_text


class SpeechTextTests(unittest.TestCase):
    def test_removes_markdown_code_and_links(self):
        text = """# 完成

        结果见 [说明](https://example.com)。

        ```python
        print('不要朗读代码')
        ```

        下一步是 **继续测试**。
        """
        result = prepare_speech_text(text)
        self.assertIn("完成", result)
        self.assertIn("说明", result)
        self.assertIn("继续测试", result)
        self.assertNotIn("不要朗读代码", result)
        self.assertNotIn("https://", result)

    def test_empty_markup_does_not_start_speech(self):
        self.assertEqual(prepare_speech_text("```text\ncode\n```"), "")


if __name__ == "__main__":
    unittest.main()

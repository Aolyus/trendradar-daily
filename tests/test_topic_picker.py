import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "topic_picker.py"
SPEC = importlib.util.spec_from_file_location("topic_picker", SCRIPT)
topic_picker = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(topic_picker)


class TopicPickerTests(unittest.TestCase):
    def test_afternoon_prompt_limits_topics_and_allows_silence(self):
        messages = topic_picker.build_slot_prompt(
            [{"title": "New model", "source": "Official", "url": "https://example.com"}],
            [],
            "afternoon",
        )

        prompt = messages[-1]["content"]
        self.assertIn("1-3 个强选题", prompt)
        self.assertIn(topic_picker.NO_STRONG_TOPIC, prompt)
        self.assertIn("不要重复早上的常规话题", prompt)

    def test_no_strong_topic_sentinel_is_detected(self):
        self.assertFalse(topic_picker.has_strong_topic("NO_STRONG_TOPIC"))
        self.assertFalse(topic_picker.has_strong_topic("  no_strong_topic\n"))
        self.assertTrue(topic_picker.has_strong_topic("01｜值得补充的新选题"))

    def test_morning_prompt_keeps_full_topic_radar(self):
        messages = topic_picker.build_slot_prompt([], [], "morning")
        self.assertIn("3-5 个最值得拍成短视频的选题", messages[-1]["content"])

    def test_hidden_validation_terms_are_removed_from_feishu_text(self):
        text = "01｜选题\n验证词：中文词｜English terms\n推荐：9/10"
        cleaned = topic_picker.strip_validation_terms(text)
        self.assertNotIn("验证词", cleaned)
        self.assertIn("推荐：9/10", cleaned)


if __name__ == "__main__":
    unittest.main()

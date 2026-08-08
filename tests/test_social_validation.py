import datetime as dt
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "social_validation.py"
SPEC = importlib.util.spec_from_file_location("social_validation", SCRIPT)
social_validation = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = social_validation
SPEC.loader.exec_module(social_validation)


class FakeSearcher:
    def __init__(self, results_by_domain):
        self.results_by_domain = results_by_domain
        self.calls = []

    def search(self, query):
        self.calls.append(query)
        for domain, results in self.results_by_domain.items():
            if f"site:{domain}" in query:
                return {"results": results, "more_results": False}
        return {"results": [], "more_results": False}


def result(title, url):
    return {
        "title": title,
        "url": url,
        "snippet": title,
        "published_at": "2026-08-08",
        "source_access": "indexed_only",
    }


class SocialValidationTests(unittest.TestCase):
    def test_extracts_only_top_level_numbered_topics(self):
        analysis = """01｜Astra AI 黑客开始自主攻击
标题备选：
1. 这不是选题行
02｜新模型改变视频生成
03｜第三个选题
"""
        topics = social_validation.extract_topic_titles(analysis, 2)
        self.assertEqual([topic["number"] for topic in topics], ["01", "02"])

    def test_similarity_rejects_same_product_but_different_angle(self):
        related = social_validation.similarity_score(
            "H3 可以生成 32×32 音频",
            "H3 32×32 音频生成玩法实测",
        )
        unrelated = social_validation.similarity_score(
            "H3 可以生成 32×32 音频",
            "H3 模型正式发布，参数规模公布",
        )
        self.assertGreater(related, unrelated)
        self.assertLess(unrelated, 0.25)

    def test_high_value_public_evidence_produces_compact_output_and_cache(self):
        searcher = FakeSearcher(
            {
                "xiaohongshu.com": [],
                "bilibili.com": [
                    result("Astra AI 黑客自主攻击实测", "https://www.bilibili.com/video/BV1")
                ],
                "youtube.com": [
                    result("Astra AI autonomous hacking demo", "https://youtube.com/watch?v=1"),
                    result("Astra AI hacker attack test", "https://youtube.com/watch?v=2"),
                    result("Astra autonomous cyber attack", "https://youtube.com/watch?v=3"),
                ],
                "reddit.com": [
                    result("Astra AI autonomous hacking discussion", "https://reddit.com/r/ai/1")
                ],
                "x.com": [],
            }
        )
        analysis = (
            "01｜Astra AI 黑客开始自主攻击\n"
            "推荐：9/10\n"
            "验证词：AI自主攻击｜AI安全测试｜Astra autonomous hacking｜AI cyber attack"
        )
        now = dt.datetime(2026, 8, 8, 11, 0, tzinfo=social_validation.BEIJING)

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            first = social_validation.validate_analysis(
                analysis,
                "morning",
                "test-key",
                cache,
                searcher=searcher,
                now=now,
                logger=lambda _: None,
            )
            second = social_validation.validate_analysis(
                analysis,
                "morning",
                "test-key",
                cache,
                searcher=searcher,
                now=now + dt.timedelta(minutes=10),
                logger=lambda _: None,
            )

        self.assertIn("平台验证｜公开索引", first)
        self.assertIn("小红书 0", first)
        self.assertIn("存在抢跑窗口", first)
        self.assertEqual(first, second)
        self.assertEqual(len(searcher.calls), len(social_validation.PLATFORMS))

    def test_low_evidence_stays_silent(self):
        searcher = FakeSearcher(
            {
                "youtube.com": [
                    result("Astra AI autonomous hacking", "https://youtube.com/watch?v=1")
                ]
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            output = social_validation.validate_analysis(
                "01｜Astra AI 黑客开始自主攻击",
                "afternoon",
                "test-key",
                Path(directory) / "cache.json",
                searcher=searcher,
                logger=lambda _: None,
            )
        self.assertEqual(output, "")

    def test_missing_api_key_stays_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            output = social_validation.validate_analysis(
                "01｜Astra AI 黑客开始自主攻击",
                "morning",
                "",
                Path(directory) / "cache.json",
                logger=lambda _: None,
            )
        self.assertEqual(output, "")

    def test_query_uses_hidden_bilingual_terms(self):
        topic = {
            "title": "AI 自己攻击其他公司的系统",
            "search_terms": ["AI自主攻击", "Astra autonomous hacking"],
        }
        query = social_validation.build_query(topic, social_validation.PLATFORMS[0])
        self.assertIn("AI自主攻击", query)
        self.assertNotIn("Astra autonomous hacking", query)

        youtube_query = social_validation.build_query(topic, social_validation.PLATFORMS[2])
        self.assertIn("Astra autonomous hacking", youtube_query)


if __name__ == "__main__":
    unittest.main()

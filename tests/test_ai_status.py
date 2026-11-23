import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.ai_status import install_analysis_guard, topics_blocked


class AnalysisStatusTests(unittest.TestCase):
    def test_balance_failure_is_short_and_blocks_second_request(self):
        class Analyzer:
            def analyze(self):
                return SimpleNamespace(success=False, skipped=False, error=(
                    'BadRequestError: Insufficient Balance request_id=private-detail'
                ))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai-status.json"
            install_analysis_guard(Analyzer, path)
            result = Analyzer().analyze()
            self.assertIn("余额不足", result.error)
            self.assertNotIn("private-detail", result.error)
            self.assertNotIn("private-detail", path.read_text(encoding="utf-8"))
            self.assertTrue(topics_blocked(path))

    def test_next_run_retries_after_balance_restored(self):
        class Analyzer:
            def analyze(self):
                return SimpleNamespace(success=True, skipped=False, error="", core_trends="analysis")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai-status.json"
            path.write_text(json.dumps({"skip_topics": True}), encoding="utf-8")
            install_analysis_guard(Analyzer, path)
            self.assertFalse(topics_blocked(path))
            self.assertEqual(Analyzer().analyze().core_trends, "analysis")
            self.assertFalse(path.exists())

    def test_temporary_failure_does_not_block_topics(self):
        class Analyzer:
            def analyze(self):
                return SimpleNamespace(success=False, skipped=False, error="connection timeout")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai-status.json"
            install_analysis_guard(Analyzer, path)
            Analyzer().analyze()
            self.assertFalse(topics_blocked(path))


if __name__ == "__main__":
    unittest.main()

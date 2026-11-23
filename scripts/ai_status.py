"""Keep provider failures concise and share permanent failures within one run."""

from __future__ import annotations

import json
from functools import wraps
from pathlib import Path


def failure_status(error: str) -> dict:
    message = error.lower()
    if "insufficient" in message and "balance" in message:
        return {
            "reason": "insufficient_balance",
            "skip_topics": True,
            "message": "AI 服务余额不足，分析和视频选题暂不可用；充值后下次运行自动重试。资讯仍正常推送。",
        }
    if any(token in message for token in ("authentication", "invalid_api_key", "unauthorized")):
        return {
            "reason": "authentication_failed",
            "skip_topics": True,
            "message": "AI 服务认证失败，请检查 GitHub Secrets 中的 AI_API_KEY。资讯仍正常推送。",
        }
    return {
        "reason": "analysis_failed",
        "skip_topics": False,
        "message": "AI 分析暂时不可用，请查看 GitHub Actions 运行日志。资讯仍正常推送。",
    }


def install_analysis_guard(analyzer_class: type, status_path: Path) -> None:
    # The marker belongs to this execution only; a top-up must be retried next run.
    status_path.unlink(missing_ok=True)
    original_analyze = analyzer_class.analyze

    @wraps(original_analyze)
    def guarded_analyze(self, *args, **kwargs):
        result = original_analyze(self, *args, **kwargs)
        if not result.success and not result.skipped:
            status = failure_status(str(result.error))
            result.error = status["message"]
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
            print(f"::warning title=AI analysis::{status['message']}", flush=True)
        return result

    analyzer_class.analyze = guarded_analyze


def topics_blocked(status_path: Path) -> bool:
    if not status_path.exists():
        return False
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if status.get("skip_topics"):
        print(f"::warning title=Video topics skipped::{status['message']}", flush=True)
        return True
    return False

#!/usr/bin/env python3
"""Run TrendRadar while treating a failed Feishu delivery as a real failure."""

from __future__ import annotations

import argparse

from trendradar.__main__ import NewsAnalyzer
from trendradar.core import load_config
from trendradar.notification.dispatcher import NotificationDispatcher


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config()
    config["DEBUG"] = True

    if args.dry_run:
        config["ENABLE_NOTIFICATION"] = False
    else:
        original_dispatch = NotificationDispatcher.dispatch_all

        def strict_dispatch(self, *dispatch_args, **dispatch_kwargs):
            results = original_dispatch(self, *dispatch_args, **dispatch_kwargs)
            if not results.get("feishu", False):
                raise RuntimeError(f"Feishu delivery was not confirmed: {results}")
            return results

        NotificationDispatcher.dispatch_all = strict_dispatch

    analyzer = NewsAnalyzer(config=config)
    analyzer.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

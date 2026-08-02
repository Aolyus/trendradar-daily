#!/usr/bin/env python3
# coding: utf-8
"""
Generate short-video topic ideas from the daily TrendRadar output.

This script is designed for GitHub Actions:
1. Read today's TrendRadar SQLite output.
2. Ask an OpenAI-compatible model, such as DeepSeek, to select video topics.
3. Send the topic cards to a Feishu custom bot webhook.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MAX_NEWS_ITEMS = 80
MAX_RSS_ITEMS = 80
MAX_FEISHU_TEXT = 12000


def log(message: str) -> None:
    print(f"[topic-picker] {message}", flush=True)


def find_latest_db(directory: Path) -> Path | None:
    if not directory.exists():
        return None
    dbs = sorted(directory.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return dbs[0] if dbs else None


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type='table' and name=?",
        (table,),
    ).fetchone()
    return row is not None


def get_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"pragma table_info({table})")}


def read_news_items(db_path: Path | None, limit: int = MAX_NEWS_ITEMS) -> list[dict[str, Any]]:
    if not db_path or not db_path.exists():
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if not table_exists(conn, "news_items"):
            return []

        columns = get_columns(conn, "news_items")
        source_expr = "platform_id"
        if table_exists(conn, "platforms"):
            source_expr = "coalesce(platforms.name, news_items.platform_id)"

        select_parts = [
            "news_items.title as title",
            f"{source_expr} as source",
            "news_items.url as url" if "url" in columns else "'' as url",
            "news_items.rank as rank" if "rank" in columns else "999 as rank",
            "news_items.updated_at as updated_at" if "updated_at" in columns else "'' as updated_at",
        ]
        join = " left join platforms on platforms.id = news_items.platform_id" if table_exists(conn, "platforms") else ""
        order = " order by rank asc, updated_at desc" if "rank" in columns else " order by rowid desc"

        rows = conn.execute(
            f"select {', '.join(select_parts)} from news_items{join}{order} limit ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows if row["title"]]
    finally:
        conn.close()


def read_rss_items(db_path: Path | None, limit: int = MAX_RSS_ITEMS) -> list[dict[str, Any]]:
    if not db_path or not db_path.exists():
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if not table_exists(conn, "rss_items"):
            return []

        columns = get_columns(conn, "rss_items")
        source_expr = "feed_id"
        if table_exists(conn, "feeds"):
            source_expr = "coalesce(feeds.name, rss_items.feed_id)"

        select_parts = [
            "rss_items.title as title",
            f"{source_expr} as source",
            "rss_items.url as url" if "url" in columns else "'' as url",
            "rss_items.summary as summary" if "summary" in columns else "'' as summary",
            "rss_items.published_at as published_at" if "published_at" in columns else "'' as published_at",
        ]
        join = " left join feeds on feeds.id = rss_items.feed_id" if table_exists(conn, "feeds") else ""
        order = " order by published_at desc" if "published_at" in columns else " order by rowid desc"

        rows = conn.execute(
            f"select {', '.join(select_parts)} from rss_items{join}{order} limit ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows if row["title"]]
    finally:
        conn.close()


def compact_items(items: list[dict[str, Any]], item_type: str) -> str:
    lines = []
    for idx, item in enumerate(items, 1):
        title = str(item.get("title", "")).strip()
        source = str(item.get("source", "")).strip()
        url = str(item.get("url", "")).strip()
        summary = str(item.get("summary", "")).strip()
        rank = item.get("rank", "")
        prefix = f"{idx}. [{source}]"
        if item_type == "hotlist" and rank not in ("", None):
            prefix += f" rank={rank}"
        line = f"{prefix} {title}"
        if summary:
            line += f" -- {summary[:220]}"
        if url:
            line += f" ({url})"
        lines.append(line)
    return "\n".join(lines)


def build_prompt(news_items: list[dict[str, Any]], rss_items: list[dict[str, Any]]) -> list[dict[str, str]]:
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    system = (
        "你是一个敏锐的中文 AI 内容选题策划。你的任务不是复述新闻，"
        "而是从当天 AI 资讯里判断哪些适合做短视频，并给出可拍角度。"
        "偏好：反常识、趋势判断、普通人/创作者/创业者可理解、60-90秒能讲清。"
        "避免夸大、避免编造事实。"
    )
    user = f"""
今天日期：{today}

请基于下面的 AI 资讯候选池，筛选 3-5 个最值得拍成短视频的选题。

每个选题请输出：
1. 选题标题
2. 推荐指数：1-10
3. 为什么今天值得拍
4. 适合切入角度
5. 3秒开头钩子
6. 60-90秒视频结构
7. 可用标题备选 2 个
8. 风险提示
9. 引用到的新闻来源标题，最多 3 条

请用中文，直接给飞书可读的 Markdown 风格文本，不要输出 JSON。

【热榜候选】
{compact_items(news_items, "hotlist") or "无"}

【RSS候选】
{compact_items(rss_items, "rss") or "无"}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user.strip()},
    ]


def normalize_model(model: str) -> str:
    if model.startswith("deepseek/"):
        return model.split("/", 1)[1]
    return model or "deepseek-chat"


def chat_completion(messages: list[dict[str, str]]) -> str:
    api_key = os.environ.get("AI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("AI_API_KEY is not configured")

    model = normalize_model(os.environ.get("AI_MODEL", "").strip())
    api_base = os.environ.get("AI_API_BASE", "").strip() or "https://api.deepseek.com"
    api_base = api_base.rstrip("/")
    endpoint = api_base if api_base.endswith("/chat/completions") else f"{api_base}/chat/completions"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.55,
        "max_tokens": 3000,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def split_text(text: str, max_len: int = MAX_FEISHU_TEXT) -> list[str]:
    chunks = []
    remaining = text
    while len(remaining) > max_len:
        cut = remaining.rfind("\n", 0, max_len)
        if cut < max_len // 2:
            cut = max_len
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def send_feishu(text: str) -> None:
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("FEISHU_WEBHOOK_URL is not configured")

    for index, chunk in enumerate(split_text(text), 1):
        suffix = f"\n\n（第 {index} 段）" if len(text) > MAX_FEISHU_TEXT else ""
        payload = {
            "msg_type": "text",
            "content": {"text": chunk + suffix},
        }
        req = urllib.request.Request(
            webhook,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        log(f"Feishu response: {body[:300]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trendradar-dir", default="TrendRadar", help="TrendRadar checkout directory")
    parser.add_argument("--dry-run", action="store_true", help="Print collected input without calling AI or Feishu")
    args = parser.parse_args()

    trendradar_dir = Path(args.trendradar_dir)
    output_dir = trendradar_dir / "output"
    news_db = find_latest_db(output_dir / "news")
    rss_db = find_latest_db(output_dir / "rss")

    log(f"news db: {news_db}")
    log(f"rss db: {rss_db}")

    news_items = read_news_items(news_db)
    rss_items = read_rss_items(rss_db)
    log(f"loaded hotlist items: {len(news_items)}")
    log(f"loaded rss items: {len(rss_items)}")

    if not news_items and not rss_items:
        raise RuntimeError("No TrendRadar items found for topic picking")

    messages = build_prompt(news_items, rss_items)
    if args.dry_run:
        print(messages[-1]["content"])
        return 0

    analysis = chat_completion(messages)
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    final_text = f"今日 AI 视频选题雷达｜{today}\n\n{analysis}\n\n来源：TrendRadar 今日资讯 + DeepSeek 二次选题分析"
    send_feishu(final_text)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        log(f"HTTP error {exc.code}: {detail}")
        raise
    except Exception as exc:
        log(f"ERROR: {exc}")
        raise

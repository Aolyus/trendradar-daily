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
import re
import sqlite3
import sys
import textwrap
import time
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
NO_STRONG_TOPIC = "NO_STRONG_TOPIC"


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

输出要求：
- 不要使用 Markdown 语法：不要用 #、##、**、```。
- 不要长篇大段，要适合手机上快速扫读。
- 每个选题最多 220 字，优先短句。
- 用下面这个纯文本格式输出：

今日最值得拍：一句话总结当天最大机会

━━━━━━━━━━━━
01｜选题标题
推荐：9/10
一句话判断：为什么值得拍
切入角度：从哪个反常识或趋势点讲
开头钩子：3 秒开场白
视频结构：
0-10秒：...
10-35秒：...
35-70秒：...
70-90秒：...
标题备选：
1. ...
2. ...
风险：不要怎么误读
来源：最多列 2 条新闻标题

最后加一段：
今天优先拍哪条：只选 1 条，并说明原因。

【热榜候选】
{compact_items(news_items, "hotlist") or "无"}

【RSS候选】
{compact_items(rss_items, "rss") or "无"}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user.strip()},
    ]


def build_slot_prompt(
    news_items: list[dict[str, Any]],
    rss_items: list[dict[str, Any]],
    slot: str,
) -> list[dict[str, str]]:
    """Build a clean Chinese prompt for the morning or afternoon slot."""
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    system = (
        "你是一名敏锐的中文 AI 内容选题策划。你的任务不是复述新闻，而是判断哪些资讯"
        "适合做成短视频，并给出有传播力、可验证、可执行的切入角度。"
        "偏好反常识、趋势判断，以及普通用户、内容创作者和创业者能够理解的影响。"
        "不要夸大，不要编造事实，不要把未经证实的消息当成定论。"
    )

    if slot == "afternoon":
        instructions = f"""
今天日期：{today}

下面只包含今天下午新增或发生变化的资讯。请先判断其中是否出现值得马上补充的视频选题。

筛选标准：
- 相比早报必须有明显新增事实、新产品、新政策、新玩法或重要进展。
- 只选择 1-3 个强选题，不要重复早上的常规话题，不要为了凑数降低标准。
- 如果没有足够重要且适合短视频的新内容，只输出一行：{NO_STRONG_TOPIC}
- 不要使用 Markdown 标记，不要使用 #、##、** 或代码块。
- 每个选题控制在 220 字以内，适合手机快速扫描。

有强选题时，严格使用以下纯文本格式：

下午新增选题：一句话说明下午最值得关注的变化

01｜选题标题
推荐：9/10
验证词：2个中文核心词｜2个英文核心词（仅供系统检索，不要写完整句子）
新增事实：与早报相比新在哪里
切入角度：从哪个反常识或趋势点讲
开头钩子：3 秒开场白
视频结构：用三句话写清起因、影响和结论
标题备选：给出 2 个
风险：哪些信息仍需核实
来源：最多列 2 条资讯标题

最后补充：下午最优先拍哪一条，以及原因。
"""
        heading = "下午增量候选"
    else:
        instructions = f"""
今天日期：{today}

请基于下面的 AI 资讯候选池，筛选 3-5 个最值得拍成短视频的选题。

输出要求：
- 不要使用 Markdown 标记，不要使用 #、##、** 或代码块。
- 不要写长篇大段，要适合手机快速扫描。
- 每个选题最多 220 字，优先使用短句。

严格使用以下纯文本格式：

今日最值得拍：一句话总结当天最大的内容机会

01｜选题标题
推荐：9/10
验证词：2个中文核心词｜2个英文核心词（仅供系统检索，不要写完整句子）
一句话判断：为什么值得拍
切入角度：从哪个反常识或趋势点讲
开头钩子：3 秒开场白
视频结构：用四句话写清起因、证据、影响和结论
标题备选：给出 2 个
风险：哪些信息需要避免误读
来源：最多列 2 条资讯标题

最后补充：今天最优先拍哪一条，以及原因。
"""
        heading = "今日候选"

    user = f"""
{instructions.strip()}

【{heading}·热榜】
{compact_items(news_items, "hotlist") or "无"}

【{heading}·RSS】
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


def clean_for_feishu_text(text: str) -> str:
    """Make model output easier to read in Feishu plain-text messages."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = text.replace("**", "")
    text = text.replace("```", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def has_strong_topic(text: str) -> bool:
    return text.strip().upper() != NO_STRONG_TOPIC


def strip_validation_terms(text: str) -> str:
    text = re.sub(r"^\s*验证词\s*[：:].*$\n?", "", text, flags=re.MULTILINE)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


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
        last_error: Exception | None = None
        for attempt in range(1, 4):
            req = urllib.request.Request(
                webhook,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                result = json.loads(body)
                code = result.get("StatusCode", result.get("code"))
                if code != 0:
                    raise RuntimeError(f"Feishu rejected the message: {body[:500]}")
                log(f"Feishu confirmed segment {index} on attempt {attempt}")
                break
            except (OSError, ValueError, RuntimeError, urllib.error.HTTPError) as exc:
                last_error = exc
                if attempt == 3:
                    raise RuntimeError(
                        f"Feishu segment {index} failed after 3 attempts"
                    ) from last_error
                wait_seconds = attempt * 2
                log(f"Feishu attempt {attempt} failed; retrying in {wait_seconds}s: {exc}")
                time.sleep(wait_seconds)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trendradar-dir", default="TrendRadar", help="TrendRadar checkout directory")
    parser.add_argument("--slot", choices=("morning", "afternoon"), default="morning")
    parser.add_argument(
        "--social-cache",
        default="state/social-validation-cache.json",
        help="Persistent public-index validation cache",
    )
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

    messages = build_slot_prompt(news_items, rss_items, args.slot)
    if args.dry_run:
        print(messages[-1]["content"])
        return 0

    analysis = chat_completion(messages)
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    analysis = clean_for_feishu_text(analysis)
    if args.slot == "afternoon" and not has_strong_topic(analysis):
        log("No strong incremental afternoon topic; Feishu topic message skipped")
        return 0

    validation = ""
    try:
        from social_validation import validate_analysis

        validation = validate_analysis(
            analysis,
            args.slot,
            os.environ.get("BRAVE_SEARCH_API_KEY", "").strip(),
            Path(args.social_cache),
            logger=log,
        )
    except Exception as exc:
        log(f"Platform validation failed safely; original topic radar will continue: {exc}")

    analysis = strip_validation_terms(analysis)

    title = "下午 AI 视频选题补充" if args.slot == "afternoon" else "今日 AI 视频选题雷达"
    source_note = (
        "TrendRadar 下午新增资讯 + DeepSeek 增量选题分析"
        if args.slot == "afternoon"
        else "TrendRadar 今日资讯 + DeepSeek 二次选题分析"
    )
    validation_text = f"\n\n{validation}" if validation else ""
    final_text = f"{title}｜{today}\n\n{analysis}{validation_text}\n\n来源：{source_note}"
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

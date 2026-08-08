#!/usr/bin/env python3
"""Lightweight public-index validation for selected video topics."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


BEIJING = dt.timezone(dt.timedelta(hours=8))
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_CACHE_TTL_HOURS = 4
MAX_RESULTS_PER_PLATFORM = 8


@dataclass(frozen=True)
class Platform:
    key: str
    label: str
    domain: str


PLATFORMS = (
    Platform("xiaohongshu", "小红书", "xiaohongshu.com"),
    Platform("bilibili", "B站", "bilibili.com"),
    Platform("youtube", "YouTube", "youtube.com"),
    Platform("reddit", "Reddit", "reddit.com"),
    Platform("x", "X", "x.com"),
)

TOPIC_LINE = re.compile(r"^\s*(\d{2})\s*[｜|]\s*(.+?)\s*$", re.MULTILINE)
SEARCH_TERMS_LINE = re.compile(r"^\s*验证词\s*[：:]\s*(.+?)\s*$", re.MULTILINE)
MARKETING_WORDS = (
    "为什么",
    "意味着什么",
    "普通人",
    "一定要知道",
    "到底",
    "真的",
    "这次",
    "来了",
    "怎么办",
    "能不能",
    "开始",
)


def extract_topic_titles(analysis: str, limit: int) -> list[dict[str, str]]:
    topics: list[dict[str, str]] = []
    seen: set[str] = set()
    matches = list(TOPIC_LINE.finditer(analysis))
    for index, match in enumerate(matches):
        number, title = match.groups()
        title = title.strip(" ：:。.!！?？\"'《》")
        normalized = normalize_text(title)
        if not title or normalized in seen:
            continue
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(analysis)
        block = analysis[match.end() : block_end]
        terms_match = SEARCH_TERMS_LINE.search(block)
        search_terms = []
        if terms_match:
            search_terms = [
                term.strip()
                for term in re.split(r"[｜|,，;；]", terms_match.group(1))
                if term.strip()
            ]
        seen.add(normalized)
        topics.append({"number": number, "title": title, "search_terms": search_terms})
        if len(topics) >= limit:
            break
    return topics


def build_search_terms(topic: dict[str, Any], platform: Platform) -> str:
    title = str(topic["title"])
    hidden_terms = topic.get("search_terms", [])
    wants_chinese = platform.key in {"xiaohongshu", "bilibili"}
    selected = [
        term
        for term in hidden_terms
        if bool(re.search(r"[\u4e00-\u9fff]", term)) == wants_chinese
    ][:2]
    terms = " ".join(selected) if selected else title
    for word in MARKETING_WORDS:
        terms = terms.replace(word, " ")
    terms = re.sub(r"[“”‘’《》【】（）()，,。.!！?？：:；;、|｜]", " ", terms)
    terms = re.sub(r"\s+", " ", terms).strip()
    return terms[:80] or title[:80]


def build_query(topic: dict[str, Any], platform: Platform) -> str:
    return f"site:{platform.domain} {build_search_terms(topic, platform)}"


def normalize_text(text: str) -> str:
    return "".join(re.findall(r"[a-z0-9\u4e00-\u9fff]+", text.lower()))


def latin_tokens(text: str) -> set[str]:
    ignored = {"ai", "the", "and", "for", "with", "from", "new"}
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9._-]{1,}", text)
        if token.lower() not in ignored
    }


def chinese_bigrams(text: str) -> set[str]:
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    return {chinese[index : index + 2] for index in range(max(0, len(chinese) - 1))}


def similarity_score(topic: str, candidate: str) -> float:
    normalized_topic = normalize_text(topic)
    normalized_candidate = normalize_text(candidate)
    if not normalized_topic or not normalized_candidate:
        return 0.0
    if normalized_topic in normalized_candidate or normalized_candidate in normalized_topic:
        return 1.0

    topic_latin = latin_tokens(topic)
    candidate_latin = latin_tokens(candidate)
    latin_score = (
        len(topic_latin & candidate_latin) / len(topic_latin)
        if topic_latin
        else 0.0
    )

    topic_bigrams = chinese_bigrams(topic)
    candidate_bigrams = chinese_bigrams(candidate)
    chinese_score = (
        len(topic_bigrams & candidate_bigrams) / min(len(topic_bigrams), 8)
        if topic_bigrams
        else 0.0
    )
    if topic_bigrams:
        # A shared product/model name is only weak evidence. Chinese angle
        # overlap must carry most of the score when the topic contains it.
        return min(1.0, (latin_score * 0.2) + (chinese_score * 0.8))
    return min(1.0, latin_score)


def topic_similarity(topic: dict[str, Any], candidate: str) -> float:
    phrases = [str(topic["title"]), *topic.get("search_terms", [])]
    scores = []
    for phrase in phrases:
        if len(normalize_text(phrase)) < 4:
            continue
        scores.append(similarity_score(phrase, candidate))
    return max(scores, default=0.0)


class BraveSearcher:
    def __init__(self, api_key: str, timeout: int = 20):
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: str) -> dict[str, Any]:
        params = urllib.parse.urlencode(
            {
                "q": query,
                "count": MAX_RESULTS_PER_PLATFORM,
                "freshness": "pw",
                "safesearch": "moderate",
                "extra_snippets": "false",
            }
        )
        request = urllib.request.Request(
            f"{BRAVE_ENDPOINT}?{params}",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
            },
        )
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                results = payload.get("web", {}).get("results", [])
                return {
                    "results": [normalize_result(item) for item in results],
                    "more_results": bool(payload.get("query", {}).get("more_results_available")),
                }
            except (OSError, ValueError, urllib.error.HTTPError) as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(1)
        raise RuntimeError("Brave Search request failed") from last_error


def normalize_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(item.get("title", "")).strip(),
        "url": str(item.get("url", "")).strip(),
        "snippet": str(item.get("description", "")).strip(),
        "published_at": item.get("page_age") or item.get("age"),
        "source_access": "indexed_only",
    }


def load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "queries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "queries": {}}
    if not isinstance(data.get("queries"), dict):
        data["queries"] = {}
    return data


def save_cache(path: Path, cache: dict[str, Any]) -> None:
    entries = list(cache.get("queries", {}).items())
    if len(entries) > 200:
        entries.sort(key=lambda item: item[1].get("checked_at", ""), reverse=True)
        cache["queries"] = dict(entries[:200])
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def cache_key(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def cached_search(
    query: str,
    searcher: Any,
    cache: dict[str, Any],
    now: dt.datetime,
    ttl_hours: int,
) -> dict[str, Any]:
    key = cache_key(query)
    entry = cache["queries"].get(key)
    if entry:
        try:
            checked_at = dt.datetime.fromisoformat(entry["checked_at"])
            if now - checked_at < dt.timedelta(hours=ttl_hours):
                return entry["response"]
        except (KeyError, TypeError, ValueError):
            pass

    response = searcher.search(query)
    cache["queries"][key] = {
        "query": query,
        "checked_at": now.isoformat(),
        "response": response,
    }
    return response


def classify_stage(counts: dict[str, int]) -> tuple[str, int, str]:
    chinese = counts.get("xiaohongshu", 0) + counts.get("bilibili", 0)
    overseas = counts.get("youtube", 0) + counts.get("reddit", 0) + counts.get("x", 0)
    total = chinese + overseas
    active_platforms = sum(1 for count in counts.values() if count > 0)

    if total >= 12 and chinese >= 5 and active_platforms >= 3:
        stage = "高拥挤"
    elif total >= 6 or active_platforms >= 3:
        stage = "扩散"
    elif total >= 2 or active_platforms >= 2:
        stage = "升温"
    else:
        stage = "萌芽"

    score = 55
    if overseas >= 3 and chinese <= 1:
        score += 30
    elif overseas >= 1 and chinese <= 1:
        score += 18
    if chinese == 0:
        score += 8
    if chinese >= 5:
        score -= 22
    if total >= 12:
        score -= 15
    score = max(10, min(95, score))

    if overseas >= 3 and chinese <= 1:
        conclusion = "海外已有讨论，中文公开内容仍少，存在抢跑窗口。"
    elif chinese >= 5:
        conclusion = "中文平台已出现较多相似内容，需要换角度而不是跟拍。"
    elif total >= 2:
        conclusion = "多个公开来源开始出现，选题正在升温。"
    else:
        conclusion = "公开证据仍少，暂不足以判断平台趋势。"
    return stage, score, conclusion


def compact_count(count: int, more_results: bool) -> str:
    return f"≥{count}" if more_results and count else str(count)


def validate_topic(
    topic: dict[str, str],
    searcher: Any,
    cache: dict[str, Any],
    now: dt.datetime,
    ttl_hours: int,
    logger: Callable[[str], None],
) -> dict[str, Any] | None:
    evidence: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    more_results: dict[str, bool] = {}
    successful_searches = 0

    for platform in PLATFORMS:
        query = build_query(topic, platform)
        try:
            response = cached_search(query, searcher, cache, now, ttl_hours)
            successful_searches += 1
        except Exception as exc:
            logger(f"{platform.label} public-index search skipped: {exc}")
            counts[platform.key] = 0
            more_results[platform.key] = False
            continue

        matched: list[dict[str, Any]] = []
        for result in response.get("results", []):
            candidate = f"{result.get('title', '')} {result.get('snippet', '')}"
            score = topic_similarity(topic, candidate)
            if score < 0.25 or not result.get("url"):
                continue
            matched.append({**result, "platform": platform.key, "platform_label": platform.label, "similarity": score})

        matched.sort(key=lambda item: item["similarity"], reverse=True)
        counts[platform.key] = len(matched)
        more_results[platform.key] = bool(response.get("more_results"))
        evidence.extend(matched)

    if successful_searches < 3 or len(evidence) < 2:
        return None

    stage, score, conclusion = classify_stage(counts)
    representative = max(evidence, key=lambda item: item["similarity"])
    return {
        "topic": topic,
        "counts": counts,
        "more_results": more_results,
        "stage": stage,
        "first_mover_score": score,
        "conclusion": conclusion,
        "representative": representative,
    }


def format_validation(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    lines = ["平台验证｜公开索引"]
    for result in results:
        counts = result["counts"]
        more = result["more_results"]
        overseas = counts.get("youtube", 0) + counts.get("reddit", 0) + counts.get("x", 0)
        overseas_more = any(more.get(key, False) for key in ("youtube", "reddit", "x"))
        lines.append(
            f"{result['topic']['number']}｜{result['stage']}｜抢跑 {result['first_mover_score'] // 10}/10"
        )
        lines.append(
            "公开命中："
            f"小红书 {compact_count(counts.get('xiaohongshu', 0), more.get('xiaohongshu', False))}｜"
            f"B站 {compact_count(counts.get('bilibili', 0), more.get('bilibili', False))}｜"
            f"海外 {compact_count(overseas, overseas_more)}"
        )
        lines.append(f"判断：{result['conclusion']}")
        source = result["representative"]
        source_title = source["title"][:48]
        lines.append(f"证据（公开索引）：{source['platform_label']}｜{source_title}｜{source['url']}")
    return "\n".join(lines)


def validate_analysis(
    analysis: str,
    slot: str,
    api_key: str,
    cache_path: Path,
    *,
    searcher: Any | None = None,
    now: dt.datetime | None = None,
    ttl_hours: int = DEFAULT_CACHE_TTL_HOURS,
    logger: Callable[[str], None] = print,
) -> str:
    if not api_key and searcher is None:
        logger("BRAVE_SEARCH_API_KEY is not configured; platform validation skipped")
        return ""

    topic_limit = 2 if slot == "morning" else 1
    topics = extract_topic_titles(analysis, topic_limit)
    if not topics:
        logger("No structured topic titles found; platform validation skipped")
        return ""

    current = now or dt.datetime.now(BEIJING)
    cache = load_cache(cache_path)
    active_searcher = searcher or BraveSearcher(api_key)
    validated: list[dict[str, Any]] = []
    for topic in topics:
        result = validate_topic(topic, active_searcher, cache, current, ttl_hours, logger)
        if result:
            validated.append(result)
    save_cache(cache_path, cache)
    return format_validation(validated)

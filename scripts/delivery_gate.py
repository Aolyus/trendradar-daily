#!/usr/bin/env python3
"""Resolve delivery slots and maintain a small persistent success ledger."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


CHINA_TZ = dt.timezone(dt.timedelta(hours=8))
SCHEDULE_SLOTS = {
    "47 2 * * *": "morning",
    "47 7 * * *": "afternoon",
}
WINDOWS = {
    "morning": (dt.time(10, 30), dt.time(12, 30)),
    "afternoon": (dt.time(15, 30), dt.time(17, 30)),
}


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def now_china(value: str | None = None) -> dt.datetime:
    if not value:
        return dt.datetime.now(dt.timezone.utc).astimezone(CHINA_TZ)
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CHINA_TZ)
    return parsed.astimezone(CHINA_TZ)


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "deliveries": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("deliveries"), dict):
        raise ValueError("delivery state must contain a deliveries object")
    return data


def resolve_slot(event_name: str, schedule: str, requested: str, now: dt.datetime) -> str:
    if event_name == "schedule":
        if schedule not in SCHEDULE_SLOTS:
            raise ValueError(f"unknown schedule: {schedule!r}")
        return SCHEDULE_SLOTS[schedule]
    if requested in {"morning", "afternoon"}:
        return requested
    return "morning" if now.hour < 14 else "afternoon"


def within_window(slot: str, now: dt.datetime) -> bool:
    start, end = WINDOWS[slot]
    current = now.time().replace(tzinfo=None)
    return start <= current <= end


def write_outputs(path: str | None, values: dict[str, str]) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def gate(args: argparse.Namespace) -> int:
    current = now_china(args.now)
    slot = resolve_slot(args.event_name, args.schedule, args.requested_slot, current)
    force = parse_bool(args.force)
    dry_run = parse_bool(args.dry_run)
    source = args.source or ("github-schedule" if args.event_name == "schedule" else "manual")
    delivery_key = f"{current.date().isoformat()}:{slot}"
    state = read_state(Path(args.state))

    reason = "ready"
    should_run = True
    if source in {"watchdog", "github-schedule"} and not within_window(slot, current):
        reason = "outside-window"
        should_run = False
    elif not force and state["deliveries"].get(delivery_key, {}).get("status") == "success":
        reason = "already-delivered"
        should_run = False

    values = {
        "slot": slot,
        "source": source,
        "delivery_key": delivery_key,
        "report_mode": "daily" if slot == "morning" else "incremental",
        "should_run": str(should_run).lower(),
        "reason": reason,
        "dry_run": str(dry_run).lower(),
    }
    print(json.dumps({"event": "delivery_gate", "now": current.isoformat(), **values}, ensure_ascii=True))
    write_outputs(args.github_output, values)
    return 0


def mark(args: argparse.Namespace) -> int:
    current = now_china(args.now)
    path = Path(args.state)
    state = read_state(path)
    key = f"{current.date().isoformat()}:{args.slot}"
    state["deliveries"][key] = {
        "status": "success",
        "slot": args.slot,
        "source": args.source,
        "run_id": str(args.run_id),
        "run_url": args.run_url,
        "success_at": current.isoformat(),
    }

    cutoff = current.date() - dt.timedelta(days=45)
    state["deliveries"] = {
        item_key: value
        for item_key, value in state["deliveries"].items()
        if dt.date.fromisoformat(item_key.split(":", 1)[0]) >= cutoff
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"event": "delivery_marked", "delivery_key": key}, ensure_ascii=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    gate_parser = commands.add_parser("gate")
    gate_parser.add_argument("--state", required=True)
    gate_parser.add_argument("--event-name", required=True)
    gate_parser.add_argument("--schedule", default="")
    gate_parser.add_argument("--requested-slot", default="auto")
    gate_parser.add_argument("--source", default="")
    gate_parser.add_argument("--force", default="false")
    gate_parser.add_argument("--dry-run", default="false")
    gate_parser.add_argument("--now")
    gate_parser.add_argument("--github-output")
    gate_parser.set_defaults(handler=gate)

    mark_parser = commands.add_parser("mark")
    mark_parser.add_argument("--state", required=True)
    mark_parser.add_argument("--slot", choices=("morning", "afternoon"), required=True)
    mark_parser.add_argument("--source", required=True)
    mark_parser.add_argument("--run-id", required=True)
    mark_parser.add_argument("--run-url", required=True)
    mark_parser.add_argument("--now")
    mark_parser.set_defaults(handler=mark)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

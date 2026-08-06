from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from scripts import delivery_gate


class DeliveryGateTests(unittest.TestCase):
    def gate(self, state: Path, **overrides: str) -> dict[str, str]:
        output = state.parent / "github-output.txt"
        values = {
            "state": str(state),
            "event_name": "workflow_dispatch",
            "schedule": "",
            "requested_slot": "morning",
            "source": "watchdog",
            "force": "false",
            "dry_run": "false",
            "now": "2026-08-06T11:17:00+08:00",
            "github_output": str(output),
        }
        values.update(overrides)
        delivery_gate.gate(argparse.Namespace(**values))
        return dict(
            line.split("=", 1)
            for line in output.read_text(encoding="utf-8").splitlines()
        )

    def test_first_watchdog_run_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = self.gate(Path(directory) / "state.json")
            self.assertEqual(output["should_run"], "true")
            self.assertEqual(output["slot"], "morning")

    def test_successful_slot_is_not_sent_twice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "deliveries": {
                            "2026-08-06:morning": {"status": "success"}
                        },
                    }
                ),
                encoding="utf-8",
            )
            output = self.gate(state)
            self.assertEqual(output["should_run"], "false")
            self.assertEqual(output["reason"], "already-delivered")

    def test_late_watchdog_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = self.gate(
                Path(directory) / "state.json",
                now="2026-08-06T14:00:00+08:00",
            )
            self.assertEqual(output["should_run"], "false")
            self.assertEqual(output["reason"], "outside-window")

    def test_force_manual_run_bypasses_success_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text(
                '{"version": 1, "deliveries": {"2026-08-06:morning": {"status": "success"}}}',
                encoding="utf-8",
            )
            output = self.gate(state, source="manual", force="true")
            self.assertEqual(output["should_run"], "true")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Synthetic tests for the metrics collector."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "skills/nodes/scripts/metrics.sh"


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="crew-metrics-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.crew_home = self.root / "crew-home"
        self.home.mkdir()
        self.crew_home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fake_pi = self.bin / "pi"
        fake_pi.write_text(
            f"#!{sys.executable}\n"
            "import sys\n"
            "if sys.argv[1:] == ['--version']:\n"
            "    print('0.75.4')\n"
            "else:\n"
            "    raise SystemExit(2)\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)
        self.env = os.environ.copy()
        for key in (
            "HYPRLAND_INSTANCE_SIGNATURE",
            "XDG_RUNTIME_DIR",
            "CREW_STARTED_AT",
            "CREW_HOME",
            "CREW_RUNS",
            "XDG_DATA_HOME",
            "CLAUDE_CODE_SESSION_ID",
            "CODEX_THREAD_ID",
        ):
            self.env.pop(key, None)
        self.env.update(
            {
                "HOME": str(self.home),
                "CREW_HOME": str(self.crew_home),
                "CREW_RUNS": str(self.crew_home / "runs"),
                "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                "CREW_TASK": "crew-v1",
                "CREW_NODE": "metrics-tests",
                "CREW_PARENT": "125181:1",
                "CREW_REPO_ID": "github.com/example/crew",
            }
        )

    def run_helper(self, cli, status="done", report="report.md", **extra):
        env = self.env.copy()
        env["CREW_CLI"] = cli
        env.update(extra)
        return subprocess.run(
            ["bash", str(HELPER), "record", "--status", status,
             "--report", report],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def write_claude(self, session_id, records, project="fixture-project"):
        path = (
            self.home / ".claude/projects" / project / f"{session_id}.jsonl"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        self.write_jsonl(path, records)
        return path

    def write_codex(self, thread_id, records):
        path = (
            self.home
            / ".codex/sessions/2026/10/18"
            / f"rollout-2026-10-18T12-00-00-{thread_id}.jsonl"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        self.write_jsonl(path, records)
        return path

    def write_pi(self, session_id, records, window_id="73", started_at=None,
                 task="crew-v1"):
        started_at = started_at or str(int(time.time()) - 2)
        path = (
            self.crew_home / "runs" / task / "pi"
            / f"{window_id}-{started_at}" / "session.jsonl"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        header = {
            "type": "session",
            "id": session_id,
            "version": 3,
            "timestamp": "2026-10-19T12:00:00Z",
            "cwd": "/synthetic/project",
        }
        self.write_jsonl(path, [header, *records])
        return path, {
            "KITTY_WINDOW_ID": window_id,
            "CREW_STARTED_AT": started_at,
            "CREW_TASK": task,
        }

    @staticmethod
    def pi_message(message_id, model, usage, timestamp):
        return {
            "type": "message",
            "id": message_id,
            "parentId": "synthetic-parent",
            "timestamp": timestamp,
            "message": {
                "role": "assistant",
                "model": model,
                "content": [{"type": "text", "text": "SYNTHETIC_PROMPT"}],
                "usage": usage,
            },
        }

    @staticmethod
    def write_jsonl(path, records):
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )

    def rows(self, directory=None):
        metrics = (directory or self.crew_home) / "metrics.jsonl"
        if not metrics.exists():
            return []
        return [json.loads(line) for line in metrics.read_text().splitlines()]

    @staticmethod
    def token_counts(input_, cache_read, cache_write, output, reasoning):
        return {
            "input": input_,
            "cache_read": cache_read,
            "cache_write": cache_write,
            "output": output,
            "reasoning": reasoning,
        }

    @staticmethod
    def claude_cost_state(
        cost, input_, output, thinking, cache_read, cache_write,
        duration=12500, api_duration=8100, api_without_retries=7000,
        tool_duration=2400,
    ):
        return {
            "type": "cost-state",
            "totalCostUSD": cost,
            "totalDuration": duration,
            "totalAPIDuration": api_duration,
            "totalAPIDurationWithoutRetries": api_without_retries,
            "totalToolDuration": tool_duration,
            "modelUsage": {
                "claude-model": {
                    "inputTokens": input_,
                    "outputTokens": output,
                    "thinkingTokens": thinking,
                    "cacheReadInputTokens": cache_read,
                    "cacheCreationInputTokens": cache_write,
                    "costUSD": cost,
                }
            },
        }

    @staticmethod
    def codex_event(event_type, payload, timestamp=None):
        event = {"type": event_type, "payload": payload}
        if timestamp is not None:
            event["timestamp"] = timestamp
        return event

    def test_claude_cost_state_is_authoritative_and_normalizes_tokens(self):
        session_id = "claude-session"
        transcript = [
            {
                "type": "assistant",
                "version": "2.1.0",
                "message": {
                    "id": "old-message",
                    "model": "old-model",
                    "content": "PRIVATE_PROMPT_MARKER",
                    "usage": {
                        "input_tokens": 900,
                        "output_tokens": 100,
                    },
                },
            },
            self.claude_cost_state(
                8.5, 700, 90, 20, 50, 30, duration=999000
            ),
            self.claude_cost_state(
                0.42, 100, 20, 5, 30, 10,
                duration=12500,
                api_duration=8100,
                api_without_retries=7000,
                tool_duration=2400,
            ),
        ]
        own_log = self.write_claude(session_id, transcript)
        self.write_claude(
            "another-session",
            [self.claude_cost_state(99, 9999, 999, 99, 99, 99)],
        )
        with own_log.open("a", encoding="utf-8") as stream:
            stream.write('{"type":"assistant","message":')

        started = int(time.time()) - 60
        result = self.run_helper(
            "claude",
            status="passed",
            report="reports/metrics.md",
            CLAUDE_CODE_SESSION_ID=session_id,
            CREW_STARTED_AT=str(started),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertIn("140 in (30 cached)", result.stdout)
        self.assertIn("20 out", result.stdout)
        self.assertIn("$", result.stdout)
        row = self.rows()[0]

        self.assertEqual(row["task"], "crew-v1")
        self.assertEqual(row["node"], "metrics-tests")
        self.assertEqual(row["parent"], "125181:1")
        self.assertEqual(row["repo_id"], "github.com/example/crew")
        self.assertEqual(row["cli"], "claude")
        self.assertEqual(row["cli_version"], "2.1.0")
        self.assertEqual(row["session_id"], session_id)
        self.assertEqual(row["status"], "passed")
        self.assertEqual(row["report"], "reports/metrics.md")
        self.assertEqual(row["models"], ["claude-model"])
        self.assertEqual(row["usage_source"], "cost_state")
        self.assertEqual(row["cost_source"], "claude")
        self.assertEqual(row["cost_usd"], 0.42)
        expected = self.token_counts(140, 30, 10, 20, 5)
        self.assertEqual(row["tokens"], expected)
        self.assertEqual(row["model_usage"], {"claude-model": expected})
        self.assertAlmostEqual(row["session_seconds"], 12.5)
        self.assertAlmostEqual(row["api_seconds"], 8.1)
        self.assertAlmostEqual(row["api_without_retries_seconds"], 7.0)
        self.assertAlmostEqual(row["tool_seconds"], 2.4)
        self.assertGreaterEqual(row["wall_seconds"], 60)
        self.assertLess(row["wall_seconds"], 70)
        timestamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
        self.assertEqual(
            timestamp.utcoffset(), timezone.utc.utcoffset(timestamp)
        )
        serialized = (self.crew_home / "metrics.jsonl").read_text()
        self.assertNotIn("PRIVATE_PROMPT_MARKER", serialized)
        self.assertNotIn("PRIVATE_PROMPT_MARKER", result.stdout)
        for key in (
            "time", "task", "node", "parent", "repo_id", "cli",
            "cli_version", "session_id", "models", "status", "report",
            "wall_seconds", "session_seconds", "api_seconds",
            "api_without_retries_seconds", "tool_seconds", "tokens",
            "model_usage", "cost_usd", "cost_source", "usage_source",
        ):
            self.assertIn(key, row)

    def test_summary_formats_compact_counts_and_cost_without_wall_time(self):
        session_id = "summary-format"
        record = self.claude_cost_state(
            0.04,
            19_000,
            1_500,
            300,
            129_000,
            0,
            duration=92_000,
        )
        self.write_claude(session_id, [record])
        result = self.run_helper(
            "claude", CLAUDE_CODE_SESSION_ID=session_id
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "92s · 148k in (129k cached) / 1.5k out · $0.04\n",
        )
        row = self.rows()[0]
        self.assertIsNone(row["wall_seconds"])
        self.assertEqual(row["session_seconds"], 92)

    def test_claude_fallback_deduplicates_and_skips_sidechains(self):
        session_id = "message-fallback"
        records = [
            {"version": "2.2.0", "type": "user", "message": {
                "content": "PRIVATE_FALLBACK_MARKER"
            }},
            {"type": "assistant", "isSidechain": False, "message": {
                "id": "m1", "model": "model-a", "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 2,
                    "cache_creation_input_tokens": 1,
                    "output_tokens": 4,
                    "output_tokens_details": {"thinking_tokens": 1},
                },
            }},
            {"type": "assistant", "isSidechain": False, "message": {
                "id": "m1", "model": "model-a", "usage": {
                    "input_tokens": 8,
                    "cache_read_input_tokens": 4,
                    "cache_creation_input_tokens": 1,
                    "output_tokens": 3,
                    "output_tokens_details": {"thinking_tokens": 2},
                },
            }},
            {"type": "assistant", "isSidechain": False, "message": {
                "id": "m2", "model": "model-b", "usage": {
                    "input_tokens": 7,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "output_tokens": 5,
                    "output_tokens_details": {"thinking_tokens": 0},
                },
            }},
            {"type": "assistant", "isSidechain": True, "message": {
                "id": "sidechain", "model": "model-a", "usage": {
                    "input_tokens": 100,
                    "output_tokens": 100,
                },
            }},
        ]
        self.write_claude(session_id, records)
        result = self.run_helper(
            "claude", CLAUDE_CODE_SESSION_ID=session_id
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()[0]
        self.assertEqual(row["cli_version"], "2.2.0")
        self.assertEqual(row["usage_source"], "message_usage")
        self.assertIsNone(row["cost_usd"])
        self.assertEqual(row["cost_source"], "unavailable")
        self.assertEqual(set(row["models"]), {"model-a", "model-b"})
        self.assertEqual(
            row["tokens"], self.token_counts(20, 4, 1, 8, 2)
        )
        self.assertEqual(
            row["model_usage"]["model-a"],
            self.token_counts(13, 4, 1, 3, 2),
        )
        self.assertEqual(
            row["model_usage"]["model-b"],
            self.token_counts(7, 0, 0, 5, 0),
        )
        self.assertNotIn(
            "PRIVATE_FALLBACK_MARKER",
            (self.crew_home / "metrics.jsonl").read_text(),
        )

    def codex_metadata(self, thread_id, version="0.99.0"):
        return self.codex_event(
            "session_meta",
            {
                "id": thread_id,
                "cli_version": version,
                "timestamp": "2026-10-18T12:00:00Z",
            },
            "2026-10-18T12:00:00Z",
        )

    def test_codex_records_deduplicate_responses_and_track_models(self):
        thread_id = "thread-dedup"
        first_usage = {
            "input_tokens": 100,
            "cached_input_tokens": 20,
            "cache_write_input_tokens": 5,
            "output_tokens": 30,
            "reasoning_output_tokens": 10,
        }
        second_usage = {
            "input_tokens": 200,
            "cached_input_tokens": 30,
            "cache_write_input_tokens": 10,
            "output_tokens": 40,
            "reasoning_output_tokens": 15,
        }
        records = [
            self.codex_metadata(thread_id),
            self.codex_event("turn_context", {"model": "model-a"}),
            self.codex_event(
                "token_usage_record",
                {"thread_id": thread_id, "response_id": "r1",
                 "usage": first_usage},
                "2026-10-18T12:00:20Z",
            ),
            self.codex_event(
                "token_usage_record",
                {"thread_id": thread_id, "response_id": "r1",
                 "usage": first_usage},
                "2026-10-18T12:00:20Z",
            ),
            self.codex_event("turn_context", {"model": "model-b"}),
            self.codex_event(
                "token_usage_record",
                {"thread_id": thread_id, "response_id": "r2",
                 "usage": second_usage},
                "2026-10-18T12:01:00Z",
            ),
        ]
        self.write_codex(thread_id, records)
        result = self.run_helper("codex", CODEX_THREAD_ID=thread_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()[0]
        self.assertEqual(row["cli"], "codex")
        self.assertEqual(row["cli_version"], "0.99.0")
        self.assertEqual(row["session_id"], thread_id)
        self.assertEqual(set(row["models"]), {"model-a", "model-b"})
        self.assertEqual(row["usage_source"], "token_usage_record")
        self.assertEqual(
            row["tokens"], self.token_counts(300, 50, 15, 70, 25)
        )
        self.assertEqual(
            row["model_usage"]["model-a"],
            self.token_counts(100, 20, 5, 30, 10),
        )
        self.assertEqual(
            row["model_usage"]["model-b"],
            self.token_counts(200, 30, 10, 40, 15),
        )
        self.assertAlmostEqual(row["session_seconds"], 60)
        self.assertIsNone(row["api_seconds"])
        self.assertIsNone(row["tool_seconds"])
        self.assertIsNone(row["cost_usd"])
        self.assertEqual(row["cost_source"], "unavailable")

    def test_codex_token_count_uses_final_cumulative_snapshot(self):
        thread_id = "thread-cumulative"
        records = [
            self.codex_metadata(thread_id),
            self.codex_event("turn_context", {"model": "model-count"}),
            self.codex_event("event_msg", {
                "type": "token_count",
                "info": {"total_token_usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 40,
                    "cache_write_input_tokens": 5,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 5,
                }},
            }, "2026-10-18T12:00:20Z"),
            self.codex_event("event_msg", {
                "type": "token_count",
                "info": {"total_token_usage": {
                    "input_tokens": 500,
                    "cached_input_tokens": 350,
                    "cache_write_input_tokens": 25,
                    "output_tokens": 80,
                    "reasoning_output_tokens": 20,
                }},
            }, "2026-10-18T12:01:00Z"),
        ]
        self.write_codex(thread_id, records)
        result = self.run_helper("codex", CODEX_THREAD_ID=thread_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()[0]
        self.assertEqual(row["usage_source"], "token_count")
        self.assertEqual(
            row["tokens"], self.token_counts(500, 350, 25, 80, 20)
        )
        self.assertEqual(row["model_usage"]["model-count"], row["tokens"])

    def test_codex_fractional_timestamps_are_accepted(self):
        thread_id = "thread-fractional-time"
        start = "2026-10-18T12:00:00.250Z"
        end = "2026-10-18T12:00:01.750Z"
        records = [
            self.codex_event("session_meta", {
                "id": thread_id,
                "cli_version": "1.0.0",
                "timestamp": start,
            }, start),
            self.codex_event("turn_context", {"model": "fractional-model"}),
            self.codex_event("token_usage_record", {
                "thread_id": thread_id,
                "response_id": "r1",
                "usage": {
                    "input_tokens": 11,
                    "cached_input_tokens": 2,
                    "cache_write_input_tokens": 1,
                    "output_tokens": 4,
                    "reasoning_output_tokens": 1,
                },
            }, end),
        ]
        self.write_codex(thread_id, records)
        result = self.run_helper("codex", CODEX_THREAD_ID=thread_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()[0]
        self.assertAlmostEqual(row["session_seconds"], 1.5)
        self.assertEqual(row["tokens"], self.token_counts(11, 2, 1, 4, 1))

    def test_codex_token_count_with_model_changes_uses_unknown_model(self):
        thread_id = "thread-model-switch"
        records = [
            self.codex_metadata(thread_id),
            self.codex_event("turn_context", {"model": "model-a"}),
            self.codex_event("event_msg", {
                "type": "token_count",
                "info": {"total_token_usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 40,
                    "cache_write_input_tokens": 5,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 5,
                }},
            }, "2026-10-18T12:00:20Z"),
            self.codex_event("turn_context", {"model": "model-b"}),
            self.codex_event("event_msg", {
                "type": "token_count",
                "info": {"total_token_usage": {
                    "input_tokens": 250,
                    "cached_input_tokens": 200,
                    "cache_write_input_tokens": 5,
                    "output_tokens": 40,
                    "reasoning_output_tokens": 10,
                }},
            }, "2026-10-18T12:01:00Z"),
        ]
        self.write_codex(thread_id, records)
        result = self.run_helper("codex", CODEX_THREAD_ID=thread_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()[0]
        self.assertEqual(row["usage_source"], "token_count")
        self.assertEqual(
            row["tokens"], self.token_counts(250, 200, 5, 40, 10)
        )
        self.assertEqual(row["model_usage"]["unknown"], row["tokens"])
        self.assertIsNone(row["cost_usd"])
        self.assertEqual(row["cost_source"], "unavailable")

    def test_codex_never_adds_token_records_to_token_count_snapshots(self):
        thread_id = "thread-no-double-count"
        usage = {
            "input_tokens": 1000,
            "cached_input_tokens": 200,
            "cache_write_input_tokens": 50,
            "output_tokens": 400,
            "reasoning_output_tokens": 100,
        }
        records = [
            self.codex_metadata(thread_id),
            self.codex_event("turn_context", {"model": "model-mixed"}),
            self.codex_event(
                "token_usage_record",
                {"thread_id": thread_id, "response_id": "r1",
                 "usage": usage},
                "2026-10-18T12:00:20Z",
            ),
            self.codex_event("event_msg", {
                "type": "token_count",
                "info": {"total_token_usage": usage},
            }, "2026-10-18T12:00:21Z"),
        ]
        self.write_codex(thread_id, records)
        result = self.run_helper("codex", CODEX_THREAD_ID=thread_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()[0]
        self.assertEqual(row["usage_source"], "token_usage_record")
        self.assertEqual(
            row["tokens"], self.token_counts(1000, 200, 50, 400, 100)
        )

    def test_codex_price_override_does_not_reprice_reasoning(self):
        thread_id = "thread-priced"
        usage = {
            "input_tokens": 1_000_000,
            "cached_input_tokens": 100_000,
            "cache_write_input_tokens": 50_000,
            "output_tokens": 100_000,
            "reasoning_output_tokens": 50_000,
        }
        self.write_codex(thread_id, [
            self.codex_metadata(thread_id),
            self.codex_event("turn_context", {"model": "priced-model"}),
            self.codex_event(
                "token_usage_record",
                {"thread_id": thread_id, "response_id": "r1",
                 "usage": usage},
                "2026-10-18T12:01:00Z",
            ),
        ])
        (self.crew_home / "prices.json").write_text(
            json.dumps({"priced-model": {
                "input": 2, "cache_read": 0.2,
                "cache_write": 3, "output": 8,
            }}),
            encoding="utf-8",
        )
        result = self.run_helper("codex", CODEX_THREAD_ID=thread_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()[0]
        self.assertEqual(row["cost_source"], "price_table")
        self.assertAlmostEqual(row["cost_usd"], 2.67)
        self.assertIn("$", result.stdout)
        self.assertNotIn("cost unavailable", result.stdout)

    def test_missing_price_for_any_model_makes_total_cost_unavailable(self):
        thread_id = "thread-partial-price"
        records = [
            self.codex_metadata(thread_id),
            self.codex_event("turn_context", {"model": "priced-model"}),
            self.codex_event("token_usage_record", {
                "thread_id": thread_id,
                "response_id": "r1",
                "usage": {
                    "input_tokens": 10,
                    "cached_input_tokens": 1,
                    "cache_write_input_tokens": 1,
                    "output_tokens": 5,
                    "reasoning_output_tokens": 2,
                },
            }, "2026-10-18T12:00:20Z"),
            self.codex_event("turn_context", {"model": "unpriced-model"}),
            self.codex_event("token_usage_record", {
                "thread_id": thread_id,
                "response_id": "r2",
                "usage": {
                    "input_tokens": 20,
                    "cached_input_tokens": 2,
                    "cache_write_input_tokens": 1,
                    "output_tokens": 10,
                    "reasoning_output_tokens": 3,
                },
            }, "2026-10-18T12:00:30Z"),
        ]
        self.write_codex(thread_id, records)
        (self.crew_home / "prices.json").write_text(
            json.dumps({"priced-model": {
                "input": 1, "cache_read": 1,
                "cache_write": 1, "output": 1,
            }}),
            encoding="utf-8",
        )
        result = self.run_helper("codex", CODEX_THREAD_ID=thread_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()[0]
        self.assertEqual(row["cost_usd"], None)
        self.assertEqual(row["cost_source"], "unavailable")
        self.assertIn("cost unavailable", result.stdout)

    def test_missing_session_ids_and_logs_fail_without_appending(self):
        cases = (
            ("claude", "CLAUDE_CODE_SESSION_ID", "missing-claude"),
            ("codex", "CODEX_THREAD_ID", "missing-codex"),
        )
        for cli, variable, session_id in cases:
            with self.subTest(cli=cli, failure="missing id"):
                result = self.run_helper(cli)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "metrics unavailable\n")
                self.assertEqual(self.rows(), [])
            with self.subTest(cli=cli, failure="missing log"):
                result = self.run_helper(cli, **{variable: session_id})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "metrics unavailable\n")
                self.assertEqual(self.rows(), [])

    def test_pi_metrics_group_assistant_usage_and_report_pi_cost(self):
        session_id = "3b2c8d3e-31ba-4bf9-8ef3-0d4d3f74e45a"
        first = self.pi_message(
            "pi-entry-a", "pi-model-a",
            {"input": 100, "cacheRead": 20, "cacheWrite": 5,
             "output": 30, "totalTokens": 155,
             "cost": {"total": 0.0}},
            "2026-10-19T12:00:10Z",
        )
        second = self.pi_message(
            "pi-entry-b", "pi-model-b",
            {"input": 200, "cacheRead": 40, "cacheWrite": 10,
             "output": 50, "totalTokens": 300,
             "cost": {"total": 0.25}},
            "2026-10-19T12:01:00Z",
        )
        path, selectors = self.write_pi(
            session_id,
            [first, first, second,
             {"type": "toolResult", "id": "tool-entry",
              "content": "SYNTHETIC_TOOL_CONTENT"}],
        )
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"type":"message","partial":')
        result = self.run_helper("pi", **selectors)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()[0]
        self.assertEqual(row["cli_version"], "0.75.4")
        self.assertEqual(row["session_id"], session_id)
        self.assertEqual(set(row["models"]), {"pi-model-a", "pi-model-b"})
        self.assertEqual(row["usage_source"], "message_usage")
        self.assertEqual(row["tokens"], self.token_counts(375, 60, 15, 80, 0))
        self.assertEqual(
            row["model_usage"]["pi-model-a"],
            self.token_counts(125, 20, 5, 30, 0),
        )
        self.assertEqual(
            row["model_usage"]["pi-model-b"],
            self.token_counts(250, 40, 10, 50, 0),
        )
        self.assertEqual(row["cost_usd"], 0.25)
        self.assertEqual(row["cost_source"], "pi")
        self.assertEqual(row["session_seconds"], 60)
        self.assertIsNone(row["api_seconds"])
        self.assertIsNone(row["tool_seconds"])
        encoded = json.dumps(row)
        self.assertNotIn("SYNTHETIC_PROMPT", encoded)
        self.assertNotIn("SYNTHETIC_TOOL_CONTENT", encoded)

    def test_pi_missing_or_invalid_cost_is_unavailable_but_zero_is_valid(self):
        cases = (
            ("missing", {"input": 1, "output": 2}, None, "unavailable"),
            ("invalid", {"input": 1, "output": 2,
                         "cost": {"total": "not-a-number"}},
             None, "unavailable"),
            ("zero", {"input": 1, "output": 2,
                      "cost": {"total": 0}}, 0, "pi"),
        )
        for index, (suffix, usage, expected_cost, expected_source) in enumerate(
            cases
        ):
            with self.subTest(cost=suffix):
                session_id = f"5c4bf209-1f1b-4d01-90ae-{index:012x}"
                _, selectors = self.write_pi(
                    session_id,
                    [self.pi_message(
                        "entry-" + suffix, "pi-model", usage,
                        "2026-10-19T12:00:01Z",
                    )],
                    window_id=str(80 + len(self.rows())),
                )
                result = self.run_helper("pi", **selectors)
                self.assertEqual(result.returncode, 0, result.stderr)
                row = self.rows()[-1]
                self.assertEqual(row["cost_usd"], expected_cost)
                self.assertEqual(row["cost_source"], expected_source)

    def test_pi_requires_one_valid_session_file_and_safe_selectors(self):
        session_id = "3b2c8d3e-31ba-4bf9-8ef3-0d4d3f74e45a"
        _, unrelated_selectors = self.write_pi(
            session_id,
            [],
            window_id="91",
            started_at="1234567890",
            task="other-worker",
        )
        missing_dir = (
            self.crew_home / "runs" / "crew-v1" / "pi" / "91-1234567890"
        )
        missing_dir.mkdir(parents=True)
        with self.subTest(failure="unrelated worker log"):
            selectors = unrelated_selectors | {"CREW_TASK": "crew-v1"}
            result = self.run_helper("pi", **selectors)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "metrics unavailable\n")
            self.assertEqual(self.rows(), [])

        path, selectors = self.write_pi(
            session_id,
            [self.pi_message(
                "entry", "pi-model", {
                    "input": 1, "output": 1, "cost": {"total": 0.1},
                }, "2026-10-19T12:00:01Z",
            )],
        )
        with self.subTest(failure="ambiguous files"):
            self.write_jsonl(path.parent / "other.jsonl", [
                {"type": "session", "id": session_id, "version": 3,
                 "timestamp": "2026-10-19T12:00:00Z",
                 "cwd": "/synthetic/project"},
            ])
            result = self.run_helper("pi", **selectors)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "metrics unavailable\n")
            self.assertEqual(self.rows(), [])
        (path.parent / "other.jsonl").unlink()

        header_and_entries = path.read_text(encoding="utf-8").splitlines()
        invalid_header = json.loads(header_and_entries[0])
        invalid_header["timestamp"] = "not-a-timestamp"
        path.write_text(
            json.dumps(invalid_header) + "\n"
            + "\n".join(header_and_entries[1:]) + "\n",
            encoding="utf-8",
        )
        with self.subTest(failure="invalid header"):
            result = self.run_helper("pi", **selectors)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "metrics unavailable\n")
            self.assertEqual(self.rows(), [])

        for invalid in (
            {"CREW_TASK": "../escape"},
            {"KITTY_WINDOW_ID": "0"},
            {"CREW_STARTED_AT": "not-numeric"},
        ):
            with self.subTest(selector=invalid):
                result = self.run_helper("pi", **(selectors | invalid))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "metrics unavailable\n")
        self.assertEqual(self.rows(), [])

    def test_metrics_append_records_and_keep_status_and_report(self):
        session_id = "append-session"
        self.write_claude(session_id, [
            {"version": "3.0", "type": "assistant", "isSidechain": False,
             "message": {"id": "m1", "model": "model-a", "usage": {
                 "input_tokens": 1, "output_tokens": 2,
             }}},
        ])
        first = self.run_helper(
            "claude", status="done", report="first.md",
            CLAUDE_CODE_SESSION_ID=session_id,
        )
        second = self.run_helper(
            "claude", status="failed", report="second.md",
            CLAUDE_CODE_SESSION_ID=session_id,
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(len(first.stdout.splitlines()), 1)
        self.assertEqual(len(second.stdout.splitlines()), 1)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["status"] for row in rows], ["done", "failed"])
        self.assertEqual(
            [row["report"] for row in rows], ["first.md", "second.md"]
        )
        self.assertEqual(
            [row["session_id"] for row in rows], [session_id] * 2
        )

    def test_default_crew_home_uses_xdg_data_home_or_home_fallback(self):
        session_id = "default-home-session"
        self.write_claude(session_id, [
            self.claude_cost_state(0.1, 1, 2, 0, 0, 0),
        ])
        data_home = self.root / "xdg-data"
        env = self.env.copy()
        env.pop("CREW_HOME", None)
        env["XDG_DATA_HOME"] = str(data_home)
        env.update({
            "CREW_CLI": "claude",
            "CLAUDE_CODE_SESSION_ID": session_id,
        })
        result = subprocess.run(
            ["bash", str(HELPER), "record", "--status", "done",
             "--report", "xdg.md"],
            cwd=ROOT, env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.rows(data_home / "crew")), 1)

        env.pop("XDG_DATA_HOME")
        result = subprocess.run(
            ["bash", str(HELPER), "record", "--status", "done",
             "--report", "home.md"],
            cwd=ROOT, env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.rows(self.home / ".local/share/crew")), 1)

    def test_success_ignores_hyprland_environment_and_reports_unknowns(self):
        session_id = "minimal-session"
        self.write_claude(session_id, [
            {"version": "1.0", "type": "assistant", "isSidechain": False,
             "message": {"id": "m1", "model": "minimal-model", "usage": {
                 "input_tokens": 3, "output_tokens": 4,
             }}},
        ])
        env = self.env.copy()
        env["CLAUDE_CODE_SESSION_ID"] = session_id
        env["CREW_CLI"] = "claude"
        env["HYPRLAND_INSTANCE_SIGNATURE"] = "synthetic-session"
        env["XDG_RUNTIME_DIR"] = "/synthetic/runtime"
        result = subprocess.run(
            ["bash", str(HELPER), "record", "--status", "done",
             "--report", "minimal.md"],
            cwd=ROOT, env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()[0]
        self.assertIsNone(row["wall_seconds"])
        self.assertIsNone(row["tool_seconds"])
        self.assertIsNone(row["cost_usd"])
        self.assertIn("?", result.stdout)
        self.assertIn("cost unavailable", result.stdout)


if __name__ == "__main__":
    unittest.main()

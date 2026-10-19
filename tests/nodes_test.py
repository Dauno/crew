#!/usr/bin/env python3
"""Tests for the Kitty nodes helper."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "skills/nodes/scripts/nodes.sh"


class NodesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bin_dir = self.root / "bin"
        self.home = self.root / "home"
        self.work = self.root / "work"
        self.bin_dir.mkdir()
        self.home.mkdir()
        self.work.mkdir()
        self.log = self.root / "kitten.jsonl"
        self.crew_bin = self.root / "crew"
        self.crew_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.crew_bin.chmod(0o755)

        fake = self.bin_dir / "kitten"
        fake.write_text(
            "#!" + os.sys.executable + "\n"
            + "import json, os, sys\n"
            + "args = sys.argv[1:]\n"
            + "payload = ''\n"
            + "if '--stdin' in args:\n"
            + "  payload = sys.stdin.buffer.read().decode('utf-8')\n"
            + "data = {\n"
            + "  'args': args,\n"
            + "  'stdin': payload,\n"
            + "  'listen_on': os.environ.get('KITTY_LISTEN_ON'),\n"
            + "  'home': os.environ.get('HOME'),\n"
            + "  'hyprland_set': "
            + "'HYPRLAND_INSTANCE_SIGNATURE' in os.environ,\n"
            + "  'runtime_set': 'XDG_RUNTIME_DIR' in os.environ,\n"
            + "}\n"
            + "log = os.environ['FAKE_KITTEN_LOG']\n"
            + "with open(log, 'a', encoding='utf-8') as f:\n"
            + "  f.write(json.dumps(data) + '\\n')\n"
            + "if args[0:1] == ['@'] and args[-1:] == ['ls']:\n"
            + "  warning = os.environ.get('FAKE_KITTEN_STDERR', '')\n"
            + "  if warning: print(warning, file=sys.stderr)\n"
            + "  if os.environ.get('FAKE_KITTEN_FAIL_LS'):\n"
            + "    raise SystemExit(3)\n"
            + "  print(os.environ['FAKE_KITTEN_LS'])\n"
            + "elif 'get-text' in args:\n"
            + "  print('screen text')\n"
            + "elif 'launch' in args:\n"
            + "  print('41')\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)

        self.ls_data = [
            {
                "id": 1,
                "tabs": [
                    {
                        "id": 1,
                        "windows": [
                            {
                                "id": 7,
                                "title": "self window",
                                "cwd": "/tmp/self",
                                "cmdline": ["bash"],
                                "foreground_processes": [
                                    {"cmdline": ["claude"]}
                                ],
                                "user_vars": {
                                    "crew_node": "parent",
                                    "other": "ignored",
                                },
                            },
                            {
                                "id": 8,
                                "title": "worker window",
                                "cwd": "/tmp/worker",
                                "cmdline": ["bash"],
                                "foreground_processes": [
                                    {"cmdline": ["codex", "--help"]}
                                ],
                                "user_vars": {
                                    "crew_cli": "codex",
                                    "crew_role": "worker",
                                    "unrelated": "ignored",
                                },
                            },
                            {
                                "id": 9,
                                "title": "non-worker window",
                                "cwd": "/tmp/human",
                                "cmdline": ["bash"],
                                "foreground_processes": [
                                    {"cmdline": ["bash"]}
                                ],
                                "user_vars": {"crew_node": "human"},
                            },
                        ],
                    }
                ],
            }
        ]
        self.env = os.environ.copy()
        self.env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
        self.env.pop("XDG_RUNTIME_DIR", None)
        self.env.update(
            {
                "HOME": str(self.home),
                "PATH": (
                    str(self.bin_dir)
                    + os.pathsep
                    + self.env.get("PATH", "")
                ),
                "KITTY_LISTEN_ON": "unix:/tmp/crew-test.sock",
                "KITTY_WINDOW_ID": "7",
                "CREW_BIN": str(self.crew_bin),
                "FAKE_KITTEN_LOG": str(self.log),
                "FAKE_KITTEN_LS": json.dumps(self.ls_data),
            }
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_helper(self, *args, input_text=None, env=None):
        return subprocess.run(
            ["bash", str(HELPER), *args],
            input=input_text,
            capture_output=True,
            text=True,
            env=self.env if env is None else env,
            check=False,
        )

    def calls(self):
        if not self.log.exists():
            return []
        return [
            json.loads(line) for line in self.log.read_text().splitlines()
        ]

    def notify_environment(self):
        env = self.env.copy()
        env.update(
            {
                "KITTY_WINDOW_ID": "8",
                "CREW_TASK": "crew-v1",
                "CREW_NODE": "worker",
                "CREW_PARENT": "7",
            }
        )
        return env

    def test_list_emits_one_object_per_window(self):
        result = self.run_helper("list")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["id"], 7)
        self.assertEqual(rows[0]["command"], "claude")
        self.assertEqual(rows[0]["vars"], {"crew_node": "parent"})
        self.assertTrue(rows[0]["self"])
        self.assertEqual(rows[1]["command"], "codex --help")
        self.assertEqual(
            rows[1]["vars"], {"crew_cli": "codex", "crew_role": "worker"}
        )
        self.assertFalse(rows[1]["self"])
        self.assertEqual(rows[2]["id"], 9)
        self.assertFalse(rows[2]["self"])
        self.assertEqual(
            self.calls()[0]["listen_on"], "unix:/tmp/crew-test.sock"
        )

    def test_list_keeps_stderr_separate_from_json(self):
        env = self.env.copy()
        env["FAKE_KITTEN_STDERR"] = "harmless kitten warning"
        result = self.run_helper("list", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 3)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("harmless kitten warning", result.stdout)

    def test_ls_failure_reports_captured_stderr(self):
        env = self.env.copy()
        env["FAKE_KITTEN_STDERR"] = "kitten connection failed"
        env["FAKE_KITTEN_FAIL_LS"] = "1"
        result = self.run_helper("read", "8", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "kitten @ ls failed: kitten connection failed", result.stderr
        )

    def test_read_checks_id_and_prints_screen(self):
        result = self.run_helper("read", "8", "screen")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "screen text\n")
        call = self.calls()[-1]
        self.assertEqual(
            call["args"][-5:],
            ["get-text", "--match", "id:8", "--extent", "screen"],
        )

    def test_send_strips_carriage_returns_and_submits_separately(self):
        result = self.run_helper(
            "send", "8", "--enter", input_text="first\r\nsecond\r"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [call for call in self.calls() if "send-text" in call["args"]]
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [call["stdin"] for call in calls], ["first\nsecond", "\r"]
        )
        self.assertTrue(
            all(
                call["args"][-3:] == ["--match", "id:8", "--stdin"]
                for call in calls
            )
        )

    def test_empty_send_enter_fails_with_guidance(self):
        result = self.run_helper("send", "8", "--enter", input_text="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("use --enter-only", result.stderr)
        self.assertFalse(
            any("send-text" in call["args"] for call in self.calls())
        )

    def test_send_enter_only_sends_return_without_reading_input(self):
        result = self.run_helper(
            "send", "8", "--enter-only", input_text="must not be sent"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [call for call in self.calls() if "send-text" in call["args"]]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["stdin"], "\r")

    def test_notify_sends_formatted_notice_to_parent(self):
        report = self.root / "report.md"
        report.write_text("completed\n", encoding="utf-8")
        result = self.run_helper(
            "notify", "done", str(report), env=self.notify_environment()
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [call for call in self.calls() if "send-text" in call["args"]]
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [call["stdin"] for call in calls],
            [f"crew-v1/worker: done. Report: {report}", "\r"],
        )
        self.assertTrue(
            all(
                call["args"][-3:] == ["--match", "id:7", "--stdin"]
                for call in calls
            )
        )

    def test_notify_requires_task_node_parent_and_report(self):
        report = self.root / "report.md"
        report.write_text("completed\n", encoding="utf-8")
        for variable in ("CREW_TASK", "CREW_NODE", "CREW_PARENT"):
            with self.subTest(variable=variable):
                env = self.notify_environment()
                env.pop(variable)
                result = self.run_helper(
                    "notify", "done", str(report), env=env
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(variable, result.stderr)
        env = self.notify_environment()
        result = self.run_helper(
            "notify", "", str(report), env=env
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STATUS must not be empty", result.stderr)
        result = self.run_helper(
            "notify", "done", str(self.root / "missing.md"), env=env
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("existing file", result.stderr)

    def test_send_and_close_refuse_the_own_window(self):
        for command in (("send", "7"), ("close", "7")):
            with self.subTest(command=command):
                result = self.run_helper(*command, input_text="do not send")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("this window", result.stderr)
        self.assertFalse(
            any("send-text" in call["args"] for call in self.calls())
        )
        self.assertFalse(
            any("close-window" in call["args"] for call in self.calls())
        )

    def test_spawn_sets_worker_environment_and_labels(self):
        result = self.run_helper(
            "spawn",
            "--name",
            "reviewer",
            "--cli",
            "codex",
            "--cwd",
            str(self.work),
            "--task",
            "crew-v1",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "41\n")
        args = self.calls()[-1]["args"]
        self.assertEqual(
            args[:5],
            ["@", "--to", "unix:/tmp/crew-test.sock", "launch", "--type=tab"],
        )
        for value in (
            "--keep-focus",
            "--copy-env",
            "--cwd",
            str(self.work),
            "--env",
            "CREW_CLI=codex",
            "CREW_ROLE=worker",
            "CREW_NODE=reviewer",
            "CREW_TASK=crew-v1",
            "CREW_PARENT=7",
            "--tab-title",
            "reviewer · codex",
            "--var",
            "crew_node=reviewer",
            "crew_cli=codex",
            "crew_role=worker",
            "crew_task=crew-v1",
            "crew_parent=7",
            str(self.crew_bin),
            "codex",
        ):
            self.assertIn(value, args)
        self.assertEqual(args[-2:], [str(self.crew_bin), "codex"])
        self.assertFalse(self.calls()[-1]["hyprland_set"])
        self.assertFalse(self.calls()[-1]["runtime_set"])

    def test_spawn_passes_cli_args_in_order_without_splitting(self):
        result = self.run_helper(
            "spawn",
            "--name",
            "haiku",
            "--cli",
            "claude",
            "--cwd",
            str(self.work),
            "--",
            "--model",
            "claude-haiku-5-5",
            "--option",
            "two words",
            "--literal=three words",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.calls()[-1]["args"]
        self.assertEqual(
            args[-7:],
            [
                str(self.crew_bin),
                "claude",
                "--model",
                "claude-haiku-5-5",
                "--option",
                "two words",
                "--literal=three words",
            ],
        )

    def test_close_uses_an_exact_numeric_id(self):
        result = self.run_helper("close", "8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.calls()[-1]["args"][-3:],
            ["close-window", "--match", "id:8"],
        )

    def test_interrupt_sends_escape_to_worker(self):
        result = self.run_helper("interrupt", "8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.calls()[-1]["args"][-4:],
            ["send-key", "--match", "id:8", "Escape"],
        )

    def test_interrupt_refuses_self_and_non_workers(self):
        for ident, reason in (("7", "this window"), ("9", "not labeled")):
            with self.subTest(ident=ident):
                result = self.run_helper("interrupt", ident)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(reason, result.stderr)
        self.assertFalse(
            any("send-key" in call["args"] for call in self.calls())
        )

    def test_close_refuses_non_workers(self):
        result = self.run_helper("close", "9")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not labeled crew_role=worker", result.stderr)
        self.assertFalse(
            any("close-window" in call["args"] for call in self.calls())
        )

    def test_missing_window_fails_clearly(self):
        result = self.run_helper("read", "99")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no Kitty window has ID 99", result.stderr)


if __name__ == "__main__":
    unittest.main()

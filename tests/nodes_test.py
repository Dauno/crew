#!/usr/bin/env python3
"""Tests for the Kitty nodes helper."""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "skills/nodes/scripts/nodes.sh"


class NodesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bin_dir = self.root / "bin"
        self.script_dir = self.root / "scripts"
        self.script_dir.mkdir()
        self.helper = self.script_dir / "nodes.sh"
        shutil.copy2(HELPER, self.helper)
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
            + "import json, os, subprocess, sys\n"
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
            + "  if '--ansi' not in args:\n"
            + "    print('screen text')\n"
            + "  elif os.environ.get('FAKE_KITTEN_SEQUENCE_FILE'):\n"
            + "    sequence_file = os.environ['FAKE_KITTEN_SEQUENCE_FILE']\n"
            + "    with open(sequence_file, encoding='utf-8') as f:\n"
            + "      sequence = json.load(f)\n"
            + "    counter_path = os.environ[\n"
            + "      'FAKE_KITTEN_SEQUENCE_COUNTER']\n"
            + "    try:\n"
            + "      with open(counter_path, encoding='utf-8') as f:\n"
            + "        index = int(f.read())\n"
            + "    except FileNotFoundError:\n"
            + "      index = 0\n"
            + "    with open(counter_path, 'w', encoding='utf-8') as f:\n"
            + "      f.write(str(index + 1))\n"
            + "    sys.stdout.write(sequence[\n"
            + "      min(index, len(sequence) - 1)])\n"
            + "  elif os.environ.get('FAKE_KITTEN_TEXT_FILE'):\n"
            + "    text_path = os.environ['FAKE_KITTEN_TEXT_FILE']\n"
            + "    with open(text_path, encoding='utf-8') as f:\n"
            + "      sys.stdout.write(f.read())\n"
            + "  else:\n"
            + "    sys.stdout.write(os.environ.get('FAKE_KITTEN_TEXT', ''))\n"
            + "elif 'launch' in args:\n"
            + "  if '--type=background' in args:\n"
            + "    if os.environ.get('FAKE_KITTEN_FAIL_BACKGROUND'):\n"
            + "      print('background launch failed', file=sys.stderr)\n"
            + "      raise SystemExit(5)\n"
            + "    child_env = os.environ.copy()\n"
            + "    for index, option in enumerate(args[:-1]):\n"
            + "      if option == '--env' and '=' in args[index + 1]:\n"
            + "        name, value = args[index + 1].split('=', 1)\n"
            + "        child_env[name] = value\n"
            + "    try:\n"
            + "      subprocess.Popen(args[-4:], stdin=subprocess.DEVNULL,\n"
            + "        stdout=subprocess.DEVNULL,\n"
            + "        stderr=subprocess.DEVNULL,\n"
            + "        env=child_env, start_new_session=True)\n"
            + "    except OSError as error:\n"
            + "      print('background launch failed:', error,\n"
            + "        file=sys.stderr)\n"
            + "      raise SystemExit(5)\n"
            + "  else:\n"
            + "    print('41')\n",
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
                "FAKE_KITTEN_TEXT": "\u001b[m❯ \u001b[22;2mTry a sample task",
                "CREW_RUNS": str(self.root / "runs"),
                "FAKE_METRICS_LOG": str(self.root / "metrics.jsonl"),
            }
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_helper(self, *args, input_text=None, env=None):
        return subprocess.run(
            ["bash", str(self.helper), *args],
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

    def enable_test_waits(self, env, send=1, notice=3):
        env.update(
            {
                "CREW_NODES_TESTING": "1",
                "CREW_NODES_TEST_SEND_WAIT_SECONDS": str(send),
                "CREW_NODES_TEST_NOTICE_WAIT_SECONDS": str(notice),
            }
        )
        return env

    def write_input(self, text):
        path = self.root / "input.txt"
        path.write_text(text, encoding="utf-8")
        return path

    @staticmethod
    def pi_frame(
        editor_rows=("\u001b[7m \u001b[27m",),
        history="",
        context="0.0%/0 (auto) unknown",
        extension_status=None,
        top_border=None,
    ):
        border = "\u001b[m\u001b[38:2:80:80:80m" + "─" * 40
        rows = []
        if history:
            rows.append(history)
        rows.append(border if top_border is None else top_border)
        rows.extend(editor_rows)
        rows.extend((
            border,
            "\u001b[m/tmp/synthetic-project",
            "\u001b[m" + context,
        ))
        if extension_status is not None:
            rows.append(extension_status)
        return "\n".join(rows)

    @staticmethod
    def pi_custom_frame(top_border, bottom_border, autocomplete_rows=()):
        return "\n".join((
            top_border,
            "synthetic human draft",
            bottom_border,
            *autocomplete_rows,
            "/tmp/synthetic-project",
            "0.0%/200k (auto) model",
        ))

    def install_metrics(self, content):
        path = self.script_dir / "metrics.sh"
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)
        return path

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

    def test_send_enter_accepts_placeholder_and_suggestion_styles(self):
        fixtures = {
            "claude placeholder": (
                "\u001b[m❯ \u001b[22;2mTry \\\"write a test\\\""
            ),
            "codex placeholder": (
                "\u001b[22;1;48:2:30:30:30m›\u001b[22m "
                "\u001b[22;2mAsk Codex to do anything"
            ),
            "suggestion popup": (
                "\u001b[38:2:177:185:249m❯ /kitty-nodes Create and coordinate"
                "\n\u001b[m❯ \u001b[22;2mTry a sample task"
            ),
        }
        for label, fixture in fixtures.items():
            with self.subTest(label=label):
                env = self.env.copy()
                env["FAKE_KITTEN_TEXT"] = fixture
                result = self.run_helper(
                    "send", "8", "--enter", input_text="test message", env=env
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_claude_context_status_preserves_clear_and_busy_states(self):
        parser = self.helper.read_text(encoding="utf-8").split(
            "python3 -c '\n", 1
        )[1].split("\n') ; then", 1)[0]
        fixtures = {
            "clear": "\u001b[m❯ \u001b[2mTry a synthetic task",
            "busy": "\u001b[m❯ synthetic human draft",
        }
        footers = {
            "context only": ("ctx 12%/200k",),
            "cwd and context": ("/home/u/proj", "ctx 12%/200k"),
            "home and context": ("~/proj", "ctx 12%/200k"),
            "cwd and bare context": ("~/proj", "12%/200k"),
            "cwd context and bypass": (
                "~/proj", "ctx 12%/200k", "⏵⏵ bypass",
            ),
            "plan mode": ("── plan mode ────",),
        }
        for expected, prompt in fixtures.items():
            for label, footer in footers.items():
                with self.subTest(state=expected, footer=label):
                    fixture = "\n".join((
                        "─" * 40, prompt, "\u001b[m" + "─" * 40,
                        *footer,
                    ))
                    result = subprocess.run(
                        [os.sys.executable, "-c", parser], input=fixture,
                        capture_output=True, text=True, env=self.env,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), expected)

    def test_codex_empty_prompt_ignores_plain_footer_rows(self):
        fixture_path = ROOT / "tests/fixtures/codex-empty-prompt.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        env = self.enable_test_waits(self.env.copy(), send=1)
        env["FAKE_KITTEN_TEXT"] = fixture["ansi"]
        result = self.run_helper(
            "send", "8", "--enter", input_text="synthetic notice", env=env
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [call["stdin"] for call in self.calls()
             if "send-text" in call["args"]],
            ["synthetic notice", "\r"],
        )

    def test_pi_border_editor_input_states(self):
        fixtures = {
            "empty beside old prompt text": (
                self.pi_frame(
                    history="\u001b[m❯ old transcript prompt text"
                ),
                "clear",
            ),
            "typed colored text": (
                self.pi_frame((
                    "\u001b[38:2:102:102:102msynthetic human draft",
                )),
                "busy",
            ),
            "multiline draft": (
                self.pi_frame(("first synthetic line", "second line")),
                "busy",
            ),
            "working command keeps blank editor": (
                self.pi_frame(
                    history="\u001b[m⠴ Running synthetic command"
                ),
                "clear",
            ),
            "blank rows below the footer": (
                self.pi_frame() + "\n" * 4,
                "clear",
            ),
            "prior command border above empty editor": (
                "─" * 40 + "\nEarlier Pi output\n"
                + self.pi_frame(),
                "clear",
            ),
            "compact context window count": (
                self.pi_frame(context="0.0%/200k (auto) unknown"),
                "clear",
            ),
            "million token context window count": (
                self.pi_frame(context="0.0%/1.0M (auto) unknown"),
                "clear",
            ),
            "used session stats": (
                self.pi_frame(
                    context=(
                        "↑1.2k ↓300 R5.0k $0.012 "
                        "3.2%/200k (auto) model"
                    )
                ),
                "clear",
            ),
            "subscription zero cost": (
                self.pi_frame(
                    context="↑1.2k ↓300 $0.000 (sub) 3.2%/200k model"
                ),
                "clear",
            ),
            "unknown context percentage after compaction": (
                self.pi_frame(context="?/200k (auto) model"),
                "clear",
            ),
            "warning colored context percentage": (
                self.pi_frame(
                    context=(
                        "↑1.2k $0.012 "
                        "\u001b[38:2:255:200:0m75.0%/200k\u001b[39m model"
                    )
                ),
                "clear",
            ),
            "error colored context percentage": (
                self.pi_frame(
                    context=(
                        "↑1.2k $0.012 "
                        "\u001b[38:2:255:100:100m95.0%/200k\u001b[39m model"
                    )
                ),
                "clear",
            ),
            "context without auto indicator": (
                self.pi_frame(context="3.2%/200k model"),
                "clear",
            ),
            "extension status row": (
                self.pi_frame(
                    context="3.2%/200k (auto) model",
                    extension_status="\u001b[2mtest extension status",
                ),
                "clear",
            ),
            "overlay content": (
                "\u001b[m" + "─" * 40 + "\n"
                "\u001b[m> \u001b[7m \u001b[27m\n"
                "\u001b[38:2:138:190:183m↕ Auto-compact"
                "          \u001b[39mtrue\n"
                "\u001b[m  Show images             true\n"
                "\u001b[m  Image width             60\n"
                "\u001b[m\n"
                "\u001b[2mAutomatically compact context"
                " when it gets too large\n"
                "\u001b[2mType to search · Enter/Space"
                " to change · Esc to cancel\n"
                "\u001b[m" + "─" * 40 + "\n"
                "\u001b[m/tmp/synthetic-project\n"
                "\u001b[m0.0%/200k (auto) model",
                "busy",
            ),
            "incomplete frame": (
                "─" * 40 + "\n\n/tmp/synthetic-project\n"
                "0.0%/0 (auto) unknown",
                "unknown",
            ),
            "old horizontal box without footer": (
                "─" * 40 + "\n\n" + "─" * 40,
                "unknown",
            ),
        }
        for label, (fixture, expected) in fixtures.items():
            with self.subTest(label=label):
                self.log.write_text("", encoding="utf-8")
                env = self.enable_test_waits(self.env.copy(), send=1)
                env["FAKE_KITTEN_TEXT"] = fixture
                result = self.run_helper(
                    "send", "8", "--enter", input_text="synthetic notice",
                    env=env,
                )
                sent = [call["stdin"] for call in self.calls()
                        if "send-text" in call["args"]]
                if expected == "clear":
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(sent, ["synthetic notice", "\r"])
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("input stayed occupied", result.stderr)
                    self.assertEqual(sent, [])

    def test_pi_active_working_editor_accepts_only_empty_frames(self):
        for spinner in "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏":
            with self.subTest(spinner=spinner):
                self.log.write_text("", encoding="utf-8")
                env = self.enable_test_waits(self.env.copy(), send=0)
                env["FAKE_KITTEN_TEXT"] = self.pi_frame(
                    top_border=(
                        "\u001b[m── \u001b[36m" + spinner
                        + "\u001b[39m Working " + "─" * 27
                    ),
                    context="0.0%/1.1M (auto) model",
                )
                result = self.run_helper(
                    "send", "8", "--enter", input_text="synthetic notice",
                    env=env,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    [call["stdin"] for call in self.calls()
                     if "send-text" in call["args"]],
                    ["synthetic notice", "\r"],
                )

    def test_pi_active_editor_rejects_drafts_and_unknown_layouts(self):
        active = "── ⠏ Working " + "─" * 27
        clear = self.pi_frame(top_border=active)
        fixtures = {
            "draft": self.pi_frame(("synthetic human draft",),
                                   top_border=active),
            "dim draft": self.pi_frame(("\u001b[2mdraft",),
                                       top_border=active),
            "multiline": self.pi_frame(("first", "second"),
                                       top_border=active),
            "dialog": self.pi_frame(("Trust project folder?",),
                                    top_border=active),
            "overlay": self.pi_frame(("Settings", "Enter to confirm"),
                                     top_border=active),
            "autocomplete": clear.replace(
                "/tmp/synthetic-project", "/help  Show help\n"
                "/model Select model\n/tmp/synthetic-project"
            ),
            "wrong width": self.pi_frame(top_border=active + "─"),
            "unknown status": self.pi_frame(
                top_border="── ⠏ Unknown " + "─" * 27
            ),
            "scroll indicator": self.pi_frame(
                top_border="── ⠏ Working ─ ↑ 2 more " + "─" * 17
            ),
            "missing top": clear.split("\n", 1)[1],
            "missing top with usage": self.pi_frame(
                context="↑1.2k ↓300 3.2%/200k model"
            ).split("\n", 1)[1],
            "missing top with cost": self.pi_frame(
                context="$0.000 (sub) 3.2%/200k model"
            ).split("\n", 1)[1],
            "missing top with extension": self.pi_frame(
                extension_status="synthetic extension status"
            ).split("\n", 1)[1],
            "missing editor row": clear.replace("\u001b[7m \u001b[27m\n", ""),
            "missing bottom": "\n".join(clear.splitlines()[:2]
                                           + clear.splitlines()[3:]),
            "unknown footer": self.pi_frame(top_border=active,
                                             context="unknown stats"),
        }
        histories = ("", "❯ \u001b[2mold transcript\u001b[m\n",
                     "› \u001b[2mold suggestion\u001b[m\n")
        for label, fixture in fixtures.items():
            for history in histories:
                with self.subTest(layout=label, history=history):
                    self.log.write_text("", encoding="utf-8")
                    env = self.enable_test_waits(self.env.copy(), send=0)
                    env["FAKE_KITTEN_TEXT"] = history + fixture
                    result = self.run_helper(
                        "send", "8", "--enter",
                        input_text="synthetic notice", env=env,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(
                        [call for call in self.calls()
                         if "send-text" in call["args"]], [],
                    )

    def test_pi_active_editor_rechecks_before_typing(self):
        top = "── ⠏ Working " + "─" * 27
        clear = self.pi_frame(top_border=top)
        busy = self.pi_frame(("synthetic human draft",), top_border=top)
        sequence = self.root / "active-sequence.json"
        sequence.write_text(json.dumps([clear, busy]), encoding="utf-8")
        env = self.enable_test_waits(self.env.copy(), send=0)
        env["FAKE_KITTEN_SEQUENCE_FILE"] = str(sequence)
        env["FAKE_KITTEN_SEQUENCE_COUNTER"] = str(self.root / "input-count")
        result = self.run_helper(
            "send", "8", "--enter", input_text="synthetic notice", env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            [call for call in self.calls() if "send-text" in call["args"]],
            [],
        )

    def test_pi_unrecognized_footer_does_not_fall_through_to_other_markers(
        self,
    ):
        histories = {
            "Claude": "\u001b[m❯ \u001b[2msome dim transcript line",
            "Codex": "\u001b[m  › \u001b[2mdim transcript line",
        }
        for label, history in histories.items():
            with self.subTest(label=label):
                env = self.enable_test_waits(self.env.copy(), send=1)
                env["FAKE_KITTEN_TEXT"] = self.pi_frame(
                    ("synthetic human draft",),
                    history=history,
                    context="unrecognized stats row",
                )
                result = self.run_helper(
                    "send", "8", "--enter", input_text="synthetic notice",
                    env=env,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("input stayed occupied", result.stderr)
                self.assertEqual(
                    [call for call in self.calls()
                     if "send-text" in call["args"]],
                    [],
                )

    def test_pi_scroll_borders_and_autocomplete_fail_closed(self):
        solid = "─" * 40
        scroll_up = "─── ↑ 2 more " + "─" * 20
        scroll_down = "─── ↓ 1 more " + "─" * 20
        histories = {
            "Claude": "\n".join((
                "\u001b[38:2:128:128:128m " + solid,
                "\u001b[38:2:128:128:128m ❯ ",
                "\u001b[38:2:128:128:128m " + solid,
            )),
            "Codex": (
                "\u001b[38:2:128:128:128m › "
                "\u001b[2mTry a synthetic command"
            ),
        }
        layouts = {
            "scroll-up": self.pi_custom_frame(scroll_up, solid),
            "scroll-down": self.pi_custom_frame(solid, scroll_down),
            "autocomplete": self.pi_custom_frame(
                solid,
                solid,
                autocomplete_rows=(
                    "  /help  Show help",
                    "  /model Select model",
                ),
            ),
        }
        fixtures = [
            ("Claude", "scroll-up", layouts["scroll-up"]),
            ("Claude", "scroll-down", layouts["scroll-down"]),
            ("Claude", "autocomplete", layouts["autocomplete"]),
            ("Codex", "scroll-up", layouts["scroll-up"]),
            ("Codex", "autocomplete", layouts["autocomplete"]),
        ]
        for history_name, layout_name, frame in fixtures:
            with self.subTest(history=history_name, layout=layout_name):
                self.log.write_text("", encoding="utf-8")
                env = self.enable_test_waits(self.env.copy(), send=1)
                env["FAKE_KITTEN_TEXT"] = (
                    histories[history_name] + "\n" + frame
                )
                result = self.run_helper(
                    "send", "8", "--enter", input_text="synthetic notice",
                    env=env,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("input stayed occupied", result.stderr)
                self.assertEqual(
                    [call for call in self.calls()
                     if "send-text" in call["args"]],
                    [],
                )

    def test_pi_send_rechecks_the_editor_before_typing(self):
        clear = self.pi_frame()
        busy = self.pi_frame(("synthetic human draft",))
        sequence_path = self.root / "input-sequence.json"
        sequence_path.write_text(
            json.dumps([clear, busy, clear, clear]), encoding="utf-8"
        )
        env = self.enable_test_waits(self.env.copy(), send=2)
        env["FAKE_KITTEN_SEQUENCE_FILE"] = str(sequence_path)
        env["FAKE_KITTEN_SEQUENCE_COUNTER"] = str(self.root / "input-count")
        result = self.run_helper(
            "send", "8", "--enter", input_text="synthetic notice", env=env
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        send_index = next(
            index for index, call in enumerate(calls)
            if "send-text" in call["args"]
        )
        self.assertGreaterEqual(
            sum("get-text" in call["args"] for call in calls[:send_index]), 4
        )

    def test_send_enter_waits_until_occupied_input_is_cleared(self):
        input_path = self.write_input("\u001b[m❯ review the build result")
        env = self.enable_test_waits(self.env.copy(), send=2)
        env["FAKE_KITTEN_TEXT_FILE"] = str(input_path)
        process = subprocess.Popen(
            ["bash", str(self.helper), "send", "8", "--enter"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        process.stdin.write("worker message")
        process.stdin.close()
        process.stdin = None
        for _ in range(40):
            if any("get-text" in call["args"] for call in self.calls()):
                break
            time.sleep(0.025)
        self.assertFalse(
            any("send-text" in call["args"] for call in self.calls())
        )
        input_path.write_text(
            "\u001b[m❯ \u001b[22;2mTry a sample task",
            encoding="utf-8",
        )
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(stdout, "")
        sent = [
            call["stdin"] for call in self.calls()
            if "send-text" in call["args"]
        ]
        self.assertEqual(
            sent,
            ["worker message", "\r"],
        )

    def test_send_enter_rechecks_input_before_typing(self):
        clear = "\u001b[m❯ \u001b[22;2mTry a sample task"
        busy = "\u001b[m❯ human text"
        sequence_path = self.root / "input-sequence.json"
        sequence_path.write_text(
            json.dumps([clear, busy, clear, clear]), encoding="utf-8"
        )
        env = self.enable_test_waits(self.env.copy(), send=2)
        env["FAKE_KITTEN_SEQUENCE_FILE"] = str(sequence_path)
        env["FAKE_KITTEN_SEQUENCE_COUNTER"] = str(self.root / "input-count")
        result = self.run_helper(
            "send", "8", "--enter", input_text="worker message", env=env
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        send_index = next(
            index for index, call in enumerate(calls)
            if "send-text" in call["args"]
        )
        self.assertGreaterEqual(
            sum("get-text" in call["args"] for call in calls[:send_index]), 4
        )

    def test_send_enter_times_out_for_busy_or_unrecognized_input(self):
        for fixture in (
            "\u001b[m❯ human text",
            "\u001b[m❯ Try a sample task",
            "no recognized prompt",
        ):
            with self.subTest(fixture=fixture):
                env = self.enable_test_waits(self.env.copy(), send=2)
                env["FAKE_KITTEN_TEXT"] = fixture
                started = time.monotonic()
                result = self.run_helper(
                    "send", "8", "--enter", input_text="worker message",
                    env=env,
                )
                elapsed = time.monotonic() - started
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "input stayed occupied or unrecognized", result.stderr
                )
                self.assertGreaterEqual(elapsed, 0.5)
                self.assertLess(elapsed, 5)
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

    def test_notify_records_metrics_and_sends_summary(self):
        report = self.root / "report.md"
        report.write_text("completed\n", encoding="utf-8")
        self.install_metrics(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$*\" >>\"$FAKE_METRICS_LOG\"\n"
            "printf '%s\\n' 'input=12 output=3'\n"
        )
        result = self.run_helper(
            "notify", "done", str(report), env=self.notify_environment()
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [call for call in self.calls() if "send-text" in call["args"]]
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [call["stdin"] for call in calls],
            [
                f"crew-v1/worker: done. Report: {report}. "
                "Metrics: input=12 output=3",
                "\r",
            ],
        )
        self.assertEqual(
            (self.root / "metrics.jsonl").read_text(encoding="utf-8"),
            f"record --status done --report {report}\n",
        )
        self.assertFalse(
            list((self.root / "runs" / "crew-v1" / "notices").glob("*"))
        )
        self.assertTrue(
            all(
                call["args"][-3:] == ["--match", "id:7", "--stdin"]
                for call in calls
            )
        )

    def test_notify_uses_unavailable_when_metrics_are_missing(self):
        report = self.root / "report.md"
        report.write_text("completed\n", encoding="utf-8")
        result = self.run_helper(
            "notify", "done", str(report), env=self.notify_environment()
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [call for call in self.calls() if "send-text" in call["args"]]
        self.assertEqual(
            calls[0]["stdin"],
            f"crew-v1/worker: done. Report: {report}. "
            "Metrics: metrics unavailable",
        )

    def test_notify_uses_unavailable_when_metrics_fail(self):
        report = self.root / "report.md"
        report.write_text("completed\n", encoding="utf-8")
        self.install_metrics(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' 'short metrics failure' >&2\n"
            "exit 4\n"
        )
        result = self.run_helper(
            "notify", "done", str(report), env=self.notify_environment()
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        calls = [call for call in self.calls() if "send-text" in call["args"]]
        self.assertEqual(
            calls[0]["stdin"],
            f"crew-v1/worker: done. Report: {report}. "
            "Metrics: metrics unavailable",
        )

    def test_notify_detached_sender_keeps_notice_until_delivery(self):
        report = self.root / "report.md"
        report.write_text("completed\n", encoding="utf-8")
        drafts = {
            "claude": "\u001b[m❯ human is still writing",
            "pi": self.pi_frame(("human is still writing",)),
        }
        for cli, draft in drafts.items():
            with self.subTest(cli=cli):
                self.log.write_text("", encoding="utf-8")
                input_path = self.write_input(draft)
                env = self.enable_test_waits(
                    self.notify_environment(), send=2, notice=5
                )
                env["CREW_CLI"] = cli
                env["FAKE_KITTEN_TEXT_FILE"] = str(input_path)
                started = time.monotonic()
                result = self.run_helper(
                    "notify", "done", str(report), env=env
                )
                elapsed = time.monotonic() - started
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertGreaterEqual(elapsed, 0.8)
                self.assertLess(elapsed, 5)
                notices = self.root / "runs" / "crew-v1" / "notices"
                pending = [
                    path for path in notices.glob("notice.*")
                    if not path.name.endswith(".status")
                ]
                self.assertEqual(len(pending), 1)
                expected = (
                    f"crew-v1/worker: done. Report: {report}. "
                    "Metrics: metrics unavailable"
                )
                self.assertEqual(
                    pending[0].read_text(encoding="utf-8").strip(),
                    expected,
                )
                self.assertIn("human is still writing", input_path.read_text())
                launch_call = next(
                    call for call in self.calls()
                    if "launch" in call["args"]
                    and "--type=background" in call["args"]
                )
                for value in (
                    "--allow-remote-control",
                    "--copy-env",
                    "CREW_PARENT=7",
                    "CREW_NODES_TESTING=1",
                    "CREW_NODES_TEST_NOTICE_WAIT_SECONDS=5",
                    f"CREW_NOTICE_PENDING={pending[0]}",
                ):
                    self.assertIn(value, launch_call["args"])

                clear = self.pi_frame() if cli == "pi" else (
                    "\u001b[m❯ \u001b[22;2mTry a sample task"
                )
                input_path.write_text(clear, encoding="utf-8")
                deadline = time.monotonic() + 6
                while pending[0].exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertFalse(pending[0].exists())
                calls = [
                    call for call in self.calls()
                    if "send-text" in call["args"]
                ]
                self.assertEqual(
                    [call["stdin"] for call in calls], [expected, "\r"]
                )

    def test_detached_sender_leaves_notice_after_its_wait_limit(self):
        pending_dir = self.root / "runs" / "crew-v1" / "notices"
        pending_dir.mkdir(parents=True)
        pending = pending_dir / "notice.pending"
        pending.write_text("crew-v1/worker: done", encoding="utf-8")
        input_path = self.write_input("\u001b[m❯ human text")
        env = self.enable_test_waits(self.notify_environment(), notice=2)
        env["FAKE_KITTEN_TEXT_FILE"] = str(input_path)
        started = time.monotonic()
        result = self.run_helper("_deliver-pending", str(pending), env=env)
        elapsed = time.monotonic() - started
        self.assertNotEqual(result.returncode, 0)
        self.assertGreaterEqual(elapsed, 0.5)
        self.assertLess(elapsed, 5)
        self.assertEqual(
            pending.read_text(encoding="utf-8"), "crew-v1/worker: done"
        )
        status = Path(f"{pending}.status").read_text(encoding="utf-8")
        self.assertIn("state=failed", status)
        self.assertIn("last_input=busy", status)
        self.assertIn("Wait limit 2s expired", status)
        self.assertFalse(
            any("send-text" in call["args"] for call in self.calls())
        )

    def test_notify_keeps_reason_when_kitty_cannot_start_sender(self):
        report = self.root / "report.md"
        report.write_text("completed\n", encoding="utf-8")
        input_path = self.write_input("\u001b[m❯ human text")
        env = self.enable_test_waits(self.notify_environment(), send=2)
        env["FAKE_KITTEN_TEXT_FILE"] = str(input_path)
        env["FAKE_KITTEN_FAIL_BACKGROUND"] = "1"
        result = self.run_helper("notify", "done", str(report), env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("background sender failed", result.stderr)
        notices = self.root / "runs" / "crew-v1" / "notices"
        pending = [
            path for path in notices.glob("notice.*")
            if not path.name.endswith(".status")
        ]
        self.assertEqual(len(pending), 1)
        self.assertIn("Metrics: metrics unavailable", pending[0].read_text())
        status = Path(f"{pending[0]}.status").read_text(encoding="utf-8")
        self.assertIn("state=failed", status)
        self.assertIn("last_input=busy", status)
        self.assertIn("Kitty background launch failed", status)

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
        before = int(time.time())
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
        after = int(time.time())
        args = self.calls()[-1]["args"]
        started_values = [
            value.removeprefix("CREW_STARTED_AT=")
            for index, value in enumerate(args)
            if index > 0 and args[index - 1] == "--env"
            and value.startswith("CREW_STARTED_AT=")
        ]
        self.assertEqual(len(started_values), 1)
        self.assertLessEqual(before, int(started_values[0]))
        self.assertLessEqual(int(started_values[0]), after)
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

    def test_spawn_supports_pi_labels_and_argument_forwarding(self):
        result = self.run_helper(
            "spawn", "--name", "pi-worker", "--cli", "pi",
            "--cwd", str(self.work), "--task", "crew-v1", "--",
            "--offline", "two words",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.calls()[-1]["args"]
        for value in (
            "CREW_CLI=pi",
            "CREW_ROLE=worker",
            "CREW_NODE=pi-worker",
            "CREW_TASK=crew-v1",
            "CREW_PARENT=7",
            "pi-worker · pi",
            "crew_cli=pi",
            "crew_node=pi-worker",
            "crew_role=worker",
            "crew_task=crew-v1",
            str(self.crew_bin),
        ):
            self.assertIn(value, args)
        self.assertEqual(
            args[-4:], [str(self.crew_bin), "pi", "--offline", "two words"]
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

    def test_missing_runtime_tool_fails_with_its_name(self):
        for missing in ("jq", "python3"):
            with self.subTest(missing=missing):
                tool_dir = self.root / f"tools-without-{missing}"
                tool_dir.mkdir()
                for program in ("bash", "jq", "python3"):
                    if program == missing:
                        continue
                    source = shutil.which(program)
                    self.assertIsNotNone(source)
                    (tool_dir / program).symlink_to(source)
                env = self.env.copy()
                env["PATH"] = str(tool_dir)
                result = self.run_helper("list", env=env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(missing, result.stderr)
                self.assertIn("not found on PATH", result.stderr)


if __name__ == "__main__":
    unittest.main()

import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


REPO = pathlib.Path(__file__).resolve().parents[1]
LAUNCHER = REPO / "bin" / "crew"


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="crew-launcher-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / "home"
        self.bin = self.root / "fake-bin"
        self.project = self.root / "test-project"
        self.skills = self.root / "skills"
        self.plugin = self.root / "plugin"
        self.tmp = self.root / "tmp"
        for path in (
            self.home,
            self.bin,
            self.project,
            self.skills,
            self.plugin,
            self.tmp,
        ):
            path.mkdir(parents=True)
        self.capture = self.root / "capture.json"
        self.core = self.root / "instructions.md"
        self.core.write_text("# Fixture core instructions\n\nCORE_MARKER\n")
        helper = self.skills / "nodes" / "scripts" / "nodes.sh"
        helper.parent.mkdir(parents=True)
        helper.write_text("#!/usr/bin/env bash\nexit 0\n")
        helper.chmod(0o755)
        for name in ("nodes", "memory", "onboard"):
            skill_dir = self.skills / name
            skill_dir.mkdir(exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Fixture {name} skill\n---\n"
            )
        (self.plugin / ".claude-plugin").mkdir()
        (self.plugin / ".claude-plugin" / "plugin.json").write_text(
            '{"name":"fixture","version":"1.0.0"}\n'
        )
        self._write_program(
            "claude",
            f"#!{sys.executable}\n" + """import json, os, pathlib, sys
keys = (
    "CREW_HOME", "CREW_MEMORY", "CREW_RUNS", "CREW_SKILLS", "CREW_BIN",
    "CREW_CLI", "CREW_ROLE", "CREW_NODE", "CREW_TASK", "CREW_PARENT",
    "CREW_REPO_ID", "CREW_UNATTENDED_WORKERS",
    "CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SSE_PORT", "CLAUDE_PID",
    "CLAUDE_EFFORT", "CLAUDE_CODE_USE_VERTEX", "ANTHROPIC_BASE_URL",
    "CODEX_CI", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED",
    "CODEX_SESSION_ID", "CODEX_THREAD_ID", "CODEX_VERSION",
    "CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS", "OPENAI_BASE_URL",
)
record = {"args": sys.argv[1:], "cwd": os.getcwd(),
          "path": os.environ.get("PATH", ""),
          "env": {key: os.environ[key] for key in keys if key in os.environ}}
args = sys.argv[1:]
if "--append-system-prompt-file" in args:
    path = args[args.index("--append-system-prompt-file") + 1]
    record["instructions"] = pathlib.Path(path).read_text()
if "--settings" in args:
    value = args[args.index("--settings") + 1]
    record["settings"] = json.loads(value) if value.startswith("{") else value
pathlib.Path(os.environ["CAPTURE"]).write_text(json.dumps(record))
""",
        )
        self._write_program(
            "codex",
            f"#!{sys.executable}\n" + """import json, os, pathlib, sys
keys = (
    "CREW_HOME", "CREW_MEMORY", "CREW_RUNS", "CREW_SKILLS", "CREW_BIN",
    "CREW_CLI", "CREW_ROLE", "CREW_NODE", "CREW_TASK", "CREW_PARENT",
    "CREW_REPO_ID", "CREW_UNATTENDED_WORKERS",
    "CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SSE_PORT", "CLAUDE_PID",
    "CLAUDE_EFFORT", "CLAUDE_CODE_USE_VERTEX", "ANTHROPIC_BASE_URL",
    "CODEX_CI", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED",
    "CODEX_SESSION_ID", "CODEX_THREAD_ID", "CODEX_VERSION",
    "CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS", "OPENAI_BASE_URL",
)
args = sys.argv[1:]
record = {"args": args, "cwd": os.getcwd(),
          "path": os.environ.get("PATH", ""),
          "env": {key: os.environ[key] for key in keys if key in os.environ}}
if "--config" in args:
    value = args[args.index("--config") + 1]
    if value.startswith("developer_instructions="):
        record["instructions"] = json.loads(value.split("=", 1)[1])
pathlib.Path(os.environ["CAPTURE"]).write_text(json.dumps(record))
""",
        )
        self._write_program(
            "kitten",
            f"#!{sys.executable}\n" + """import json, os, pathlib, sys
if sys.argv[1:] == ["@", "ls"] and os.environ.get("FAIL_KITTEN") == "1":
    raise SystemExit(1)
pathlib.Path(os.environ["KITTY_CAPTURE"]).write_text(
    json.dumps({"args": sys.argv[1:]})
)
""",
        )
        self._write_program(
            "kitty",
            f"#!{sys.executable}\n" + """import json, os, pathlib, sys
pathlib.Path(os.environ["KITTY_CAPTURE"]).write_text(
    json.dumps({"args": sys.argv[1:], "cwd": os.getcwd()})
)
""",
        )
        self._git("init", "-q")

    def _write_program(self, name, contents):
        path = self.bin / name
        path.write_text(contents)
        path.chmod(0o755)

    def _git(self, *args):
        subprocess.run(
            ["git", *args],
            cwd=self.project,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _env(self, **extra):
        env = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "TMPDIR": str(self.tmp),
            "CREW_BIN": str(LAUNCHER),
            "CREW_CORE_INSTRUCTIONS": str(self.core),
            "CREW_SKILLS": str(self.skills),
            "CREW_PLUGIN": str(self.plugin),
            "CAPTURE": str(self.capture),
            "KITTY_CAPTURE": str(self.root / "kitty-capture.json"),
            "KITTY_LISTEN_ON": "unix:/tmp/fake-kitty.sock",
        }
        env.update(extra)
        for key in ("HYPRLAND_INSTANCE_SIGNATURE", "XDG_RUNTIME_DIR"):
            env.pop(key, None)
        return env

    def _run(self, *args, env=None, expected=0):
        result = subprocess.run(
            ["bash", str(LAUNCHER), *args],
            cwd=self.project,
            env=env or self._env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def _record(self):
        return json.loads(self.capture.read_text())

    def test_cli_arguments_and_exported_environment(self):
        self._git(
            "remote",
            "add",
            "origin",
            "git@GitHub.com:Acme/Widget.git",
        )
        self._run("claude", "--print", "keep this argument")
        record = self._record()
        self.assertEqual(
            record["args"][-2:],
            ["--print", "keep this argument"],
        )
        self.assertEqual(record["cwd"], str(self.project))
        self.assertEqual(record["env"]["CREW_CLI"], "claude")
        self.assertEqual(
            record["env"]["CREW_REPO_ID"],
            "github.com/acme/widget",
        )
        self.assertEqual(
            record["env"]["CREW_HOME"],
            str(self.home / ".local/share/crew"),
        )
        self.assertEqual(
            record["env"]["CREW_MEMORY"],
            str(self.home / ".local/share/crew/memory"),
        )
        self.assertEqual(
            record["env"]["CREW_RUNS"],
            str(self.home / ".local/share/crew/runs"),
        )
        self.assertEqual(record["env"]["CREW_SKILLS"], str(self.skills))
        self.assertEqual(record["env"]["CREW_BIN"], str(LAUNCHER))
        self.assertNotIn("CREW_ROLE", record["env"])

    def test_xdg_data_home_sets_crew_home(self):
        data_home = self.root / "custom-data"
        self._run("codex", env=self._env(XDG_DATA_HOME=str(data_home)))
        record = self._record()
        self.assertEqual(record["env"]["CREW_CLI"], "codex")
        self.assertEqual(
            record["env"]["CREW_HOME"],
            str(data_home / "crew"),
        )
        self.assertEqual(
            record["env"]["CREW_MEMORY"],
            str(data_home / "crew/memory"),
        )
        self.assertEqual(
            record["env"]["CREW_RUNS"],
            str(data_home / "crew/runs"),
        )
        self.assertTrue((data_home / "crew/memory").is_dir())
        self.assertTrue((data_home / "crew/runs").is_dir())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_initial_memory_indices_and_permissions(self):
        self._git(
            "remote",
            "add",
            "origin",
            "https://user:fixture@GitHub.com/Acme/Widget.git",
        )
        self._run("claude")
        memory = self.home / ".local/share/crew/memory"
        paths = {
            memory: "# Crew memory\n",
            memory / "global": None,
            memory / "machine": None,
            memory / "repos": None,
            memory / "repos/github.com_acme_widget": "# Repository memory\n",
            self.home / ".local/share/crew/runs": None,
        }
        for path, contents in paths.items():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700, path)
            if contents is not None:
                self.assertEqual(
                    (path / "index.md").read_text(),
                    contents,
                )
        self.assertEqual(
            (memory / "global/index.md").read_text(),
            "# Global memory\n",
        )
        self.assertEqual(
            (memory / "machine/index.md").read_text(),
            "# Machine memory\n",
        )
        self.assertEqual(
            (memory / "repos/index.md").read_text(),
            "# Repository memory\n",
        )

    def test_https_credentials_and_https_without_credentials(self):
        for url in (
            "https://user:fixture@example.com/Owner/Repo.git",
            "https://example.com/Owner/Repo.git",
        ):
            with self.subTest(url=url):
                if self._origin_exists():
                    self._git("remote", "remove", "origin")
                self._git("remote", "add", "origin", url)
                self.capture.unlink(missing_ok=True)
                self._run("claude")
                self.assertEqual(
                    self._record()["env"]["CREW_REPO_ID"],
                    "example.com/owner/repo",
                )

    def _origin_exists(self):
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=self.project,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0

    def test_originless_repository_uses_local_directory_id(self):
        self._run("codex", "exec", "--ephemeral", "preserve words")
        record = self._record()
        self.assertEqual(record["env"]["CREW_REPO_ID"], "local/test-project")
        self.assertEqual(
            record["args"][-3:],
            ["exec", "--ephemeral", "preserve words"],
        )

    def test_generated_instructions_and_claude_plugin_arguments(self):
        self._run("claude", "--print", "prompt")
        record = self._record()
        self.assertIn("CORE_MARKER", record["instructions"])
        self.assertIn("## This session", record["instructions"])
        helper = self.skills / "nodes/scripts/nodes.sh"
        self.assertIn(
            "  - " + str(self.skills / "nodes/SKILL.md"),
            record["instructions"],
        )
        self.assertIn("Nodes helper: crew-nodes", record["instructions"])
        self.assertNotIn(str(helper), record["instructions"])
        self.assertEqual(
            shutil.which("crew-nodes", path=record["path"]),
            str(REPO / "bin/crew-nodes"),
        )
        plugin_index = record["args"].index("--plugin-dir") + 1
        self.assertEqual(record["args"][plugin_index], str(self.plugin))
        self.assertEqual(list(self.tmp.glob("crew-instructions.*")), [])

    def test_human_claude_allows_only_nodes_helper(self):
        self._run("claude")
        settings = self._record()["settings"]
        self.assertEqual(
            settings,
            {"permissions": {"allow": ["Bash(crew-nodes *)"]}},
        )
        self.assertNotIn(
            "--dangerously-skip-permissions",
            self._record()["args"],
        )
        self.assertFalse((self.home / ".claude").exists())
        self.assertFalse((self.home / ".codex").exists())

    def test_claude_worker_permissions_default_and_unattended(self):
        env = self._env(
            CREW_ROLE="worker",
            CREW_NODE="worker-a",
            CREW_TASK="task-a",
            CREW_PARENT="9",
        )
        self._run("claude", "--print", env=env)
        record = self._record()
        self.assertIn("--settings", record["args"])
        self.assertEqual(
            self._record()["settings"],
            {"permissions": {"allow": ["Bash(crew-nodes *)"]}},
        )
        self.assertNotIn("--dangerously-skip-permissions", record["args"])
        self.assertEqual(record["env"]["CREW_NODE"], "worker-a")
        self.assertEqual(record["env"]["CREW_TASK"], "task-a")
        self.assertEqual(record["env"]["CREW_PARENT"], "9")
        self.assertIn("- Role: worker", record["instructions"])
        self.assertIn("- Node: worker-a", record["instructions"])
        self.assertIn("- Task: task-a", record["instructions"])
        self.assertIn("- Parent Kitty window: 9", record["instructions"])
        env = self._env(
            CREW_ROLE="worker",
            CREW_UNATTENDED_WORKERS="1",
        )
        self._run("claude", env=env)
        record = self._record()
        self.assertIn("--settings", record["args"])
        self.assertIn("--dangerously-skip-permissions", record["args"])

    def test_codex_human_worker_and_unattended_permissions(self):
        self._run("codex", "exec", "--ephemeral", "extra", env=self._env())
        record = self._record()
        self.assertIn("--sandbox", record["args"])
        sandbox_index = record["args"].index("--sandbox") + 1
        self.assertEqual(record["args"][sandbox_index], "danger-full-access")
        self.assertIn("CORE_MARKER", record["instructions"])
        self.assertEqual(
            record["args"][-3:],
            ["exec", "--ephemeral", "extra"],
        )

        self._run("codex", env=self._env(CREW_ROLE="worker"))
        worker_args = self._record()["args"]
        self.assertIn("--sandbox", worker_args)
        worker_sandbox = worker_args.index("--sandbox") + 1
        self.assertEqual(worker_args[worker_sandbox], "danger-full-access")
        self.assertNotIn(
            "--dangerously-bypass-approvals-and-sandbox",
            worker_args,
        )

        self._run(
            "codex",
            env=self._env(
                CREW_ROLE="worker",
                CREW_UNATTENDED_WORKERS="1",
            ),
        )
        unattended_args = self._record()["args"]
        self.assertIn("--sandbox", unattended_args)
        self.assertIn(
            "--dangerously-bypass-approvals-and-sandbox",
            unattended_args,
        )

    def test_launcher_writes_only_to_crew_home_and_temp_files(self):
        self._run("codex")
        crew_home = self.home / ".local/share/crew"
        self.assertTrue(crew_home.is_dir())
        self.assertEqual(
            {path.name for path in self.home.iterdir()},
            {".local"},
        )
        self.assertEqual(
            {path.name for path in (self.home / ".local").iterdir()},
            {"share"},
        )
        self.assertEqual(
            {path.name for path in (self.home / ".local/share").iterdir()},
            {"crew"},
        )
        self.assertFalse((self.home / ".agents").exists())
        self.assertFalse((self.home / ".claude").exists())
        self.assertFalse((self.home / ".codex").exists())
        self.assertEqual(list(self.tmp.glob("crew-instructions.*")), [])
        instructions = self._record()["instructions"]
        self.assertIn(
            "Read relevant skills from the listed SKILL.md paths",
            instructions,
        )
        for name in ("nodes", "memory", "onboard"):
            self.assertIn(str(self.skills / name / "SKILL.md"), instructions)

    def test_launcher_does_not_add_model_provider_or_credential_flags(self):
        for cli in ("claude", "codex"):
            with self.subTest(cli=cli):
                self._run(cli)
                args = self._record()["args"]
                forbidden = (
                    "--model",
                    "--provider",
                    "--api-key",
                    "--auth-token",
                )
                self.assertFalse(any(arg in forbidden for arg in args), args)

    def test_cli_session_markers_clear_without_losing_provider_config(self):
        claude_markers = (
            "CLAUDECODE",
            "CLAUDE_CODE_CHILD_SESSION",
            "CLAUDE_CODE_ENTRYPOINT",
            "CLAUDE_CODE_EXECPATH",
            "CLAUDE_CODE_MESSAGING_SOCKET",
            "CLAUDE_CODE_MESSAGING_TOKEN",
            "CLAUDE_CODE_SESSION_ATTENDED",
            "CLAUDE_CODE_SESSION_ID",
            "CLAUDE_CODE_SSE_PORT",
            "CLAUDE_PID",
        )
        claude_env = self._env(
            **{name: "fixture-marker" for name in claude_markers},
            CLAUDE_EFFORT="high",
            CLAUDE_CODE_USE_VERTEX="1",
            ANTHROPIC_BASE_URL="https://example.invalid",
        )
        self._run("claude", env=claude_env)
        claude_received = self._record()["env"]
        for name in claude_markers:
            self.assertNotIn(name, claude_received)
        self.assertEqual(claude_received["CLAUDE_EFFORT"], "high")
        self.assertEqual(claude_received["CLAUDE_CODE_USE_VERTEX"], "1")
        self.assertEqual(
            claude_received["ANTHROPIC_BASE_URL"],
            "https://example.invalid",
        )

        codex_markers = (
            "CODEX_CI",
            "CODEX_SANDBOX",
            "CODEX_SANDBOX_NETWORK_DISABLED",
            "CODEX_SESSION_ID",
            "CODEX_THREAD_ID",
        )
        codex_env = self._env(
            **{name: "fixture-marker" for name in codex_markers},
            CODEX_VERSION="parent-version",
            CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS="1",
            OPENAI_BASE_URL="https://example.invalid/v1",
        )
        self._run("codex", env=codex_env)
        codex_received = self._record()["env"]
        for name in codex_markers:
            self.assertNotIn(name, codex_received)
        self.assertEqual(codex_received["CODEX_VERSION"], "parent-version")
        self.assertEqual(
            codex_received["CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS"],
            "1",
        )
        self.assertEqual(
            codex_received["OPENAI_BASE_URL"],
            "https://example.invalid/v1",
        )

    def test_reopens_kitty_without_socket(self):
        env = self._env()
        env.pop("KITTY_LISTEN_ON")
        result = self._run("claude", "--print", env=env)
        self.assertEqual(result.stderr, "")
        record = json.loads((self.root / "kitty-capture.json").read_text())
        args = record["args"]
        self.assertEqual(args[0], "--detach")
        self.assertEqual(
            args[1:3],
            ["-o", "allow_remote_control=socket-only"],
        )
        listen = args[args.index("--listen-on") + 1]
        self.assertTrue(listen.startswith(f"unix:{self.tmp}/crew-"), listen)
        self.assertTrue(listen.endswith(".sock"), listen)
        self.assertNotIn("XDG_RUNTIME_DIR", listen)
        directory_index = args.index("--directory") + 1
        self.assertEqual(args[directory_index], str(self.project))
        command_index = args.index(str(LAUNCHER))
        self.assertEqual(
            args[command_index:],
            [str(LAUNCHER), "claude", "--print"],
        )
        self.assertFalse(self.capture.exists())

    def test_reopens_kitty_when_remote_listing_fails(self):
        env = self._env(FAIL_KITTEN="1")
        result = self._run("codex", "exec", env=env)
        self.assertEqual(result.returncode, 0)
        record = json.loads((self.root / "kitty-capture.json").read_text())
        self.assertIn(str(LAUNCHER), record["args"])
        self.assertEqual(record["args"][-2:], ["codex", "exec"])

    def test_invalid_cli_prints_help_and_exits_two(self):
        result = self._run("unknown", expected=2)
        self.assertIn(
            "Usage: crew claude [args] | crew codex [args]",
            result.stderr,
        )
        self.assertFalse((self.root / "kitty-capture.json").exists())


if __name__ == "__main__":
    unittest.main()

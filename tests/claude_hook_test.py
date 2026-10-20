"""Tests for Claude FileChanged delivery and explicit mailbox acknowledgement."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/nodes/scripts"
MAILBOX_SCRIPT = SCRIPTS / "mailbox.py"
HOOK_SCRIPT = SCRIPTS / "claude_hook.py"
SPEC = importlib.util.spec_from_file_location("crew_mailbox_for_claude", MAILBOX_SCRIPT)
mailbox = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mailbox)

SENDER = "11111111-1111-4111-8111-111111111111"
RECIPIENT = "22222222-2222-4222-8222-222222222222"


class ClaudeHookTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "crew"
        self.sender_inbox = mailbox.initialize_session(
            SENDER, cli="pi", node="sender", home=self.home,
        )
        self.inbox = mailbox.initialize_session(
            RECIPIENT, cli="claude", node="receiver", home=self.home,
        )
        self.env = os.environ.copy()
        self.env.update({
            "CREW_HOME": str(self.home),
            "CREW_SESSION_ID": RECIPIENT,
            "CREW_INBOX": str(self.inbox),
            "CREW_CLI": "claude",
            "PATH": str(ROOT / "bin") + os.pathsep + os.environ.get("PATH", ""),
        })

    def hook(self, event):
        return subprocess.run(
            [sys.executable, str(HOOK_SCRIPT)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )

    def publish(self, text):
        with mock.patch.dict(os.environ, {
            "CREW_HOME": str(self.home),
            "CREW_SESSION_ID": SENDER,
            "CREW_INBOX": str(self.sender_inbox),
            "CREW_CLI": "pi",
        }):
            return mailbox.publish_message(RECIPIENT, text, home=self.home)

    def test_session_start_registers_signal_watch_and_initial_context(self):
        message_id = self.publish("arrived before hook registration")
        result = self.hook({"hook_event_name": "SessionStart"})
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        hook_output = output["hookSpecificOutput"]
        self.assertEqual(hook_output["hookEventName"], "SessionStart")
        self.assertEqual(hook_output["watchPaths"], [str(self.inbox / "signal")])
        self.assertIn(message_id, hook_output["additionalContext"])
        self.assertTrue((self.inbox / "pending" / f"{message_id}.json").is_file())
        self.assertFalse((self.inbox / "received" / f"{message_id}.json").exists())

    def test_file_changed_never_acks_or_reinjects_before_ack(self):
        first = self.publish("first line\nsecond line")
        second = self.publish("next message")
        event = {
            "hook_event_name": "FileChanged",
            "file_path": str(self.inbox / "signal"),
            "event": "change",
        }
        result = self.hook(event)
        self.assertEqual(result.returncode, 2)
        self.assertIn(first, result.stderr)
        self.assertIn(SENDER, result.stderr)
        self.assertIn("first line\nsecond line", result.stderr)
        self.assertFalse((self.inbox / "received" / f"{first}.json").exists())

        repeated = self.hook(event)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertNotIn(first, repeated.stderr)
        self.assertNotIn(second, repeated.stderr)
        self.assertTrue((self.inbox / "pending" / f"{first}.json").exists())

        with mock.patch.dict(os.environ, self.env):
            self.assertTrue(mailbox.acknowledge(first, home=self.home))
        next_message = self.hook(event)
        self.assertEqual(next_message.returncode, 2)
        self.assertIn(second, next_message.stderr)
        self.assertNotIn(first, next_message.stderr)
        self.assertFalse((self.inbox / "received" / f"{second}.json").exists())

    def test_unrelated_file_change_does_not_claim_a_message(self):
        message_id = self.publish("wait for the mailbox signal")
        result = self.hook({
            "hook_event_name": "FileChanged",
            "file_path": str(self.root / "other-file"),
            "event": "change",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.inbox / "pending" / f"{message_id}.json").exists())
        self.assertFalse((self.inbox / ".delivery.json").exists())


if __name__ == "__main__":
    unittest.main()

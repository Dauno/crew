"""Tests for persistent session mailboxes and explicit acknowledgements."""

import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MAILBOX_SCRIPT = ROOT / "skills/nodes/scripts/mailbox.py"
SPEC = importlib.util.spec_from_file_location("crew_mailbox", MAILBOX_SCRIPT)
mailbox = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mailbox)

SENDER = "11111111-1111-4111-8111-111111111111"
RECIPIENT = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
PREALLOCATED = "44444444-4444-4444-8444-444444444444"


class MailboxTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "crew"
        self.sender = mailbox.initialize_session(
            SENDER, cli="pi", node="sender", task="test-task", home=self.home,
        )
        self.receiver = mailbox.initialize_session(
            RECIPIENT, cli="claude", node="receiver", task="test-task",
            home=self.home,
        )
        self.env = mock.patch.dict(os.environ, {
            "CREW_HOME": str(self.home),
            "CREW_SESSION_ID": SENDER,
            "CREW_INBOX": str(self.sender),
            "CREW_CLI": "pi",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def receiver_env(self, cli="claude", session_id=RECIPIENT):
        path = self.home / "mailboxes" / session_id
        return mock.patch.dict(os.environ, {
            "CREW_HOME": str(self.home),
            "CREW_SESSION_ID": session_id,
            "CREW_INBOX": str(path),
            "CREW_CLI": cli,
        })

    def publish(self, text):
        return mailbox.publish_message(RECIPIENT, text, home=self.home)

    def test_envelope_has_only_id_from_and_text(self):
        message_id = self.publish("first line\nsecond line")
        path = self.receiver / "pending" / f"{message_id}.json"
        message = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(message), {"id", "from", "text"})
        self.assertEqual(message, {
            "id": message_id,
            "from": SENDER,
            "text": "first line\nsecond line",
        })
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.receiver.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.home / "mailboxes").stat().st_mode), 0o700)

    def test_concurrent_senders_publish_distinct_atomic_files(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            message_ids = list(pool.map(
                lambda index: self.publish(f"message {index}"), range(32),
            ))
        self.assertEqual(len(set(message_ids)), 32)
        files = list((self.receiver / "pending").glob("*.json"))
        self.assertEqual(len(files), 32)
        messages = [json.loads(path.read_text(encoding="utf-8")) for path in files]
        self.assertEqual({message["id"] for message in messages}, set(message_ids))
        self.assertEqual({message["from"] for message in messages}, {SENDER})

    def test_empty_and_nul_messages_are_rejected(self):
        for text in ("", "bad\x00message"):
            with self.subTest(text=text):
                with self.assertRaises(mailbox.MailboxError):
                    self.publish(text)
        self.assertEqual(list((self.receiver / "pending").glob("*.json")), [])

    def test_payload_limit_counts_utf8_bytes_before_publication(self):
        exact_ascii = "a" * mailbox.MAX_MESSAGE_BYTES
        message_id = self.publish(exact_ascii)
        message = json.loads(
            (self.receiver / "pending" / f"{message_id}.json").read_text()
        )
        self.assertEqual(len(message["text"].encode("utf-8")), 8192)

        exact_unicode = "é" * (mailbox.MAX_MESSAGE_BYTES // 2)
        self.assertEqual(len(exact_unicode.encode("utf-8")), 8192)
        self.publish(exact_unicode)
        for too_large in ("a" * 8193, "é" * 4097):
            with self.subTest(bytes=len(too_large.encode("utf-8"))):
                with self.assertRaisesRegex(
                    mailbox.MailboxError, "8 KiB UTF-8 limit.*report file"
                ):
                    self.publish(too_large)
        self.assertEqual(
            len(list((self.receiver / "pending").glob("*.json"))), 2
        )

    def test_reserved_identity_is_consumed_once(self):
        reserved = mailbox.reserve_session(
            PREALLOCATED, cli="codex", node="worker", task="task-a",
            parent="7", started_at="123", home=self.home,
        )
        metadata_path = reserved / "session.json"
        self.assertTrue(json.loads(metadata_path.read_text())["preallocated"])
        with mock.patch.dict(os.environ, {
            "CREW_HOME": str(self.home),
            "CREW_SESSION_ID": PREALLOCATED,
            "CREW_INBOX": str(reserved),
        }):
            mailbox.consume_reservation(
                PREALLOCATED, cli="codex", node="worker", task="task-a",
                parent="7", window_id="12", started_at="123", native=True,
                home=self.home,
            )
            metadata = json.loads(metadata_path.read_text())
            self.assertFalse(metadata["preallocated"])
            self.assertEqual(metadata["window_id"], "12")
            self.assertTrue(metadata["native"])
            with self.assertRaisesRegex(mailbox.MailboxError, "not preallocated"):
                mailbox.consume_reservation(
                    PREALLOCATED, cli="codex", home=self.home,
                )

    def test_only_one_message_is_dispatched_until_explicit_ack(self):
        first = self.publish("message one")
        second = self.publish("message two")
        before_signal = (self.receiver / "signal").read_text()
        with self.receiver_env():
            claimed = mailbox.claim_next(home=self.home)
            self.assertEqual(claimed["id"], first)
            self.assertIsNone(mailbox.claim_next(home=self.home))
            with self.assertRaisesRegex(mailbox.MailboxError, "another message"):
                mailbox.acknowledge(second, home=self.home)
            self.assertEqual(list((self.receiver / "pending").glob("*.json")), [
                self.receiver / "pending" / f"{first}.json",
                self.receiver / "pending" / f"{second}.json",
            ])
            self.assertTrue(mailbox.acknowledge(first, home=self.home))
            self.assertFalse(mailbox.acknowledge(first, home=self.home))
            self.assertFalse((self.receiver / ".delivery.json").exists())
            self.assertNotEqual((self.receiver / "signal").read_text(), before_signal)
            next_message = mailbox.claim_next(home=self.home)
            self.assertEqual(next_message["id"], second)
            self.assertTrue(mailbox.acknowledge(second, home=self.home))
        self.assertTrue((self.receiver / "received" / f"{first}.json").is_file())
        self.assertTrue((self.receiver / "received" / f"{second}.json").is_file())
        self.assertEqual(list((self.receiver / "pending").glob("*.json")), [])

    def test_delivery_status_is_read_only_and_reports_age(self):
        message_id = self.publish("held for status")
        with self.receiver_env():
            claimed = mailbox.claim_next(home=self.home)
            self.assertEqual(claimed["id"], message_id)
            marker = self.receiver / ".delivery.json"
            os.utime(marker, (time.time() - 80, time.time() - 80))
            before = marker.read_bytes()
            status = mailbox.delivery_status(RECIPIENT, home=self.home)
            self.assertEqual(status["id"], message_id)
            self.assertGreaterEqual(status["age_seconds"], 79)
            self.assertEqual(marker.read_bytes(), before)
            pending = self.receiver / "pending" / f"{message_id}.json"
            received = self.receiver / "received" / f"{message_id}.json"
            self.assertTrue(pending.is_file())
            self.assertFalse(received.exists())
            self.assertIsNone(mailbox.delivery_status(OTHER, home=self.home))
            self.assertFalse((self.home / "mailboxes" / OTHER).exists())
            self.assertTrue(mailbox.acknowledge(message_id, home=self.home))
            self.assertIsNone(
                mailbox.delivery_status(RECIPIENT, home=self.home)
            )

    def test_repeated_claim_after_crash_does_not_reinject(self):
        message_id = self.publish("do not duplicate")
        with self.receiver_env():
            self.assertEqual(mailbox.claim_next(home=self.home)["id"], message_id)
            # A new adapter process sees the same durable dispatch marker.
            self.assertIsNone(mailbox.claim_next(home=self.home))
            self.assertTrue(mailbox.acknowledge(message_id, home=self.home))
            self.assertFalse((self.receiver / ".delivery.json").exists())

    def test_wrong_session_cannot_acknowledge(self):
        message_id = self.publish("private to receiver")
        with self.receiver_env(session_id=SENDER):
            with self.assertRaisesRegex(mailbox.MailboxError, "not pending"):
                mailbox.acknowledge(message_id, home=self.home)
        with self.receiver_env():
            self.assertEqual(mailbox.claim_next(home=self.home)["id"], message_id)
            self.assertTrue(mailbox.acknowledge(message_id, home=self.home))

    def test_acknowledgement_requires_the_dispatched_message(self):
        first = self.publish("first")
        second = self.publish("second")
        with self.receiver_env():
            with self.assertRaisesRegex(mailbox.MailboxError, "not delivered"):
                mailbox.acknowledge(first, home=self.home)
            mailbox.claim_next(home=self.home)
            with self.assertRaisesRegex(mailbox.MailboxError, "another message"):
                mailbox.acknowledge(second, home=self.home)

    def test_acknowledgement_of_unknown_message_fails(self):
        with self.receiver_env():
            with self.assertRaisesRegex(mailbox.MailboxError, "not pending"):
                mailbox.acknowledge(OTHER, home=self.home)

    def test_codex_stale_route_is_persisted_in_private_metadata(self):
        socket_path = str(self.root / "codex.sock")
        with mock.patch.dict(os.environ, {
            "CREW_HOME": str(self.home),
            "CREW_SESSION_ID": RECIPIENT,
            "CREW_INBOX": str(self.receiver),
        }):
            mailbox.set_codex_state(
                socket_path=socket_path, thread_id="thread-id", stale=False,
                home=self.home,
            )
            state = mailbox.codex_state(home=self.home, session_id=RECIPIENT)
            self.assertEqual(state["socket_path"], socket_path)
            self.assertFalse(state["stale"])
            mailbox.set_codex_state(
                socket_path=socket_path, thread_id="thread-id", stale=True,
                reason="thread changed", home=self.home,
            )
            self.assertTrue(mailbox.codex_state(
                home=self.home, session_id=RECIPIENT
            )["stale"])

    def test_invalid_session_and_inbox_mismatch_fail_closed(self):
        with self.assertRaisesRegex(mailbox.MailboxError, "lowercase UUID"):
            mailbox.publish_message("../escape", "message", home=self.home)
        with mock.patch.dict(os.environ, {"CREW_INBOX": str(self.root / "wrong")}):
            with self.assertRaisesRegex(mailbox.MailboxError, "does not match"):
                mailbox.publish_message(RECIPIENT, "message", home=self.home)


if __name__ == "__main__":
    unittest.main()

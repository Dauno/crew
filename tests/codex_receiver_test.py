"""Fake app-server tests for Codex ownership and delivery bookkeeping."""

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/nodes/scripts"
MAILBOX_SCRIPT = SCRIPTS / "mailbox.py"
RECEIVER_SCRIPT = SCRIPTS / "codex_receiver.py"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


mailbox = load_module("crew_mailbox_for_codex", MAILBOX_SCRIPT)
original_mailbox = sys.modules.get("mailbox")
sys.modules["mailbox"] = mailbox
codex_receiver = load_module("crew_codex_receiver", RECEIVER_SCRIPT)
if original_mailbox is None:
    del sys.modules["mailbox"]
else:
    sys.modules["mailbox"] = original_mailbox

SENDER = "11111111-1111-4111-8111-111111111111"
RECIPIENT = "22222222-2222-4222-8222-222222222222"
ROOT_THREAD = "01a15a98-8e29-7c91-9210-32f374b09b16"
NEW_THREAD = "01a15a98-9bd3-7fc3-be87-295e00d6b7af"


class FakeProxy:
    def __init__(self, loaded_roots=None):
        self.events = queue.Queue()
        self.requests = []
        self.loaded_roots = loaded_roots or [ROOT_THREAD]

    def pump_events(self):
        return None

    def request(self, method, params, timeout=5):
        self.requests.append((method, params))
        if method == "thread/loaded/list":
            return {"data": self.loaded_roots}
        if method == "thread/read":
            return {"thread": {
                "id": params["threadId"],
                "parentThreadId": None,
                "cwd": "/tmp/project",
            }}
        raise AssertionError(f"unexpected request: {method}")


class CodexReceiverTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "crew"
        self.inbox = mailbox.initialize_session(
            RECIPIENT, cli="codex", node="receiver", home=self.home,
        )
        self.sender = mailbox.initialize_session(
            SENDER, cli="pi", node="sender", home=self.home,
        )
        self.env = os.environ.copy()
        self.env.update({
            "CREW_HOME": str(self.home),
            "CREW_SESSION_ID": RECIPIENT,
            "CREW_INBOX": str(self.inbox),
            "CREW_CLI": "codex",
        })

    def receiver(self, thread_id=ROOT_THREAD, stale=False, loaded_roots=None):
        result = codex_receiver.CodexReceiver.__new__(codex_receiver.CodexReceiver)
        result.socket_path = str(self.root / "app.sock")
        result.session_id = RECIPIENT
        result.thread_id = thread_id
        result.stale = stale
        result.proxy = FakeProxy(loaded_roots)
        return result

    def publish(self, text):
        with mock.patch.dict(os.environ, {
            "CREW_HOME": str(self.home),
            "CREW_SESSION_ID": SENDER,
            "CREW_INBOX": str(self.sender),
            "CREW_CLI": "pi",
        }):
            return mailbox.publish_message(RECIPIENT, text, home=self.home)

    def test_proxy_uses_unix_websocket_transport(self):
        socket_path = self.root / "app.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(socket_path))
        server.listen(1)
        server.settimeout(5)
        requests = []
        masked_frames = []
        server_errors = []

        def read_exact(connection, count):
            chunks = bytearray()
            while len(chunks) < count:
                chunk = connection.recv(count - len(chunks))
                if not chunk:
                    raise OSError("client disconnected")
                chunks.extend(chunk)
            return bytes(chunks)

        def read_client_frame(connection):
            first, second = read_exact(connection, 2)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", read_exact(connection, 2))[0]
            elif length == 127:
                length = struct.unpack("!Q", read_exact(connection, 8))[0]
            masked_frames.append(bool(second & 0x80))
            mask = read_exact(connection, 4)
            payload = read_exact(connection, length)
            return first & 0x0F, bytes(
                value ^ mask[index % 4] for index, value in enumerate(payload)
            )

        def send_frame(connection, value):
            payload = json.dumps(value, separators=(",", ":")).encode()
            if len(payload) < 126:
                header = bytes([0x81, len(payload)])
            else:
                header = bytes([0x81, 126]) + struct.pack("!H", len(payload))
            connection.sendall(header + payload)

        def serve():
            try:
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(5)
                    request = bytearray()
                    while not request.endswith(b"\r\n\r\n"):
                        request.extend(connection.recv(1))
                    headers = request.decode().split("\r\n")
                    key = next(
                        line.split(":", 1)[1].strip()
                        for line in headers if line.lower().startswith(
                            "sec-websocket-key:"
                        )
                    )
                    accept = base64.b64encode(hashlib.sha1(
                        (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                    ).digest()).decode()
                    connection.sendall(
                        "HTTP/1.1 101 Switching Protocols\r\n"
                        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Accept: {accept}\r\n\r\n".encode()
                    )
                    while True:
                        opcode, payload = read_client_frame(connection)
                        if opcode == 8:
                            return
                        message = json.loads(payload)
                        requests.append(message)
                        if "id" in message:
                            result = (
                                {"codexHome": "/private/test-home"}
                                if message["method"] == "initialize"
                                else {"data": []}
                            )
                            send_frame(connection, {
                                "id": message["id"], "result": result,
                            })
            except OSError:
                return
            except StopIteration as error:
                server_errors.append(error)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            proxy = codex_receiver.AppServerProxy(str(socket_path))
            try:
                self.assertEqual(proxy.codex_home, "/private/test-home")
                result = proxy.request("thread/loaded/list", {"limit": 5})
                self.assertEqual(result, {"data": []})
            finally:
                proxy.close()
        finally:
            server.close()
            thread.join(timeout=2)
        self.assertEqual(server_errors, [])
        self.assertEqual(
            [message["method"] for message in requests],
            ["initialize", "initialized", "thread/loaded/list"],
        )
        self.assertTrue(masked_frames)
        self.assertTrue(all(masked_frames))

    def test_loaded_root_is_selected_and_second_root_fails_closed(self):
        with mock.patch.dict(os.environ, self.env):
            receiver = self.receiver(thread_id=None)
            receiver.discover_root()
            self.assertEqual(receiver.thread_id, ROOT_THREAD)
            receiver.proxy.events.put({
                "method": "thread/started",
                "params": {"thread": {
                    "id": NEW_THREAD,
                    "parentThreadId": None,
                    "cwd": "/tmp/project",
                }},
            })
            receiver.process_events()
            self.assertTrue(receiver.stale)
            state = mailbox.codex_state(home=self.home, session_id=RECIPIENT)
            self.assertTrue(state["stale"])
            self.assertEqual(state["thread_id"], ROOT_THREAD)

    def test_child_thread_does_not_invalidate_root_route(self):
        with mock.patch.dict(os.environ, self.env):
            receiver = self.receiver()
            receiver.proxy.events.put({
                "method": "thread/started",
                "params": {"thread": {
                    "id": NEW_THREAD,
                    "parentThreadId": ROOT_THREAD,
                }},
            })
            receiver.process_events()
            self.assertFalse(receiver.stale)
            self.assertEqual(receiver.thread_id, ROOT_THREAD)

    def test_queue_waits_for_ack_and_progresses_one_message_at_a_time(self):
        first = self.publish("first message")
        second = self.publish("second message")
        receiver = self.receiver()
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0)

        with mock.patch.dict(os.environ, self.env), mock.patch.object(
            codex_receiver.subprocess, "run", side_effect=fake_run,
        ):
            receiver.dispatch_one()
            self.assertEqual(len(calls), 1)
            args = calls[0][0]
            self.assertIn("--remote", args)
            self.assertEqual(args[args.index("--thread") + 1], ROOT_THREAD)
            self.assertIn(first, args[args.index("--message") + 1])
            receiver.dispatch_one()
            self.assertEqual(len(calls), 1)

            self.assertTrue(mailbox.acknowledge(first, home=self.home))
            receiver.dispatch_one()
            self.assertEqual(len(calls), 2)
            self.assertIn(second, calls[1][0][calls[1][0].index("--message") + 1])

    def test_failed_queue_is_not_retried_before_explicit_ack(self):
        message_id = self.publish("possibly accepted")
        receiver = self.receiver()
        calls = []

        def failed_run(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 1)

        with mock.patch.dict(os.environ, self.env), mock.patch.object(
            codex_receiver.subprocess, "run", side_effect=failed_run,
        ):
            receiver.dispatch_one()
            receiver.dispatch_one()
        self.assertEqual(len(calls), 1)
        self.assertTrue((self.inbox / "pending" / f"{message_id}.json").exists())
        self.assertTrue((self.inbox / ".delivery.json").exists())

    def test_loaded_root_mismatch_fails_closed_before_queue(self):
        message_id = self.publish("thread may have switched")
        receiver = self.receiver(thread_id=NEW_THREAD, loaded_roots=[ROOT_THREAD])
        with mock.patch.dict(os.environ, self.env), mock.patch.object(
            codex_receiver.subprocess, "run",
        ) as run:
            receiver.dispatch_one()
        run.assert_not_called()
        self.assertTrue(receiver.stale)
        self.assertTrue((self.inbox / "pending" / f"{message_id}.json").exists())

    def test_stale_root_never_queues_pending_message(self):
        message_id = self.publish("stale destination")
        receiver = self.receiver(stale=True)
        with mock.patch.dict(os.environ, self.env), mock.patch.object(
            codex_receiver.subprocess, "run",
        ) as run:
            receiver.dispatch_one()
        run.assert_not_called()
        self.assertTrue((self.inbox / "pending" / f"{message_id}.json").exists())


if __name__ == "__main__":
    unittest.main()

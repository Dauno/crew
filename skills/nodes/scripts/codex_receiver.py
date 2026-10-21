#!/usr/bin/env python3
"""Read one Codex session mailbox and queue to its owning app-server thread."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import queue
import secrets
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

from mailbox import MailboxError, claim_next, format_for_agent, set_codex_state


class ReceiverError(Exception):
    pass


class AppServerProxy:
    """Speak Codex's Unix WebSocket app-server protocol directly."""

    def __init__(self, socket_path: str):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(5)
        try:
            self.socket.connect(socket_path)
            self._websocket_upgrade()
        except OSError as error:
            self.socket.close()
            raise ReceiverError("could not connect to Codex app-server") from error
        except Exception:
            self.socket.close()
            raise
        self.socket.settimeout(None)
        self.messages: queue.Queue[dict | None] = queue.Queue()
        self.events: queue.Queue[dict] = queue.Queue()
        self.next_id = 1
        self.write_lock = threading.Lock()
        self.closed = False
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()
        try:
            result = self.request("initialize", {
                "clientInfo": {
                    "name": "crew-mailbox",
                    "title": "crew mailbox receiver",
                    "version": "1.0.0",
                },
                "capabilities": {"experimentalApi": True},
            })
            self.codex_home = result.get("codexHome")
            self.notify("initialized", {})
        except Exception:
            self.close()
            raise

    def _read_exact(self, count: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < count:
            chunk = self.socket.recv(count - len(chunks))
            if not chunk:
                raise OSError("Codex WebSocket closed")
            chunks.extend(chunk)
        return bytes(chunks)

    def _websocket_upgrade(self) -> None:
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            "GET / HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.socket.sendall(request.encode("ascii"))
        response = bytearray()
        while not response.endswith(b"\r\n\r\n"):
            chunk = self.socket.recv(1)
            if not chunk:
                raise ReceiverError("Codex closed its socket during WebSocket upgrade")
            response.extend(chunk)
            if len(response) > 8192:
                raise ReceiverError("oversized Codex WebSocket handshake")
        headers = response.decode("ascii", errors="replace").split("\r\n")
        status = headers[0].split()
        if len(status) < 2 or status[1] != "101":
            raise ReceiverError("Codex rejected WebSocket upgrade")
        received = {
            name.strip().lower(): value.strip()
            for line in headers[1:]
            if ":" in line
            for name, value in [line.split(":", 1)]
        }
        expected = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
        ).digest()).decode("ascii")
        if received.get("sec-websocket-accept") != expected:
            raise ReceiverError("Codex WebSocket handshake did not validate")

    def _send_frame(self, payload: bytes, opcode: int = 1) -> None:
        length = len(payload)
        header = bytes([0x80 | opcode])
        if length < 126:
            header += bytes([0x80 | length])
        elif length < 65536:
            header += bytes([0x80 | 126]) + struct.pack("!H", length)
        else:
            header += bytes([0x80 | 127]) + struct.pack("!Q", length)
        mask = secrets.token_bytes(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        with self.write_lock:
            self.socket.sendall(header + mask + masked)

    def _read_frame(self) -> tuple[bool, int, bytes]:
        first, second = self._read_exact(2)
        final = bool(first & 0x80)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        mask = self._read_exact(4) if second & 0x80 else None
        payload = self._read_exact(length) if length else b""
        if mask:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        return final, opcode, payload

    def _read_loop(self) -> None:
        fragments = bytearray()
        fragment_opcode: int | None = None
        try:
            while not self.closed:
                final, opcode, payload = self._read_frame()
                if opcode == 8:
                    break
                if opcode == 9:
                    self._send_frame(payload, opcode=10)
                    continue
                if opcode == 10:
                    continue
                if opcode in (1, 2):
                    fragments = bytearray(payload)
                    fragment_opcode = opcode
                elif opcode == 0 and fragment_opcode is not None:
                    fragments.extend(payload)
                else:
                    continue
                if not final:
                    continue
                try:
                    message = json.loads(fragments.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if isinstance(message, dict):
                    self.messages.put(message)
                fragments = bytearray()
                fragment_opcode = None
        except OSError:
            pass
        finally:
            self.messages.put(None)

    def _write(self, message: dict) -> None:
        if self.closed:
            raise ReceiverError("Codex app-server connection is closed")
        try:
            payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
            self._send_frame(payload)
        except OSError as error:
            raise ReceiverError("Codex app-server connection is unavailable") from error

    def notify(self, method: str, params: dict) -> None:
        self._write({"method": method, "params": params})

    def pump_events(self) -> None:
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                return
            if message is None:
                raise ReceiverError("Codex app-server connection closed")
            if isinstance(message.get("method"), str):
                self.events.put(message)

    def request(self, method: str, params: dict, timeout: float = 5) -> dict:
        request_id = self.next_id
        self.next_id += 1
        self._write({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                response = self.messages.get(timeout=min(0.2, deadline - time.monotonic()))
            except queue.Empty:
                continue
            if response is None:
                raise ReceiverError("Codex app-server connection closed")
            if response.get("id") == request_id and "method" not in response:
                if "error" in response:
                    raise ReceiverError(f"Codex {method} request failed")
                result = response.get("result")
                if not isinstance(result, dict):
                    raise ReceiverError(f"Codex {method} returned invalid data")
                return result
            if isinstance(response.get("method"), str):
                self.events.put(response)
        raise ReceiverError(f"Codex {method} request timed out")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()
        self.reader.join(timeout=2)


class CodexReceiver:
    def __init__(self, socket_path: str):
        self.socket_path = str(Path(socket_path).absolute())
        self.thread_id: str | None = None
        self.stale = False
        self.logged_ignored_thread_ids: set[str] = set()
        self.root_thread_metadata: dict[str, dict] = {}
        self.proxy = AppServerProxy(self.socket_path)
        try:
            self.write_state("")
        except Exception:
            self.proxy.close()
            raise

    def write_state(self, reason: str) -> None:
        set_codex_state(
            socket_path=self.socket_path,
            thread_id=self.thread_id,
            stale=self.stale,
            reason=reason,
        )

    def log(self, text: str) -> None:
        inbox = Path(os.environ["CREW_INBOX"])
        path = inbox / "codex-receiver.log"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, (text + "\n").encode())
        finally:
            os.close(descriptor)

    @staticmethod
    def is_root_candidate(thread: dict) -> bool:
        source = thread.get("source")
        is_subagent = isinstance(source, dict) and "subAgent" in source
        return (
            thread.get("parentThreadId") is None
            and not is_subagent
            and thread.get("ephemeral") is not True
        )

    @staticmethod
    def safe_source(source: object) -> str | None:
        if source is None:
            return None
        if isinstance(source, str):
            if source in {"cli", "vscode", "exec", "appServer", "unknown"}:
                return source
            return "unknown"
        if not isinstance(source, dict):
            return "unknown"
        if "subAgent" in source:
            subagent = source["subAgent"]
            known = {"review", "compact", "memory_consolidation"}
            if isinstance(subagent, str) and subagent in known:
                return f"subAgent:{subagent}"
            if isinstance(subagent, dict):
                for variant in (
                    "review", "compact", "memory_consolidation",
                    "thread_spawn", "other",
                ):
                    if variant in subagent:
                        return f"subAgent:{variant}"
            return "subAgent:unknown"
        if "custom" in source:
            return "custom"
        return "unknown"

    @staticmethod
    def safe_thread_id(value: object) -> str | None:
        if value is None:
            return None
        if (
            isinstance(value, str)
            and 0 < len(value) <= 128
            and value.isascii()
            and all(
                character.isalnum() or character in "-_" for character in value
            )
        ):
            return value
        return "present"

    @classmethod
    def thread_metadata(cls, thread: dict, thread_id: str | None = None) -> dict:
        metadata = {
            "id": thread.get("id"),
            "source": cls.safe_source(thread.get("source")),
            "ephemeral": thread.get("ephemeral"),
            "threadSource": "threadSource" in thread,
            "forkedFromId": thread.get("forkedFromId"),
            "parentThreadId": thread.get("parentThreadId"),
        }
        if metadata["id"] is None and thread_id is not None:
            metadata["id"] = thread_id
        for field in ("id", "forkedFromId", "parentThreadId"):
            metadata[field] = cls.safe_thread_id(metadata[field])
        ephemeral = metadata["ephemeral"]
        if ephemeral is not None and not isinstance(ephemeral, bool):
            metadata["ephemeral"] = "present"
        return metadata

    def log_thread(
        self, action: str, thread: dict, thread_id: str | None = None,
    ) -> None:
        metadata = self.thread_metadata(thread, thread_id)
        encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        self.log(f"{action}: {encoded}")

    def log_ignored_thread(self, thread: dict, thread_id: str) -> None:
        logged = getattr(self, "logged_ignored_thread_ids", set())
        if thread_id in logged:
            return
        logged.add(thread_id)
        self.logged_ignored_thread_ids = logged
        self.log_thread("ignored non-root thread", thread, thread_id)

    def log_root_threads(self, thread_ids: list[str], action: str) -> None:
        metadata_by_id = getattr(self, "root_thread_metadata", {})
        for thread_id in thread_ids:
            thread = metadata_by_id.get(thread_id, {"id": thread_id})
            self.log_thread(action, thread, thread_id)

    def read_thread(self, thread_id: str, thread: dict | None = None) -> dict:
        response = self.proxy.request("thread/read", {
            "threadId": thread_id,
            "includeTurns": False,
        })
        fetched = response.get("thread", {})
        if not isinstance(fetched, dict):
            raise ReceiverError("Codex thread metadata is invalid")
        fetched_id = fetched.get("id")
        if fetched_id is not None and fetched_id != thread_id:
            raise ReceiverError("Codex thread metadata has a mismatched ID")
        combined = dict(thread or {})
        combined.update(fetched)
        combined["id"] = thread_id
        return combined

    def root_ids(self) -> list[str]:
        response = self.proxy.request("thread/loaded/list", {"limit": 50})
        ids = response.get("data", [])
        if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
            raise ReceiverError("Codex loaded thread list is invalid")
        roots: list[str] = []
        for thread_id in ids:
            thread = self.read_thread(thread_id)
            if self.is_root_candidate(thread):
                roots.append(thread_id)
                metadata_by_id = getattr(self, "root_thread_metadata", {})
                metadata_by_id[thread_id] = thread
                self.root_thread_metadata = metadata_by_id
            else:
                self.log_ignored_thread(thread, thread_id)
        return roots

    def set_root(self, thread_id: str, thread: dict | None = None) -> None:
        if thread is not None:
            metadata_by_id = getattr(self, "root_thread_metadata", {})
            metadata_by_id[thread_id] = thread
            self.root_thread_metadata = metadata_by_id
        if self.thread_id is None:
            self.thread_id = thread_id
            self.write_state("")
        elif self.thread_id != thread_id:
            self.invalidate("Codex root conversation changed")

    def invalidate(self, reason: str) -> None:
        if self.stale:
            return
        self.stale = True
        self.write_state(reason)
        self.log("native messaging disabled: " + reason)

    def handle_event(self, event: dict) -> None:
        if event.get("method") != "thread/started":
            return
        params = event.get("params", {})
        thread = params.get("thread", {}) if isinstance(params, dict) else {}
        if not isinstance(thread, dict):
            return
        thread_id = thread.get("id")
        if "source" not in thread or "ephemeral" not in thread:
            if isinstance(thread_id, str):
                thread = self.read_thread(thread_id, thread)
            elif thread.get("parentThreadId") is None:
                self.log_thread("thread caused root invalidation", thread)
                self.invalidate("Codex started a root thread without an ID")
                return
        if not self.is_root_candidate(thread):
            if isinstance(thread_id, str):
                self.log_ignored_thread(thread, thread_id)
            else:
                self.log_thread("ignored non-root thread", thread)
            return
        if not isinstance(thread_id, str):
            self.log_thread("thread caused root invalidation", thread)
            self.invalidate("Codex started a root thread without an ID")
            return
        if (
            self.thread_id is not None
            and self.thread_id != thread_id
            and not self.stale
        ):
            self.log_thread("thread caused root invalidation", thread, thread_id)
        self.set_root(thread_id, thread)

    def process_events(self) -> None:
        self.proxy.pump_events()
        while True:
            try:
                event = self.proxy.events.get_nowait()
            except queue.Empty:
                return
            self.handle_event(event)

    def discover_root(self) -> None:
        if self.thread_id is not None or self.stale:
            return
        roots = self.root_ids()
        if len(roots) == 1:
            self.set_root(roots[0])
        elif len(roots) > 1:
            self.log_root_threads(roots, "multiple loaded root thread")
            self.invalidate("Codex has multiple loaded root conversations")

    def dispatch_one(self) -> None:
        if self.stale or self.thread_id is None:
            return
        self.process_events()
        if self.stale:
            return
        message = claim_next()
        if message is None:
            return
        self.process_events()
        roots = self.root_ids()
        if self.stale or roots != [self.thread_id]:
            if not self.stale:
                offending_roots = [
                    thread_id for thread_id in roots
                    if thread_id != self.thread_id
                ]
                if not offending_roots:
                    offending_roots = [self.thread_id]
                self.log_root_threads(
                    offending_roots, "root changed before queued delivery",
                )
                self.invalidate("Codex root changed before queued delivery")
            return
        endpoint = "unix://" + self.socket_path
        try:
            result = subprocess.run(
                [
                    "codex", "queue", "--remote", endpoint,
                    "--thread", self.thread_id,
                    "--message", format_for_agent(message),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            self.log("Codex queue timed out; message remains held pending explicit ack")
            self.invalidate("Codex queue result is uncertain")
            return
        except OSError:
            self.log("Codex queue could not start; message remains held")
            self.invalidate("Codex queue result is uncertain")
            return
        if result.returncode != 0:
            # Keep the dispatch marker. The queue response could have been lost
            # after acceptance, so automatic retry could inject the same ID twice.
            self.log("Codex queue failed; message remains held pending explicit ack")
            self.invalidate("Codex queue result is uncertain")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    args = parser.parse_args()
    stopping = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda _signum, _frame: stopping.set())
    receiver: CodexReceiver | None = None
    try:
        receiver = CodexReceiver(args.socket)
        ready = Path(os.environ["CREW_INBOX"]) / ".codex-receiver-ready"
        ready.write_text("ready\n", encoding="ascii")
        os.chmod(ready, 0o600)
        receiver.log("Codex mailbox receiver started")
        while not stopping.is_set():
            if receiver.stale:
                time.sleep(0.2)
                continue
            try:
                receiver.process_events()
                now = time.monotonic()
                if receiver.thread_id is None and now >= getattr(receiver, "next_discovery", 0):
                    receiver.discover_root()
                    receiver.next_discovery = now + 0.5
                receiver.dispatch_one()
            except ReceiverError:
                receiver.invalidate("Codex app-server route became unavailable")
            time.sleep(0.2)
        return 0
    except (MailboxError, ReceiverError, OSError) as error:
        print(f"crew Codex receiver: {error}", file=sys.stderr)
        return 1
    finally:
        if receiver is not None:
            receiver.proxy.close()


if __name__ == "__main__":
    raise SystemExit(main())

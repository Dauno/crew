#!/usr/bin/env python3
"""Private per-session message mailboxes for crew nodes."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import uuid
from typing import Iterator

SESSION_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
MAX_MESSAGE_BYTES = 8 * 1024


class MailboxError(Exception):
    """A mailbox operation failed without changing another session."""


def _die(message: str) -> None:
    print(f"crew mailbox: {message}", file=sys.stderr)
    raise SystemExit(1)


def _home() -> Path:
    value = os.environ.get("CREW_HOME")
    if not value:
        value = str(Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "crew")
    return Path(value).absolute()


def _session_id(value: str, name: str = "session ID") -> str:
    if not SESSION_RE.fullmatch(value):
        raise MailboxError(f"{name} must be a lowercase UUID")
    return value


def _mailboxes_root(home: Path) -> Path:
    return home / "mailboxes"


def _safe_mkdir(path: Path) -> None:
    if path.is_symlink():
        raise MailboxError(f"refusing symlinked mailbox directory: {path.name}")
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as error:
        raise MailboxError(f"could not create mailbox directory: {error}") from error
    if not path.is_dir():
        raise MailboxError(f"mailbox path is not a directory: {path.name}")
    os.chmod(path, 0o700)


def session_path(home: Path, session_id: str, *, create: bool = False) -> Path:
    session_id = _session_id(session_id)
    root = _mailboxes_root(home)
    if create:
        if home.is_symlink():
            if not home.is_dir():
                raise MailboxError("CREW_HOME symlink is not a directory")
            os.chmod(home, 0o700)
        else:
            _safe_mkdir(home)
        _safe_mkdir(root)
    if root.is_symlink():
        raise MailboxError("refusing symlinked mailboxes directory")
    path = root / session_id
    if create:
        _safe_mkdir(path)
        _safe_mkdir(path / "pending")
        _safe_mkdir(path / "received")
    elif path.is_symlink():
        raise MailboxError("refusing symlinked session mailbox")
    return path


def current_session() -> tuple[str, Path, Path]:
    home = _home()
    session_id = _session_id(os.environ.get("CREW_SESSION_ID", ""))
    path = session_path(home, session_id, create=True)
    configured = os.environ.get("CREW_INBOX")
    if configured and Path(configured).absolute() != path.absolute():
        raise MailboxError("CREW_INBOX does not match CREW_SESSION_ID")
    return session_id, path, home


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    opened = True
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
            opened = False
            json.dump(value, output, ensure_ascii=False, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        if opened:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
    lock_path = path / ".lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "r+b", buffering=0) as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def initialize_session(
    session_id: str,
    *,
    cli: str,
    node: str = "",
    task: str = "",
    parent: str = "",
    window_id: str = "",
    started_at: str = "",
    native: bool = False,
    home: Path | None = None,
) -> Path:
    session_id = _session_id(session_id)
    home = home or _home()
    path = session_path(home, session_id, create=True)
    metadata_path = path / "session.json"
    metadata = {
        "session_id": session_id,
        "cli": cli,
        "node": node,
        "task": task,
        "parent": parent,
        "window_id": window_id,
        "started_at": started_at,
        "native": bool(native),
        "preallocated": False,
    }
    with _locked(path):
        if metadata_path.exists():
            if metadata_path.is_symlink():
                raise MailboxError("refusing symlinked session metadata")
            try:
                previous = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise MailboxError("session metadata is unreadable") from error
            if previous.get("session_id") != session_id:
                raise MailboxError("session metadata identity does not match")
            return path
        _atomic_json(metadata_path, metadata)
    signal = path / "signal"
    if not signal.exists():
        _write_signal(path)
    return path


def reserve_session(
    session_id: str,
    *,
    cli: str,
    node: str = "",
    task: str = "",
    parent: str = "",
    started_at: str = "",
    home: Path | None = None,
) -> Path:
    session_id = _session_id(session_id)
    home = home or _home()
    path = session_path(home, session_id, create=True)
    metadata_path = path / "session.json"
    metadata = {
        "session_id": session_id,
        "cli": cli,
        "node": node,
        "task": task,
        "parent": parent,
        "window_id": "",
        "started_at": started_at,
        "native": False,
        "preallocated": True,
    }
    with _locked(path):
        if metadata_path.exists():
            raise MailboxError("session identity is already reserved")
        _atomic_json(metadata_path, metadata)
    _write_signal(path)
    return path


def consume_reservation(
    session_id: str,
    *,
    cli: str,
    node: str = "",
    task: str = "",
    parent: str = "",
    window_id: str = "",
    started_at: str = "",
    native: bool = False,
    home: Path | None = None,
) -> Path:
    session_id = _session_id(session_id)
    home = home or _home()
    path = session_path(home, session_id, create=False)
    configured = os.environ.get("CREW_INBOX")
    if configured and Path(configured).absolute() != path.absolute():
        raise MailboxError("CREW_INBOX does not match reserved session")
    metadata_path = path / "session.json"
    with _locked(path):
        if metadata_path.is_symlink():
            raise MailboxError("refusing symlinked session metadata")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise MailboxError("session reservation is unreadable") from error
        if metadata.get("session_id") != session_id or metadata.get("preallocated") is not True:
            raise MailboxError("session identity was not preallocated")
        metadata.update({
            "cli": cli,
            "node": node,
            "task": task,
            "parent": parent,
            "window_id": window_id,
            "started_at": started_at,
            "native": bool(native),
            "preallocated": False,
        })
        _atomic_json(metadata_path, metadata)
    return path


def _read_message(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MailboxError(f"message file is unreadable: {path.name}") from error
    if not isinstance(value, dict) or set(value) != {"id", "from", "text"}:
        raise MailboxError(f"message has an invalid shape: {path.name}")
    try:
        _session_id(value["id"], "message ID")
        _session_id(value["from"], "sender session ID")
    except (TypeError, MailboxError) as error:
        raise MailboxError(f"message identity is invalid: {path.name}") from error
    if not isinstance(value["text"], str):
        raise MailboxError(f"message text is invalid: {path.name}")
    if path.stem != value["id"]:
        raise MailboxError(f"message filename does not match its ID: {path.name}")
    return value


def publish_message(to_session: str, text: str, *, home: Path | None = None) -> str:
    to_session = _session_id(to_session, "destination session ID")
    from_session, _, _ = current_session()
    if not text:
        raise MailboxError("message text must not be empty")
    if "\x00" in text:
        raise MailboxError("message text cannot contain NUL")
    try:
        text_bytes = text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise MailboxError("message text must be valid UTF-8") from error
    if len(text_bytes) > MAX_MESSAGE_BYTES:
        raise MailboxError(
            "message text exceeds the 8 KiB UTF-8 limit; write a report file "
            "and send its path instead"
        )
    home = home or _home()
    destination = session_path(home, to_session, create=True)
    pending = destination / "pending"
    with _locked(destination):
        message_id = str(uuid.uuid4())
        while (pending / f"{message_id}.json").exists() or (
            destination / "received" / f"{message_id}.json"
        ).exists():
            message_id = str(uuid.uuid4())
        _atomic_json(pending / f"{message_id}.json", {
            "id": message_id,
            "from": from_session,
            "text": text,
        })
    # Claude watches this signal; other adapters may ignore the file.
    _write_signal(destination)
    return message_id


def claim_next(*, home: Path | None = None) -> dict | None:
    session_id, path, _ = current_session() if home is None else (
        _session_id(os.environ.get("CREW_SESSION_ID", "")),
        session_path(home, os.environ.get("CREW_SESSION_ID", ""), create=True),
        home,
    )
    pending = path / "pending"
    received = path / "received"
    delivery_path = path / ".delivery.json"
    with _locked(path):
        if delivery_path.exists():
            if delivery_path.is_symlink():
                raise MailboxError("refusing symlinked delivery marker")
            try:
                marker = json.loads(delivery_path.read_text(encoding="utf-8"))
                active_id = _session_id(marker["id"], "delivery message ID")
            except (OSError, KeyError, TypeError, json.JSONDecodeError, MailboxError) as error:
                raise MailboxError("delivery marker is unreadable") from error
            if (pending / f"{active_id}.json").is_file():
                return None
            if (received / f"{active_id}.json").is_file():
                delivery_path.unlink()
            else:
                # A crash after reserving delivery leaves a durable hold. Do not
                # automatically reinject a possibly received message.
                return None
        candidates = sorted(
            pending.glob("*.json"),
            key=lambda item: (item.stat().st_mtime_ns, item.name),
        )
        if not candidates:
            return None
        message = _read_message(candidates[0])
        _atomic_json(delivery_path, {"id": message["id"]})
        return message


def delivery_status(
    session_id: str,
    *,
    home: Path | None = None,
) -> dict[str, str | int] | None:
    """Return the age of a held delivery without changing mailbox state."""
    home = home or _home()
    path = session_path(home, session_id, create=False)
    marker_path = path / ".delivery.json"
    if marker_path.is_symlink():
        raise MailboxError("refusing symlinked delivery marker")
    try:
        marker_stat = marker_path.stat()
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        message_id = _session_id(marker["id"], "delivery message ID")
    except FileNotFoundError:
        return None
    except (
        OSError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        MailboxError,
    ) as error:
        raise MailboxError("delivery marker is unreadable") from error
    if (path / "received" / f"{message_id}.json").exists():
        return None
    age_seconds = max(0, int(time.time() - marker_stat.st_mtime))
    return {"id": message_id, "age_seconds": age_seconds}


def _write_signal(path: Path) -> None:
    signal = path / "signal"
    temporary = path / f".signal.{uuid.uuid4().hex}"
    try:
        with temporary.open("w", encoding="ascii") as output:
            os.chmod(temporary, 0o600)
            output.write(uuid.uuid4().hex + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, signal)
        _fsync_directory(path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def acknowledge(message_id: str, *, home: Path | None = None) -> bool:
    message_id = _session_id(message_id, "message ID")
    _, path, _ = current_session() if home is None else (
        _session_id(os.environ.get("CREW_SESSION_ID", "")),
        session_path(home, os.environ.get("CREW_SESSION_ID", ""), create=True),
        home,
    )
    pending = path / "pending" / f"{message_id}.json"
    received = path / "received" / f"{message_id}.json"
    delivery_path = path / ".delivery.json"
    with _locked(path):
        if received.exists():
            duplicate = True
            if delivery_path.is_file() and not delivery_path.is_symlink():
                with contextlib.suppress(OSError, json.JSONDecodeError):
                    marker = json.loads(delivery_path.read_text(encoding="utf-8"))
                    if marker.get("id") == message_id:
                        delivery_path.unlink()
        else:
            duplicate = False
            if not pending.is_file():
                raise MailboxError("message is not pending in this session")
            if delivery_path.is_symlink() or not delivery_path.is_file():
                raise MailboxError("message was not delivered to this session")
            try:
                marker = json.loads(delivery_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise MailboxError("delivery marker is unreadable") from error
            if marker.get("id") != message_id:
                raise MailboxError("another message is awaiting acknowledgement")
            _read_message(pending)
            # Rename is atomic because both directories share the session mailbox.
            os.replace(pending, received)
            _fsync_directory(received.parent)
            delivery_path.unlink()
            _fsync_directory(path)
        signal_next = any((path / "pending").glob("*.json"))
    if signal_next:
        _write_signal(path)
    return not duplicate


def codex_state(*, home: Path | None = None, session_id: str | None = None) -> dict | None:
    if home is None:
        home = _home()
    session_id = _session_id(session_id or os.environ.get("CREW_SESSION_ID", ""))
    path = session_path(home, session_id, create=False)
    state_path = path / "codex.json"
    if not state_path.exists():
        return None
    if state_path.is_symlink():
        raise MailboxError("refusing symlinked Codex metadata")
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MailboxError("Codex metadata is unreadable") from error
    if value.get("session_id") != session_id:
        raise MailboxError("Codex metadata identity does not match")
    return value


def set_codex_state(
    *,
    socket_path: str,
    thread_id: str | None,
    stale: bool,
    reason: str = "",
    home: Path | None = None,
) -> None:
    session_id, path, _ = current_session() if home is None else (
        _session_id(os.environ.get("CREW_SESSION_ID", "")),
        session_path(home, os.environ.get("CREW_SESSION_ID", ""), create=True),
        home,
    )
    state = {
        "session_id": session_id,
        "socket_path": socket_path,
        "thread_id": thread_id,
        "stale": bool(stale),
        "reason": reason,
    }
    with _locked(path):
        _atomic_json(path / "codex.json", state)


def format_for_agent(message: dict) -> str:
    return (
        "CREW_MESSAGE_ID: " + message["id"] + "\n"
        + "CREW_FROM: " + message["from"] + "\n\n"
        + message["text"]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--cli", required=True)
    init.add_argument("--node", default="")
    init.add_argument("--task", default="")
    init.add_argument("--parent", default="")
    init.add_argument("--window", default="")
    init.add_argument("--started-at", default="")
    init.add_argument("--native", choices=("0", "1"), default="0")
    init.add_argument("--consume-reservation", action="store_true")
    reserve = commands.add_parser("reserve")
    reserve.add_argument("--cli", required=True)
    reserve.add_argument("--node", default="")
    reserve.add_argument("--task", default="")
    reserve.add_argument("--parent", default="")
    reserve.add_argument("--started-at", default="")
    publish = commands.add_parser("publish")
    publish.add_argument("--to", required=True)
    commands.add_parser("claim")
    acknowledge_parser = commands.add_parser("ack")
    acknowledge_parser.add_argument("message_id")
    status = commands.add_parser("status")
    status.add_argument("--sessions", action="store_true")
    state = commands.add_parser("codex-state")
    state.add_argument("--session", default="")
    set_state = commands.add_parser("codex-set")
    set_state.add_argument("--socket", required=True)
    set_state.add_argument("--thread", default="")
    set_state.add_argument("--stale", choices=("yes", "no"), required=True)
    set_state.add_argument("--reason", default="")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            session_id = _session_id(os.environ.get("CREW_SESSION_ID", ""))
            options = {
                "cli": args.cli,
                "node": args.node,
                "task": args.task,
                "parent": args.parent,
                "window_id": args.window,
                "started_at": args.started_at,
                "native": args.native == "1",
            }
            path = (
                consume_reservation(session_id, **options)
                if args.consume_reservation
                else initialize_session(session_id, **options)
            )
            print(path)
        elif args.command == "reserve":
            session_id = _session_id(os.environ.get("CREW_SESSION_ID", ""))
            path = reserve_session(
                session_id,
                cli=args.cli,
                node=args.node,
                task=args.task,
                parent=args.parent,
                started_at=args.started_at,
            )
            print(path)
        elif args.command == "publish":
            raw = sys.stdin.buffer.read(MAX_MESSAGE_BYTES + 1)
            if len(raw) > MAX_MESSAGE_BYTES:
                raise MailboxError(
                    "message text exceeds the 8 KiB UTF-8 limit; write a "
                    "report file and send its path instead"
                )
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as error:
                raise MailboxError("message text must be valid UTF-8") from error
            print(publish_message(args.to, text))
        elif args.command == "claim":
            message = claim_next()
            if message is not None:
                print(json.dumps(message, ensure_ascii=False, separators=(",", ":")))
        elif args.command == "ack":
            changed = acknowledge(args.message_id)
            print(("acknowledged " if changed else "already acknowledged ") + args.message_id)
        elif args.command == "status":
            if not args.sessions:
                raise MailboxError("status requires --sessions")
            session_ids = sorted({
                line.strip() for line in sys.stdin if line.strip()
            })
            values = {}
            for session_id in session_ids:
                try:
                    values[session_id] = delivery_status(session_id)
                except (MailboxError, OSError):
                    values[session_id] = {"status": "unavailable"}
            print(json.dumps(values, separators=(",", ":")))
        elif args.command == "codex-state":
            value = codex_state(session_id=args.session or None)
            if value is not None:
                print(json.dumps(value, separators=(",", ":")))
        elif args.command == "codex-set":
            set_codex_state(
                socket_path=args.socket,
                thread_id=args.thread or None,
                stale=args.stale == "yes",
                reason=args.reason,
            )
        return 0
    except (MailboxError, OSError) as error:
        _die(str(error))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

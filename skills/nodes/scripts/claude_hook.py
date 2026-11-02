#!/usr/bin/env python3
"""Deliver one crew message from a Claude FileChanged hook."""

import fcntl
import json
import os
from pathlib import Path
import sys

from mailbox import (
    MailboxError, _atomic_json, _write_signal, claim_next, current_session,
    format_for_agent,
)


def claim_for_event(inbox: Path, event: dict, *, start: bool) -> dict | None:
    """Serialize live-session changes with the guard and mailbox claim."""
    record = inbox / "claude-session.json"
    session_id = event.get("session_id")
    descriptor = os.open(
        inbox / ".claude-session.lock", os.O_CREAT | os.O_RDWR, 0o600,
    )
    with os.fdopen(descriptor, "r+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if start:
            if isinstance(session_id, str) and session_id:
                _atomic_json(record, {"session_id": session_id})
            else:
                record.unlink(missing_ok=True)
        elif isinstance(session_id, str) and session_id:
            try:
                live = json.loads(record.read_text(encoding="utf-8"))
                live_id = (
                    live.get("session_id") if isinstance(live, dict) else None
                )
            except (OSError, UnicodeError, ValueError):
                live_id = None
            if isinstance(live_id, str) and live_id and live_id != session_id:
                return None
        return claim_next()


def main() -> int:
    try:
        event = json.load(sys.stdin)
        event_name = event.get("hook_event_name")
        _, inbox, _ = current_session()
        signal = inbox / "signal"
        if event_name == "SessionStart":
            if not signal.exists():
                _write_signal(inbox)
            message = claim_for_event(inbox, event, start=True)
            output = {
                "hookEventName": "SessionStart",
                "watchPaths": [str(signal)],
            }
            if message is not None:
                output["additionalContext"] = (
                    format_for_agent(message)
                    + f"\nAcknowledge now: crew-nodes ack {message['id']}"
                )
            print(json.dumps({"hookSpecificOutput": output}))
            return 0
        if event_name != "FileChanged":
            return 0
        changed_path = event.get("file_path")
        if not isinstance(changed_path, str):
            return 0
        if Path(changed_path).absolute() != signal.absolute():
            return 0
        message = claim_for_event(inbox, event, start=False)
        if message is None:
            return 0
        sys.stderr.write(
            format_for_agent(message)
            + f"\nAcknowledge now: crew-nodes ack {message['id']}\n"
        )
        sys.stderr.flush()
        # asyncRewake turns this feedback into a system reminder, even when
        # Claude is idle. The agent, not the hook, acknowledges the message.
        return 2
    except (MailboxError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"crew Claude hook: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

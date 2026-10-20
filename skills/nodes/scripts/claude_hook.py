#!/usr/bin/env python3
"""Deliver one crew message from a Claude FileChanged hook."""

import json
from pathlib import Path
import sys

from mailbox import (
    MailboxError, _write_signal, claim_next, current_session, format_for_agent,
)


def main() -> int:
    try:
        event = json.load(sys.stdin)
        event_name = event.get("hook_event_name")
        _, inbox, _ = current_session()
        signal = inbox / "signal"
        if event_name == "SessionStart":
            if not signal.exists():
                _write_signal(inbox)
            message = claim_next()
            output = {
                "hookEventName": "SessionStart",
                "watchPaths": [str(signal)],
            }
            if message is not None:
                output["additionalContext"] = format_for_agent(message)
            print(json.dumps({"hookSpecificOutput": output}))
            return 0
        if event_name != "FileChanged":
            return 0
        changed_path = event.get("file_path")
        if not isinstance(changed_path, str):
            return 0
        if Path(changed_path).absolute() != signal.absolute():
            return 0
        message = claim_next()
        if message is None:
            return 0
        sys.stderr.write(format_for_agent(message) + "\n")
        sys.stderr.flush()
        # asyncRewake turns this feedback into a system reminder, even when
        # Claude is idle. The agent, not the hook, acknowledges the message.
        return 2
    except (MailboxError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"crew Claude hook: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

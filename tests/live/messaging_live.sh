#!/usr/bin/env bash
# Run with: nix develop -c bash tests/live/messaging_live.sh
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
export PATH="$root/bin:$PATH"
for program in kitty kitten jq python3 claude crew-nodes; do
  command -v "$program" >/dev/null 2>&1 || {
    printf 'messaging-live: required program not found: %s\n' "$program" >&2
    exit 1
  }
done

runs=${CREW_RUNS:-${XDG_DATA_HOME:-$HOME/.local/share}/crew/runs}
task=${CREW_TASK:-messaging-live}
[[ $task != */* && $task != . && $task != .. ]] || {
  printf 'messaging-live: task label must be one path component.\n' >&2
  exit 2
}
run_root=$runs/$task/claude-smoke-$(date +%s)-$$
mkdir -p "$run_root"
chmod 700 "$run_root"
xdg_home=$run_root/xdg
mkdir -p "$xdg_home"
parent_session=$(python3 -c 'import uuid; print(uuid.uuid4())')
tmp=$(mktemp -d "${TMPDIR:-/tmp}/crew-msg-live.XXXXXX")
listen_on="unix:$tmp/kitty.sock"

export PATH="$root/bin:$PATH"
export KITTY_LISTEN_ON=$listen_on
export XDG_DATA_HOME=$xdg_home
export CREW_HOME=$XDG_DATA_HOME/crew
export CREW_MEMORY=$CREW_HOME/memory
export CREW_RUNS=$CREW_HOME/runs
export CREW_BIN=$root/bin/crew
export CREW_CORE_INSTRUCTIONS=$root/core/instructions.md
export CREW_SKILLS=$root/skills
export CREW_PLUGIN=$root/claude
export CREW_SESSION_ID=$parent_session
export CREW_INBOX=$CREW_HOME/mailboxes/$parent_session
export CREW_CLI=pi
export CREW_TASK=$task
export CREW_NODE=smoke-parent
export CREW_NODES_SCRIPT=$root/skills/nodes/scripts/nodes.sh

python3 "$CREW_SKILLS/nodes/scripts/mailbox.py" init \
  --cli pi --node "$CREW_NODE" --task "$CREW_TASK" \
  --window "" --native 1 >/dev/null

kitty_pid=''
worker_id=''
cleanup() {
  local status=$?
  trap - EXIT
  if [[ -n $worker_id ]]; then
    screen=$(crew-nodes read "$worker_id" screen 2>/dev/null || true)
    if grep -Fq 'Esc to interrupt' <<<"$screen"; then
      crew-nodes interrupt "$worker_id" >/dev/null 2>&1 || true
      for _ in {1..50}; do
        screen=$(crew-nodes read "$worker_id" screen 2>/dev/null || true)
        grep -Fq 'Esc to interrupt' <<<"$screen" || break
        sleep 0.1
      done
    fi
    crew-nodes close "$worker_id" >/dev/null 2>&1 || true
  fi
  if [[ -n $kitty_pid ]]; then
    kill "$kitty_pid" 2>/dev/null || true
    wait "$kitty_pid" 2>/dev/null || true
  fi
  rm -rf -- "$tmp"
  exit "$status"
}
trap cleanup EXIT

cat >"$run_root/guardian.sh" <<'GUARDIAN'
#!/usr/bin/env bash
exec sleep 3600
GUARDIAN
chmod +x "$run_root/guardian.sh"
kitty --config NONE -o allow_remote_control=socket-only \
  --listen-on "$listen_on" --start-as=hidden --directory "$root" \
  "$run_root/guardian.sh" >"$run_root/kitty.log" 2>&1 &
kitty_pid=$!

ready=0
for _ in {1..100}; do
  if listing=$(kitten @ --to "$listen_on" ls 2>/dev/null); then
    parent_id=$(jq -r '.[0].tabs[0].windows[0].id // empty' <<<"$listing")
    if [[ $parent_id =~ ^[1-9][0-9]*$ ]]; then
      ready=1
      break
    fi
  fi
  kill -0 "$kitty_pid" 2>/dev/null || {
    printf 'messaging-live: hidden Kitty exited during startup.\n' >&2
    exit 1
  }
  sleep 0.1
done
[[ $ready == 1 ]] || {
  printf 'messaging-live: hidden Kitty did not open its socket.\n' >&2
  exit 1
}
export KITTY_WINDOW_ID=$parent_id
kitten @ --to "$listen_on" set-user-vars --match "id:$parent_id" \
  "crew_session=$parent_session" crew_cli=pi crew_native=1

prompt=$(cat <<PROMPT
This is a bounded native messaging smoke test. Do not inspect or modify the
repository. First reply exactly SMOKE_READY and stop. Then wait for one crew
message. After reading it, run crew-nodes ack MESSAGE_ID with the ID shown in
its header. Reply exactly SMOKE_ACK:<nonce> using the nonce from that message.
Do not call notify.
PROMPT
)
worker_id=$(crew-nodes spawn --name claude-message-smoke --cli claude \
  --cwd "$root" --task "$task" -- --model haiku "$prompt")
[[ $worker_id =~ ^[1-9][0-9]*$ ]] || {
  printf 'messaging-live: Claude spawn returned no window ID.\n' >&2
  exit 1
}
listing=$(kitten @ --to "$listen_on" ls)
worker_session=$(jq -r --arg id "$worker_id" '
  [.[]?.tabs[]?.windows[]? | select((.id | tostring) == $id)
   | .user_vars.crew_session // empty][0] // empty
' <<<"$listing")
[[ $worker_session =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || {
  printf 'messaging-live: spawned Claude session has no identity label.\n' >&2
  exit 1
}
worker_inbox=$CREW_HOME/mailboxes/$worker_session

ready=0
for _ in {1..180}; do
  screen=$(crew-nodes read "$worker_id" screen 2>/dev/null || true)
  if grep -Fq 'SMOKE_READY' <<<"$screen"; then
    ready=1
    break
  fi
  if grep -Eiq 'trust this folder|trust project|do you trust' <<<"$screen"; then
    printf 'messaging-live: trust dialog needs a human response.\n' >&2
    exit 1
  fi
  sleep 0.25
done
[[ $ready == 1 ]] || {
  printf 'messaging-live: Claude did not finish its smoke-test bootstrap.\n' >&2
  exit 1
}

nonce=$(python3 -c 'import secrets; print(secrets.token_hex(12))')
message=$(printf 'Fixture-only message. Nonce: %s. Do not edit files. Read the message, acknowledge its ID with crew-nodes ack, then reply SMOKE_ACK:%s.' "$nonce" "$nonce")
queued=$(printf '%s\n' "$message" | crew-nodes send "$worker_id")
message_id=${queued##* }
[[ $message_id =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || {
  printf 'messaging-live: native send did not return a message ID.\n' >&2
  exit 1
}

received=$worker_inbox/received/$message_id.json
acknowledged=0
for _ in {1..240}; do
  screen=$(crew-nodes read "$worker_id" screen 2>/dev/null || true)
  if [[ -f $received ]] && grep -Fq "SMOKE_ACK:$nonce" <<<"$screen"; then
    acknowledged=1
    break
  fi
  sleep 0.25
done
[[ $acknowledged == 1 ]] || {
  printf 'messaging-live: Claude did not explicitly ack the native message.\n' >&2
  exit 1
}
[[ ! -e $worker_inbox/pending/$message_id.json ]] || {
  printf 'messaging-live: acknowledged message remains pending.\n' >&2
  exit 1
}
[[ ! -e $worker_inbox/.delivery.json ]] || {
  printf 'messaging-live: dispatch marker remains after ack.\n' >&2
  exit 1
}

python3 - "$run_root/result.json" "$worker_session" "$message_id" "$nonce" <<'PY'
import json
from pathlib import Path
import sys
path, session_id, message_id, nonce = sys.argv[1:]
Path(path).write_text(json.dumps({
    "status": "passed",
    "cli": "claude",
    "model_requested": "haiku",
    "session_id": session_id,
    "message_id": message_id,
    "nonce_acknowledged": True,
    "channels_used": False,
    "provider_changed": False,
}, indent=2) + "\n")
PY
printf 'messaging-live: Claude Haiku explicitly acknowledged native message %s.\n' "$message_id"

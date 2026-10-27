#!/usr/bin/env bash
# Run with: nix develop -c bash tests/live/nodes_live.sh
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
helper=$root/skills/nodes/scripts/nodes.sh
mailbox=$root/skills/nodes/scripts/mailbox.py
for program in kitty kitten jq python3; do
  command -v "$program" >/dev/null 2>&1 || {
    printf 'nodes-live: required program not found: %s\n' "$program" >&2
    exit 1
  }
done

tmp=$(mktemp -d "${TMPDIR:-/tmp}/crew-nodes-live.XXXXXX")
listen_on="unix:$tmp/kitty.sock"
parent_session=$(python3 -c 'import uuid; print(uuid.uuid4())')
export CREW_HOME=$tmp/crew
export CREW_RUNS=$tmp/runs
export CREW_SESSION_ID=$parent_session
export CREW_INBOX=$CREW_HOME/mailboxes/$CREW_SESSION_ID
export CREW_CLI=pi
export CREW_NODES_SCRIPT=$helper
unset CLAUDE_CODE_SESSION_ID CODEX_THREAD_ID
mkdir -p "$tmp/bin"
ln -s "$root/bin/crew-nodes" "$tmp/bin/crew-nodes"
export PATH="$tmp/bin:$root/bin:$PATH"
export CREW_LIVE_REPORT="$tmp/report.md"
export KITTY_LISTEN_ON=$listen_on
export CREW_ROLE=''

python3 "$mailbox" init --cli pi --native 1 >/dev/null
kitty_pid=''
parent_id=''
node_id=''
extra_tab_id=''
split_id=''
cleanup() {
  local status=$?
  trap - EXIT
  if [[ -n $split_id ]]; then
    crew-nodes close "$split_id" >/dev/null 2>&1 || true
  fi
  if [[ -n $extra_tab_id ]]; then
    kitten @ --to "$listen_on" close-window --match "id:$extra_tab_id" \
      >/dev/null 2>&1 || true
  fi
  if [[ -n $node_id ]]; then
    crew-nodes close "$node_id" >/dev/null 2>&1 || true
  fi
  if [[ -n $kitty_pid ]]; then
    kill "$kitty_pid" 2>/dev/null || true
    wait "$kitty_pid" 2>/dev/null || true
  fi
  if [[ $status == 0 ]]; then
    rm -rf -- "$tmp"
  else
    printf 'nodes-live: diagnostic files kept under %s\n' "$tmp" >&2
  fi
  exit "$status"
}
trap cleanup EXIT

cat >"$tmp/crew-fake" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf 'marker=%s\n' "${CREW_LIVE_MARKER:-}"
printf 'role=%s\n' "${CREW_ROLE:-}"
printf 'task=%s\n' "${CREW_TASK:-}"
printf 'kitty_window=%s\n' "${KITTY_WINDOW_ID:-}"
printf 'kitty_listen=%s\n' "${KITTY_LISTEN_ON:-}"
printf 'crew_parent=%s\n' "${CREW_PARENT:-}"
printf 'live report\n' >"${CREW_LIVE_REPORT:?}"
crew-nodes notify done "$CREW_LIVE_REPORT"
printf 'READY\n'
while :; do
  printf '❯ '
  IFS= read -r message || exit 0
  case $message in
    ping) printf 'pong\n' ;;
    stop) exit 0 ;;
  esac
done
FAKE
chmod +x "$tmp/crew-fake"

cat >"$tmp/parent.sh" <<'PARENT'
#!/usr/bin/env bash
set -euo pipefail
while :; do
  printf '❯ '
  IFS= read -r line || exit 0
  printf 'PARENT_INPUT=%s\n' "$line"
done
PARENT
chmod +x "$tmp/parent.sh"

export CREW_LIVE_MARKER=crew-live-marker
kitty --config NONE -o allow_remote_control=socket-only \
  --listen-on "$listen_on" --start-as=hidden --directory "$tmp" \
  "$tmp/parent.sh" >"$tmp/kitty.log" 2>&1 &
kitty_pid=$!

ready=0
for _ in {1..100}; do
  if kitten @ --to "$listen_on" ls >"$tmp/ls.json" 2>/dev/null; then
    ready=1
    break
  fi
  kill -0 "$kitty_pid" 2>/dev/null || {
    printf 'nodes-live: hidden Kitty exited during startup.\n' >&2
    exit 1
  }
  sleep 0.1
done
[[ $ready == 1 ]] || {
  printf 'nodes-live: hidden Kitty did not open its socket.\n' >&2
  exit 1
}
parent_id=$(jq -r '.[0].tabs[0].windows[0].id // empty' "$tmp/ls.json")
[[ $parent_id =~ ^[1-9][0-9]*$ ]] || {
  printf 'nodes-live: hidden Kitty has no initial window.\n' >&2
  exit 1
}
export KITTY_WINDOW_ID=$parent_id
kitten @ --to "$listen_on" set-user-vars --match "id:$parent_id" \
  "crew_session=$parent_session" crew_cli=pi crew_native=1

parent_ready=0
for _ in {1..50}; do
  parent_transcript=$(kitten @ --to "$listen_on" get-text \
    --match "id:$parent_id" --ansi)
  if grep -Fq '❯' <<<"$parent_transcript"; then
    parent_ready=1
    break
  fi
  sleep 0.1
done
[[ $parent_ready == 1 ]] || {
  printf 'nodes-live: parent input did not become ready.\n' >&2
  exit 1
}
human_input='human is drafting'
printf '%s' "$human_input" | kitten @ --to "$listen_on" \
  send-text --match "id:$parent_id" --stdin
sleep 0.2
parent_transcript=$(kitten @ --to "$listen_on" get-text \
  --match "id:$parent_id" --ansi)
grep -Fq "$human_input" <<<"$parent_transcript" || {
  printf 'nodes-live: parent did not retain the synthetic draft.\n' >&2
  exit 1
}

export CREW_BIN=$tmp/crew-fake
export CREW_TASK=live-test
node_id=$(crew-nodes spawn --name live-test --cli claude \
  --cwd "$tmp" --task live-test)
[[ $node_id =~ ^[1-9][0-9]*$ ]] || {
  printf 'nodes-live: spawn did not return a window ID.\n' >&2
  exit 1
}

worker_ready=0
for _ in {1..100}; do
  transcript=$(crew-nodes read "$node_id" screen)
  if grep -Fq 'READY' <<<"$transcript"; then
    worker_ready=1
    break
  fi
  sleep 0.1
done
[[ $worker_ready == 1 ]] || {
  printf 'nodes-live: fake worker did not become ready.\n' >&2
  exit 1
}

parent_inbox=$CREW_HOME/mailboxes/$parent_session
pending_file=''
for _ in {1..100}; do
  for candidate in "$parent_inbox"/pending/*.json; do
    [[ -f $candidate ]] || continue
    pending_file=$candidate
    break
  done
  [[ -n $pending_file ]] && break
  sleep 0.1
done
[[ -n $pending_file ]] || {
  printf 'nodes-live: native notice was not stored in the parent inbox.\n' >&2
  exit 1
}
message=$(jq -c . "$pending_file")
message_id=$(jq -r .id <<<"$message")
expected_notice="live-test/live-test: done. Report: $CREW_LIVE_REPORT. Metrics: metrics unavailable"
[[ $(jq -r .text <<<"$message") == "$expected_notice" ]] || {
  printf 'nodes-live: stored notice text was unexpected.\n' >&2
  exit 1
}
[[ $(jq -r 'keys | sort | join(",")' <<<"$message") == "from,id,text" ]] || {
  printf 'nodes-live: message envelope has unexpected fields.\n' >&2
  exit 1
}
parent_transcript=$(kitten @ --to "$listen_on" get-text \
  --match "id:$parent_id" --ansi)
grep -Fq "$human_input" <<<"$parent_transcript" || {
  printf 'nodes-live: native notice changed the parent draft.\n' >&2
  exit 1
}
! grep -Fq 'PARENT_INPUT=' <<<"$parent_transcript" || {
  printf 'nodes-live: native notice submitted the parent draft.\n' >&2
  exit 1
}

# The controller stands in for the parent agent: it claims, reads, and acks.
claimed=$(crew-nodes _mailbox claim)
[[ $(jq -r .id <<<"$claimed") == "$message_id" ]] || {
  printf 'nodes-live: parent claimed the wrong message.\n' >&2
  exit 1
}
crew-nodes ack "$message_id" >/dev/null
[[ -f $parent_inbox/received/$message_id.json &&
  ! -e $parent_inbox/pending/$message_id.json ]] || {
  printf 'nodes-live: explicit ack did not move the notice to received.\n' >&2
  exit 1
}

printf 'ping' | crew-nodes type "$node_id" --enter
transcript=$(crew-nodes read "$node_id" all)
for expected in \
  "marker=$CREW_LIVE_MARKER" \
  'role=worker' \
  'task=live-test' \
  'pong'; do
  grep -Fq "$expected" <<<"$transcript" || {
    printf 'nodes-live: missing fake worker output: %s\n' "$expected" >&2
    exit 1
  }
done

extra_tab_id=$(kitten @ --to "$listen_on" launch --type=tab \
  --title split-anchor-test --cwd "$tmp" "$tmp/parent.sh")
[[ $extra_tab_id =~ ^[1-9][0-9]*$ ]] || {
  printf 'nodes-live: could not create the extra active tab.\n' >&2
  exit 1
}
split_id=$(crew-nodes spawn --name live-split --cli claude \
  --cwd "$tmp" --task live-test --split)
[[ $split_id =~ ^[1-9][0-9]*$ ]] || {
  printf 'nodes-live: split spawn did not return a window ID.\n' >&2
  exit 1
}
split_ready=0
for _ in {1..100}; do
  transcript=$(crew-nodes read "$split_id" screen)
  if grep -Fq 'READY' <<<"$transcript"; then
    split_ready=1
    break
  fi
  sleep 0.1
done
[[ $split_ready == 1 ]] || {
  printf 'nodes-live: split fake worker did not become ready.\n' >&2
  exit 1
}
for expected in "kitty_window=$split_id" \
  "kitty_listen=$listen_on" "crew_parent=$parent_id"; do
  grep -Fq "$expected" <<<"$transcript" || {
    printf 'nodes-live: split worker missing launch environment: %s\n' \
      "$expected" >&2
    exit 1
  }
done
kitten @ --to "$listen_on" ls >"$tmp/after-split.json"
parent_tab=$(jq -r --argjson id "$parent_id" \
  '.[] | .tabs[] | select(any(.windows[]; .id == $id)) | .id' \
  "$tmp/after-split.json")
split_tab=$(jq -r --argjson id "$split_id" \
  '.[] | .tabs[] | select(any(.windows[]; .id == $id)) | .id' \
  "$tmp/after-split.json")
[[ -n $parent_tab && $parent_tab == "$split_tab" ]] || {
  printf 'nodes-live: split window did not land in caller tab.\n' >&2
  exit 1
}
closed_split_id=$split_id
crew-nodes close "$split_id"
kitten @ --to "$listen_on" close-window --match "id:$extra_tab_id"
extra_tab_id=''
split_id=''
kitten @ --to "$listen_on" ls >"$tmp/after-close.json"
jq -e --argjson id "$parent_id" \
  'any(.[].tabs[].windows[]; .id == $id)' "$tmp/after-close.json" >/dev/null
jq -e --argjson id "$node_id" \
  'any(.[].tabs[].windows[]; .id == $id)' "$tmp/after-close.json" >/dev/null
if jq -e --argjson id "$closed_split_id" \
  'any(.[].tabs[].windows[]; .id == $id)' "$tmp/after-close.json" >/dev/null; then
  printf 'nodes-live: close left the split window open.\n' >&2
  exit 1
fi
bash -n "$helper"
printf '%s\n' \
  'nodes-live: native notice stored and explicitly acknowledged.' \
  'nodes-live: native notice preserved the parent editor draft.' \
  'nodes-live: explicit type command still sends terminal input.'

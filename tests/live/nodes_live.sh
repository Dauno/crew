#!/usr/bin/env bash
# Run with: nix develop -c bash tests/live/nodes_live.sh
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
helper=$root/skills/nodes/scripts/nodes.sh
for program in kitty kitten jq awk python3; do
  command -v "$program" >/dev/null 2>&1 || {
    printf 'nodes-live: required program not found: %s\n' "$program" >&2
    exit 1
  }
done

tmp=$(mktemp -d "${TMPDIR:-/tmp}/crew-nodes-live.XXXXXX")
listen_on="unix:$tmp/kitty.sock"
mkdir -p "$tmp/bin"
ln -s "$helper" "$tmp/bin/crew-nodes"
export PATH="$tmp/bin:$PATH"
export CREW_LIVE_REPORT="$tmp/report.md"
export CREW_RUNS="$tmp/runs"
export CREW_HOME="$tmp/crew"
export CREW_NODES_TESTING=1
export CREW_NODES_TEST_SEND_WAIT_SECONDS=1
export CREW_NODES_TEST_NOTICE_WAIT_SECONDS=15
kitty_pid=''
parent_id=''
node_id=''
worker_id=''
notice_dir=$CREW_RUNS/live-test/notices
pending_notice=''

cleanup() {
  local status=$?
  trap - EXIT
  if [[ -n $node_id && -n $parent_id ]]; then
    KITTY_LISTEN_ON=$listen_on KITTY_WINDOW_ID=$parent_id \
      bash "$helper" close "$node_id" >/dev/null 2>&1 || true
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

find_pending_notice() {
  local candidate
  pending_notice=''
  for candidate in "$notice_dir"/notice.*; do
    [[ -f $candidate && $candidate != *.status ]] || continue
    pending_notice=$candidate
    return 0
  done
  return 1
}

report_notice_state() {
  local status_file state=missing sender_pid='' alive=no
  local last_input=unknown reason=none
  find_pending_notice || true
  if [[ -z $pending_notice ]]; then
    printf 'nodes-live: no pending file in %s\n' "$notice_dir" >&2
    return
  fi
  status_file=$pending_notice.status
  if [[ -f $status_file ]]; then
    state=$(awk -F= '$1 == "state" {print $2; exit}' "$status_file")
    sender_pid=$(awk -F= '$1 == "pid" {print $2; exit}' "$status_file")
    last_input=$(awk -F= '$1 == "last_input" {print $2; exit}' \
      "$status_file")
    reason=$(awk -F= '$1 == "reason" {sub(/^[^=]*=/, ""); print; exit}' \
      "$status_file")
    if [[ $sender_pid =~ ^[1-9][0-9]*$ ]] &&
      kill -0 "$sender_pid" 2>/dev/null; then
      alive=yes
    fi
  fi
  printf 'nodes-live: pending notice: %s\n' "$pending_notice" >&2
  printf 'nodes-live: sender_alive=%s state=%s last_input=%s\n' \
    "$alive" "$state" "$last_input" >&2
  printf 'nodes-live: sender reason: %s\n' "$reason" >&2
}

cat >"$tmp/crew-fake" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf 'marker=%s\n' "${CREW_LIVE_MARKER:-}"
printf 'role=%s\n' "${CREW_ROLE:-}"
printf 'task=%s\n' "${CREW_TASK:-}"
printf 'live report\n' >"${CREW_LIVE_REPORT:?}"
crew-nodes notify done "$CREW_LIVE_REPORT"
printf 'parent=%s\n' "${CREW_PARENT:-}"
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
while IFS= read -e -r -p '❯ ' line; do
  printf 'PARENT_NOTICE=%s\n' "$line"
done
PARENT
chmod +x "$tmp/parent.sh"

export CREW_LIVE_MARKER=crew-live-marker
export KITTY_LISTEN_ON=$listen_on
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
export CREW_BIN=$tmp/crew-fake
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
  printf 'nodes-live: parent did not retain the typed input.\n' >&2
  exit 1
}

node_id=$(bash "$helper" spawn --name live-test --cli claude \
  --cwd "$tmp" --task live-test)
[[ $node_id =~ ^[1-9][0-9]*$ ]] || {
  printf 'nodes-live: spawn did not return a window ID.\n' >&2
  exit 1
}
sender_ready=0
for _ in {1..150}; do
  find_pending_notice || true
  if [[ -n $pending_notice && -f $pending_notice.status ]] &&
    grep -Fq 'state=running' "$pending_notice.status"; then
    sender_ready=1
    break
  fi
  sleep 0.1
done
if [[ $sender_ready != 1 ]]; then
  report_notice_state
  printf 'nodes-live: background sender did not start.\n' >&2
  exit 1
fi

worker_ready=0
for _ in {1..50}; do
  transcript=$(bash "$helper" read "$node_id" screen)
  if grep -Fq 'READY' <<<"$transcript"; then
    worker_ready=1
    break
  fi
  sleep 0.1
done
if [[ $worker_ready != 1 ]]; then
  report_notice_state
  printf 'nodes-live: worker did not resume after notify.\n' >&2
  exit 1
fi
if ! grep -Fq 'last_input=busy' "$pending_notice.status"; then
  report_notice_state
  printf 'nodes-live: sender did not record occupied input.\n' >&2
  exit 1
fi

parent_transcript=$(bash "$helper" read "$parent_id" screen)
grep -Fq "$human_input" <<<"$parent_transcript" || {
  report_notice_state
  printf 'nodes-live: human input disappeared while sender waited.\n' >&2
  exit 1
}
if grep -Fq 'PARENT_NOTICE=' <<<"$parent_transcript"; then
  report_notice_state
  printf 'nodes-live: notice arrived before input was cleared.\n' >&2
  exit 1
fi

printf 'ping' | bash "$helper" send "$node_id" --enter
transcript=$(bash "$helper" read "$node_id" screen)
for expected in \
  "marker=$CREW_LIVE_MARKER" \
  'role=worker' \
  'task=live-test' \
  "parent=$parent_id" \
  'pong'; do
  if ! grep -Fq "$expected" <<<"$transcript"; then
    report_notice_state
    printf 'nodes-live: missing worker output: %s\n' "$expected" >&2
    exit 1
  fi
done
bash "$helper" close "$node_id"
worker_id=$node_id
node_id=''
worker_closed=0
for _ in {1..50}; do
  if ! bash "$helper" list | jq -e --arg id "$worker_id" \
    'select((.id | tostring) == $id)' >/dev/null; then
    worker_closed=1
    break
  fi
  sleep 0.1
done
if [[ $worker_closed != 1 ]]; then
  node_id=$worker_id
  report_notice_state
  printf 'nodes-live: worker window did not close.\n' >&2
  exit 1
fi
sender_pid=$(awk -F= '$1 == "pid" {print $2; exit}' \
  "$pending_notice.status")
if [[ ! $sender_pid =~ ^[1-9][0-9]*$ ]] ||
  ! kill -0 "$sender_pid" 2>/dev/null; then
  report_notice_state
  printf 'nodes-live: sender did not survive worker close.\n' >&2
  exit 1
fi

parent_transcript=$(bash "$helper" read "$parent_id" screen)
grep -Fq "$human_input" <<<"$parent_transcript" || {
  report_notice_state
  printf 'nodes-live: closing worker cleared parent input.\n' >&2
  exit 1
}
if grep -Fq 'PARENT_NOTICE=' <<<"$parent_transcript"; then
  report_notice_state
  printf 'nodes-live: notice arrived before input was cleared.\n' >&2
  exit 1
fi
kitten @ --to "$listen_on" send-key --match "id:$parent_id" ctrl+a ctrl+k
parent_transcript=$(kitten @ --to "$listen_on" get-text \
  --match "id:$parent_id" --ansi)
if grep -Fq "$human_input" <<<"$parent_transcript"; then
  report_notice_state
  printf 'nodes-live: parent input did not clear.\n' >&2
  exit 1
fi

expected_notice="live-test/live-test: done. Report: $CREW_LIVE_REPORT."
expected_notice+=" Metrics: "
notice_ready=0
for _ in {1..100}; do
  parent_transcript=$(bash "$helper" read "$parent_id" screen)
  if grep -Fq "PARENT_NOTICE=$expected_notice" <<<"$parent_transcript"; then
    notice_ready=1
    break
  fi
  sleep 0.1
done
if [[ $notice_ready != 1 ]]; then
  report_notice_state
  printf '%s\n' \
    'nodes-live: parent did not receive notice after input cleared.' >&2
  exit 1
fi
[[ ! -e $pending_notice && ! -e $pending_notice.status ]] || {
  report_notice_state
  printf 'nodes-live: delivered notice files remain pending.\n' >&2
  exit 1
}
printf '%s\n' \
  'nodes-live: background sender survived worker close and delivered.'

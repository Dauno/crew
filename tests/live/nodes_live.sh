#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
helper=$root/skills/nodes/scripts/nodes.sh
for program in kitty kitten jq; do
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
kitty_pid=''
parent_id=''
node_id=''

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
  rm -rf -- "$tmp"
  exit "$status"
}
trap cleanup EXIT

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
while IFS= read -r message; do
  case $message in
    ping) printf 'pong\n' ;;
    stop) exit 0 ;;
  esac
done
FAKE
chmod +x "$tmp/crew-fake"

export CREW_LIVE_MARKER=crew-live-marker
export KITTY_LISTEN_ON=$listen_on
# shellcheck disable=SC2016
kitty --config NONE -o allow_remote_control=socket-only \
  --listen-on "$listen_on" --start-as=hidden --directory "$tmp" \
  bash -c 'while IFS= read -r line; do
    printf "PARENT_NOTICE=%s\n" "$line"
  done' >"$tmp/kitty.log" 2>&1 &
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
node_id=$(bash "$helper" spawn --name live-test --cli claude \
  --cwd "$tmp" --task live-test)
[[ $node_id =~ ^[1-9][0-9]*$ ]] || {
  printf 'nodes-live: spawn did not return a window ID.\n' >&2
  exit 1
}
printf 'ping' | bash "$helper" send "$node_id" --enter
transcript=$(bash "$helper" read "$node_id" screen)
for expected in \
  "marker=$CREW_LIVE_MARKER" \
  'role=worker' \
  'task=live-test' \
  "parent=$parent_id" \
  'pong'; do
  if ! grep -Fq "$expected" <<<"$transcript"; then
    printf 'nodes-live: missing worker output: %s\n' "$expected" >&2
    exit 1
  fi
done
expected_notice="live-test/live-test: done. Report: $CREW_LIVE_REPORT"
notice_ready=0
for _ in {1..100}; do
  parent_transcript=$(bash "$helper" read "$parent_id" screen)
  if grep -Fq "PARENT_NOTICE=$expected_notice" <<<"$parent_transcript"; then
    notice_ready=1
    break
  fi
  sleep 0.1
done
[[ $notice_ready == 1 ]] || {
  printf 'nodes-live: parent did not receive the exact notice.\n' >&2
  exit 1
}
bash "$helper" close "$node_id"
node_id=''
printf 'nodes-live: Kitty spawn, send, notify, read and close passed.\n'

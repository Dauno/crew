#!/usr/bin/env bash
# Run with: nix develop -c bash tests/live/pi_live.sh
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
helper=$root/skills/nodes/scripts/nodes.sh
for program in kitty kitten jq pi python3; do
  command -v "$program" >/dev/null 2>&1 || {
    printf 'pi-live: required program not found: %s\n' "$program" >&2
    exit 1
  }
done
pi_version=$(pi --version 2>&1) || {
  printf 'pi-live: could not read the Pi version.\n' >&2
  exit 1
}
[[ $pi_version == 1.4.0 ]] || {
  printf 'pi-live: expected Pi 1.4.0, got %s\n' "$pi_version" >&2
  exit 1
}

tmp=$(mktemp -d "${TMPDIR:-/tmp}/crew-pi-live.XXXXXX")
listen_on="unix:$tmp/kitty.sock"
mkdir -p "$tmp/bin" "$tmp/home" "$tmp/agent" "$tmp/project"
unset CREW_CLI CREW_HOME CREW_NODES_SCRIPT CREW_NODE CREW_PARENT
unset CREW_REPO_ID CREW_ROLE CREW_RUNS CREW_STARTED_AT CREW_TASK
unset CREW_SESSION_ID CREW_INBOX
unset KITTY_WINDOW_ID XDG_DATA_HOME
ln -s "$helper" "$tmp/bin/crew-nodes"
export PATH="$tmp/bin:$PATH"
export HOME="$tmp/home"
export PI_CODING_AGENT_DIR="$tmp/agent"
export PI_OFFLINE=1
export PI_TELEMETRY=0
export CREW_BIN="$root/bin/crew"
export CREW_SKILLS="$root/skills"
export CREW_CORE_INSTRUCTIONS="$root/core/instructions.md"
export CREW_PLUGIN="$root/claude"
export KITTY_LISTEN_ON=$listen_on
export CREW_NODES_TESTING=1
export CREW_NODES_TEST_SEND_WAIT_SECONDS=1

kitty_pid=''
parent_id=''
worker_id=''

cleanup() {
  local status=$?
  trap - EXIT
  if [[ -n $worker_id ]]; then
    env KITTY_LISTEN_ON="$listen_on" KITTY_WINDOW_ID="${parent_id:-1}" \
      CREW_BIN="$CREW_BIN" bash "$helper" close "$worker_id" \
      >/dev/null 2>&1 || true
  fi
  if [[ -n $kitty_pid ]]; then
    kill "$kitty_pid" 2>/dev/null || true
    wait "$kitty_pid" 2>/dev/null || true
  fi
  if [[ $status == 0 ]]; then
    rm -rf -- "$tmp"
  else
    printf 'pi-live: diagnostic files kept under %s\n' "$tmp" >&2
  fi
  exit "$status"
}
trap cleanup EXIT

has_window() {
  local id=$1 listing
  listing=$(kitten @ --to "$listen_on" ls 2>/dev/null) || return 1
  jq -e --arg id "$id" \
    'any(.[]?.tabs[]?.windows[]?; (.id | tostring) == $id)' \
    >/dev/null <<<"$listing"
}

screen() {
  kitten @ --to "$listen_on" get-text --match "id:$1" --ansi
}

wait_screen() {
  local id=$1 marker=$2 content=''
  for _ in {1..150}; do
    has_window "$id" || return 1
    content=$(screen "$id") || return 1
    grep -Fq "$marker" <<<"$content" && return 0
    sleep 0.1
  done
  return 1
}

send_to_window() {
  local id=$1 text=$2
  env -u KITTY_WINDOW_ID KITTY_LISTEN_ON="$listen_on" \
    CREW_CLI=pi CREW_HOME="$HOME/.local/share/crew" \
    CREW_RUNS="$HOME/.local/share/crew/runs" \
    bash "$helper" type "$id" --enter <<<"$text"
}

kitty --config NONE -o allow_remote_control=socket-only \
  --listen-on "$listen_on" --start-as=hidden \
  --directory "$tmp/project" \
  "$root/bin/crew" pi --offline --no-extensions \
  --no-prompt-templates --no-context-files \
  >"$tmp/kitty.log" 2>&1 &
kitty_pid=$!

ready=0
for _ in {1..100}; do
  if listing=$(kitten @ --to "$listen_on" ls 2>/dev/null); then
    parent_id=$(jq -r '.[0].tabs[0].windows[0].id // empty' <<<"$listing")
    if [[ $parent_id =~ ^[1-9][0-9]*$ ]] &&
      wait_screen "$parent_id" '0.0%/0'; then
      ready=1
      break
    fi
  fi
  kill -0 "$kitty_pid" 2>/dev/null || {
    printf 'pi-live: hidden Kitty exited during startup.\n' >&2
    exit 1
  }
  sleep 0.1
done
[[ $ready == 1 ]] || {
  printf 'pi-live: hidden Pi parent did not become ready.\n' >&2
  exit 1
}

parent_multiline=$(cat <<'COMMAND'
!!printf 'PI_PARENT_MULTILINE_ONE\n'
printf 'PI_PARENT_MULTILINE_TWO\n'
COMMAND
)
send_to_window "$parent_id" "$parent_multiline"
wait_screen "$parent_id" 'PI_PARENT_MULTILINE_TWO' || {
  printf 'pi-live: parent did not receive multiline shell input.\n' >&2
  exit 1
}

worker_id=$(env KITTY_WINDOW_ID="$parent_id" \
  KITTY_LISTEN_ON="$listen_on" CREW_BIN="$CREW_BIN" \
  CREW_NODES_TESTING=1 \
  CREW_NODES_TEST_SEND_WAIT_SECONDS=1 \
  bash "$helper" spawn --name pi-worker --cli pi \
    --cwd "$tmp/project" --task pi-live -- --offline \
    --no-extensions --no-prompt-templates --no-context-files)
[[ $worker_id =~ ^[1-9][0-9]*$ ]] || {
  printf 'pi-live: Pi worker spawn returned no window ID.\n' >&2
  exit 1
}
wait_screen "$worker_id" '0.0%/0' || {
  printf 'pi-live: Pi worker did not become ready.\n' >&2
  exit 1
}
session_parent="$HOME/.local/share/crew/runs/pi-live/pi"
for _ in {1..50}; do
  find "$session_parent" -mindepth 1 -maxdepth 1 -type d \
    -name "${worker_id}-*" -print -quit | grep -q . && break
  sleep 0.1
done
find "$session_parent" -mindepth 1 -maxdepth 1 -type d \
  -name "${worker_id}-*" -print -quit | grep -q . || {
  printf 'pi-live: launcher did not create the isolated Pi session directory.\n' >&2
  exit 1
}

worker_multiline=$(cat <<'COMMAND'
!!printf 'PI_WORKER_MULTILINE_ONE\n'
printf 'PI_WORKER_MULTILINE_TWO\n'
COMMAND
)
send_to_window "$worker_id" "$worker_multiline"
wait_screen "$worker_id" 'PI_WORKER_MULTILINE_TWO' || {
  printf 'pi-live: Pi worker did not receive multiline input.\n' >&2
  exit 1
}

send_to_window "$worker_id" '!!sleep 30'
wait_screen "$worker_id" 'sleep 30' || {
  printf 'pi-live: Pi worker did not start the cancellable command.\n' >&2
  exit 1
}
env KITTY_LISTEN_ON="$listen_on" KITTY_WINDOW_ID="$parent_id" \
  CREW_BIN="$CREW_BIN" bash "$helper" interrupt "$worker_id"
wait_screen "$worker_id" '(cancelled)' || {
  printf 'pi-live: Escape did not cancel the Pi worker command.\n' >&2
  exit 1
}

send_to_window "$worker_id" '/quit'
worker_closed=0
for _ in {1..100}; do
  if ! has_window "$worker_id"; then
    worker_closed=1
    worker_id=''
    break
  fi
  sleep 0.1
done
[[ $worker_closed == 1 ]] || {
  printf 'pi-live: Pi worker did not exit through /quit.\n' >&2
  exit 1
}

send_to_window "$parent_id" '/quit'
parent_closed=0
for _ in {1..100}; do
  if ! has_window "$parent_id"; then
    parent_closed=1
    break
  fi
  sleep 0.1
done
[[ $parent_closed == 1 ]] || {
  printf 'pi-live: Pi parent did not exit through /quit.\n' >&2
  exit 1
}

printf '%s\n' \
  'pi-live: Pi 1.4.0 spawn, multiline, Escape and /quit passed.'

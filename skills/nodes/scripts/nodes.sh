#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: nodes.sh COMMAND [ARGS]
  list                         List Kitty windows as JSON lines.
  read ID [screen|all]         Read a window's text.
  send ID [--enter]            Send standard input to a window.
  spawn --name N --cli CLI --cwd DIR [--task T] [-- ARGS...]
                               Open a worker tab and print its window ID.
  interrupt ID                 Send Escape to a worker window.
  close ID                     Close a worker window by exact ID.
EOF
  exit 2
}

die() {
  printf 'nodes: %s\n' "$*" >&2
  exit 1
}

require_connection() {
  [[ -n ${KITTY_LISTEN_ON:-} ]] || die 'KITTY_LISTEN_ON is not set.'
  command -v kitten >/dev/null 2>&1 || die 'kitten is not on PATH.'
}

kitty_remote() {
  kitten @ --to "$KITTY_LISTEN_ON" "$@"
}

kitty_ls() {
  local result error_file error_output
  error_file=$(mktemp "${TMPDIR:-/tmp}/crew-nodes.XXXXXX") ||
    die 'could not create a temporary file for Kitty errors.'
  if ! result=$(kitty_remote ls 2>"$error_file"); then
    error_output=$(<"$error_file")
    rm -f "$error_file"
    if [[ -n $error_output ]]; then
      die "kitten @ ls failed: $error_output"
    fi
    die 'kitten @ ls failed.'
  fi
  rm -f "$error_file"
  if ! jq -e 'type == "array"' >/dev/null <<<"$result"; then
    die 'kitten @ ls returned invalid JSON.'
  fi
  printf '%s\n' "$result"
}

valid_id() {
  [[ $1 =~ ^[1-9][0-9]*$ ]] || die "window ID must be a positive integer: $1"
}

refuse_self() {
  local action=$1 id=$2
  [[ -z ${KITTY_WINDOW_ID:-} || $id != "$KITTY_WINDOW_ID" ]] ||
    die "refusing to $action this window."
}

require_window() {
  local id=$1 listing
  valid_id "$id"
  listing=$(kitty_ls)
  if ! jq -e --arg id "$id" \
    '[.[]?.tabs[]?.windows[]?
      | select((.id | tostring) == $id)] | length == 1' \
    >/dev/null <<<"$listing"; then
    die "no Kitty window has ID $id."
  fi
}

require_worker_window() {
  local id=$1 listing
  valid_id "$id"
  listing=$(kitty_ls)
  if ! jq -e --arg id "$id" \
    'any(.[]?.tabs[]?.windows[]?;
      (.id | tostring) == $id and .user_vars.crew_role == "worker")' \
    >/dev/null <<<"$listing"; then
    if jq -e --arg id "$id" \
      'any(.[]?.tabs[]?.windows[]?; (.id | tostring) == $id)' \
      >/dev/null <<<"$listing"; then
      die "Kitty window $id is not labeled crew_role=worker."
    fi
    die "no Kitty window has ID $id."
  fi
}

list_windows() {
  local listing
  listing=$(kitty_ls)
  jq -c --arg self "${KITTY_WINDOW_ID:-}" '
    .[]?.tabs[]?.windows[]?
    | {
        id,
        title: (.title // ""),
        cwd: (.cwd // ""),
        command: ((.foreground_processes[0].cmdline // .cmdline // [])
          | if type == "array" then join(" ") else tostring end),
        vars: ((.user_vars // {})
          | with_entries(select(.key | startswith("crew_")))),
        self: ((.id | tostring) == $self)
      }
  ' <<<"$listing"
}

read_window() {
  local id=${1:-} extent=${2:-screen}
  [[ $# -ge 1 && $# -le 2 ]] || usage
  [[ $extent == screen || $extent == all ]] ||
    die "extent must be screen or all: $extent"
  require_window "$id"
  kitty_remote get-text --match "id:$id" --extent "$extent"
}

send_text() {
  local id=${1:-} enter=0 text
  [[ $# -ge 1 && $# -le 2 ]] || usage
  [[ ${2:-} != --enter ]] || enter=1
  [[ -z ${2:-} || $enter == 1 ]] || usage
  valid_id "$id"
  refuse_self send "$id"
  require_window "$id"

  text=$(cat; printf '\001')
  text=${text%$'\001'}
  text=${text//$'\r'/}
  if [[ -z $text && $enter == 0 ]]; then
    die 'send reads nonempty text from standard input, or use --enter.'
  fi

  write_text() {
    printf '%s' "$1" | kitty_remote send-text --match "id:$id" --stdin
  }

  if [[ $enter == 1 ]]; then
    if [[ -n $text ]]; then
      write_text "$text"
      sleep 0.5
    fi
    write_text $'\r'
  else
    write_text "$text"
  fi
}

spawn_node() {
  local name='' cli='' cwd='' task=${CREW_TASK:-} reply directory_error
  local -a extra_args=()
  while [[ $# -gt 0 ]]; do
    case $1 in
      --name) [[ $# -ge 2 ]] || usage; name=$2; shift 2 ;;
      --cli) [[ $# -ge 2 ]] || usage; cli=$2; shift 2 ;;
      --cwd) [[ $# -ge 2 ]] || usage; cwd=$2; shift 2 ;;
      --task) [[ $# -ge 2 ]] || usage; task=$2; shift 2 ;;
      --) shift; extra_args=("$@"); break ;;
      *) die "unknown spawn argument: $1" ;;
    esac
  done
  [[ -n $name ]] || die 'spawn requires --name.'
  [[ $cli == claude || $cli == codex ]] ||
    die 'spawn --cli must be claude or codex.'
  if [[ -z $cwd || ! -d $cwd ]]; then
    directory_error="spawn --cwd must be an existing directory: $cwd"
    die "$directory_error"
  fi
  [[ -n ${KITTY_WINDOW_ID:-} ]] ||
    die 'KITTY_WINDOW_ID is not set; spawn must run inside a Kitty window.'
  valid_id "$KITTY_WINDOW_ID"
  [[ -n ${CREW_BIN:-} ]] || die 'CREW_BIN is not set.'
  [[ -x $CREW_BIN ]] || die "CREW_BIN is not executable: $CREW_BIN"

  if ! reply=$(kitty_remote launch --type=tab --keep-focus --copy-env \
    --tab-title "$name · $cli" \
    --cwd "$cwd" \
    --env "CREW_CLI=$cli" \
    --env CREW_ROLE=worker \
    --env "CREW_NODE=$name" \
    --env "CREW_TASK=$task" \
    --env "CREW_PARENT=$KITTY_WINDOW_ID" \
    --var "crew_node=$name" \
    --var "crew_cli=$cli" \
    --var crew_role=worker \
    --var "crew_task=$task" \
    --var "crew_parent=$KITTY_WINDOW_ID" \
    "$CREW_BIN" "$cli" "${extra_args[@]}" 2>&1); then
    die "Kitty could not spawn $cli: $reply"
  fi
  reply=${reply//$'\r'/}
  [[ $reply =~ ^[1-9][0-9]*$ ]] ||
    die "Kitty returned an invalid window ID: $reply"
  printf '%s\n' "$reply"
}

interrupt_window() {
  local id=${1:-}
  [[ $# -eq 1 ]] || usage
  valid_id "$id"
  refuse_self interrupt "$id"
  require_worker_window "$id"
  kitty_remote send-key --match "id:$id" Escape
}

close_window() {
  local id=${1:-}
  [[ $# -eq 1 ]] || usage
  valid_id "$id"
  refuse_self close "$id"
  require_worker_window "$id"
  kitty_remote close-window --match "id:$id"
}

[[ $# -gt 0 ]] || usage
command_name=$1
shift
require_connection

case $command_name in
  list)
    [[ $# -eq 0 ]] || usage
    list_windows
    ;;
  read) read_window "$@" ;;
  send) send_text "$@" ;;
  spawn) spawn_node "$@" ;;
  interrupt) interrupt_window "$@" ;;
  close) close_window "$@" ;;
  *) usage ;;
esac

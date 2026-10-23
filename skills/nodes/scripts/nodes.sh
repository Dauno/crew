#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: nodes.sh COMMAND [ARGS]
  list                         List Kitty windows as JSON lines.
  read ID [screen|all]         Read a window's text.
  send ID                      Publish nonempty standard input to a crew session.
  type ID [--enter]            Type nonempty standard input into a window.
  type ID --enter-only         Type only Return; do not read standard input.
  ack MESSAGE_ID               Acknowledge a message in this session's inbox.
  notify STATUS REPORT         Publish a worker notice to its parent.
  spawn --name N --cli CLI --cwd DIR [--task LABEL] [-- ARGS...]
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

require_runtime_tools() {
  local program
  for program in jq python3; do
    command -v "$program" >/dev/null 2>&1 ||
      die "$program is required but was not found on PATH."
  done
}

send_wait_seconds=60
poll_interval=0.25
if [[ ${CREW_NODES_TESTING:-0} == 1 ]]; then
  send_wait_seconds=${CREW_NODES_TEST_SEND_WAIT_SECONDS:-60}
  [[ $send_wait_seconds =~ ^[0-9]+$ ]] ||
    die 'test send wait must be a nonnegative integer.'
fi

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

mailbox_script() {
  local script_dir
  script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
  printf '%s/mailbox.py\n' "$script_dir"
}

native_target_session() {
  local id=$1 listing user_vars session_id native cli state
  valid_id "$id"
  listing=$(kitty_ls)
  if ! jq -e --arg id "$id" \
    '[.[]?.tabs[]?.windows[]? | select((.id | tostring) == $id)]
      | length == 1' >/dev/null <<<"$listing"; then
    die "no Kitty window has ID $id."
  fi
  user_vars=$(jq -ce --arg id "$id" \
    '[.[]?.tabs[]?.windows[]? | select((.id | tostring) == $id)][0]
      | .user_vars // {}' <<<"$listing") || die "could not read Kitty labels for $id."
  session_id=$(jq -r '.crew_session // empty' <<<"$user_vars")
  native=$(jq -r '.crew_native // empty' <<<"$user_vars")
  cli=$(jq -r '.crew_cli // empty' <<<"$user_vars")
  [[ $session_id =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] ||
    die "Kitty window $id has no crew session identity; restart it with crew."
  [[ $native == 1 ]] ||
    die "Kitty window $id has no native crew receiver."
  if [[ $cli == codex ]]; then
    state=$(python3 "$(mailbox_script)" codex-state --session "$session_id") ||
      die "could not verify Codex routing for Kitty window $id."
    [[ -n $state ]] || die "Codex native receiver is not ready for Kitty window $id."
    if jq -e '.stale == true' >/dev/null <<<"$state"; then
      local reason
      reason=$(jq -r '
        .reason
        | if type == "string" then
            gsub("[\u0000-\u001f\u007f]+"; " ")
          else
            empty
          end
      ' <<<"$state")
      [[ -n $reason ]] || reason="unknown reason"
      die "Codex messaging is stale ($reason); restart the crew session" \
        "before messaging."
    fi
  fi
  printf '%s\n' "$session_id"
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

kitty_send_text() {
  local id=$1 text=$2
  printf '%s' "$text" | kitty_remote send-text --match "id:$id" --stdin
}

input_state() {
  local id=$1 output state
  if ! output=$(kitty_remote get-text \
    --match "id:$id" --ansi 2>/dev/null); then
    printf 'unknown\n'
    return 0
  fi
  if ! state=$(printf '%s' "$output" | python3 -c '
import re
import sys

rows = [[]]
dim = False
foreground = None
text = sys.stdin.read()
i = 0


def apply_sgr(params):
    global dim, foreground
    parts = params.split(";") if params else ["0"]
    index = 0
    while index < len(parts):
        item = parts[index]
        fields = item.split(":")
        try:
            code = int(fields[0] or "0")
        except ValueError:
            index += 1
            continue
        if code == 0:
            dim = False
            foreground = None
        elif code == 2:
            dim = True
        elif code == 22:
            dim = False
        elif code == 39:
            foreground = None
        elif code in (38, 48, 58):
            if code == 38:
                foreground = ("sgr", item)
            if len(fields) == 1 and index + 1 < len(parts):
                mode = parts[index + 1]
                index += 4 if mode == "2" else 2 if mode == "5" else 1
        elif 30 <= code <= 37 or 90 <= code <= 97:
            foreground = ("ansi", code)
        index += 1


while i < len(text):
    char = text[i]
    if char == "\x1b":
        if text.startswith("\x1b]", i):
            bell = text.find("\x07", i + 2)
            string_end = text.find("\x1b\\", i + 2)
            ends = [end for end in (bell, string_end) if end >= 0]
            if ends:
                end = min(ends)
                i = end + (1 if end == bell else 2)
            else:
                i = len(text)
            continue
        if text.startswith("\x1b[", i):
            end = i + 2
            while end < len(text) and not ("@" <= text[end] <= "~"):
                end += 1
            if end < len(text):
                if text[end] == "m":
                    apply_sgr(text[i + 2:end])
                i = end + 1
                continue
        i += 1
        continue
    if char == "\n":
        rows.append([])
    elif char != "\r":
        rows[-1].append((char, dim, foreground))
    i += 1

def plain(row):
    return "".join(char for char, _, _ in row)


def border(row):
    value = plain(row)
    return (len(value) > 1 and len(set(value)) == 1
            and value[0] in "─━═-")


pi_context_pattern = (
    r"(?:^|\s)(?:\d+(?:\.\d+)?%|\?)/"
    r"\d+(?:\.\d+)?[kM]?(?:\s|$)"
)


def pi_frame_bounds():
    visible_rows = [index for index, row in enumerate(rows)
                    if plain(row).strip()]
    if len(visible_rows) < 4:
        return None
    for footer_rows in (3, 2):
        lower_position = len(visible_rows) - footer_rows - 1
        if lower_position < 0:
            continue
        lower_index = visible_rows[lower_position]
        lower_border = plain(rows[lower_index])
        if not border(rows[lower_index]):
            continue
        footer_indexes = visible_rows[lower_position + 1:]
        if border(rows[footer_indexes[0]]):
            continue
        top_index = None
        for index in range(lower_index - 1, -1, -1):
            upper_border = plain(rows[index])
            matching_border = upper_border == lower_border
            working_border = (
                lower_border[0] == "─"
                and len(upper_border) == len(lower_border)
                and re.fullmatch(r"── [⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏] Working ─+",
                                 upper_border) is not None
            )
            if matching_border or working_border:
                top_index = index
                break
        if top_index is None or top_index + 1 >= lower_index:
            continue
        prompt_inside = any(
            re.match(r"^\s*[❯›](?:\s|$)", plain(row))
            for row in rows[top_index + 1:lower_index]
        )
        if prompt_inside:
            continue
        return top_index, lower_index, footer_indexes
    return None


def pi_state():
    frame = pi_frame_bounds()
    if frame is None:
        return None
    top_index, lower_index, footer_indexes = frame

    editor_rows = rows[top_index + 1:lower_index]
    if any(not char.isspace()
           for row in editor_rows for char, _, _ in row):
        return "busy"

    stats = plain(rows[footer_indexes[1]]).strip()
    if not re.search(pi_context_pattern, stats):
        return "unknown"
    return "clear"


pi_input = pi_state()
if pi_input is not None:
    print(pi_input)
    raise SystemExit

candidates = []
for row_index, row in enumerate(rows):
    for char_index, (char, _, _) in enumerate(row):
        if char in ("❯", "›") and all(
            prior.isspace() for prior, _, _ in row[:char_index]
        ):
            candidates.append((row_index, char_index))

if not candidates:
    print("unknown")
    raise SystemExit

row_index, char_index = max(candidates)
row = rows[row_index]
marker_foreground = row[char_index][2]
marker = row[char_index][0]

pi_frame_lines = sum(
    re.fullmatch(r"─+|─── [↑↓] \d+ more ─*|── [⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏] Working ─+",
                 plain(following).strip())
    is not None
    for following in rows[row_index + 1:]
)
pi_tail = [plain(following).strip() for following in rows[row_index + 1:]
           if plain(following).strip()]
# Require Pi usage counters, cost, or its default auto-compaction marker.
pi_footer = any(
    len(pi_tail) >= footer_size + 1
    and re.match(r"^(?:/|~(?:/|$))", pi_tail[-footer_size])
    and re.search(pi_context_pattern, pi_tail[-footer_size + 1])
    and (
        re.match(r"^(?:[↑↓RW]\d|\$\d)", pi_tail[-footer_size + 1])
        or re.match(pi_context_pattern + r"\(auto\)(?:\s|$)",
                    pi_tail[-footer_size + 1])
    )
    for footer_size in (2, 3)
)
if pi_frame_lines >= 2 or (pi_frame_lines and pi_footer):
    print("unknown")
    raise SystemExit

for char, is_dim, color in row[char_index + 1:]:
    if not char.isspace() and not is_dim:
        if color == marker_foreground:
            print("busy")
        else:
            print("unknown")
        raise SystemExit

if marker == "›":
    # Codex draws its footer below the prompt. Only the prompt row describes
    # the draft; scanning footer text makes an empty prompt look occupied.
    if any(not char.isspace() for char, _, _ in row[char_index + 1:]):
        print("clear")
    else:
        # A blank composer without a suggestion is ambiguous, so wait.
        print("unknown")
    raise SystemExit

border = set("─━═-")
for following in rows[row_index + 1:]:
    visible = [(char, is_dim, color) for char, is_dim, color in following
               if not char.isspace()]
    if not visible:
        continue
    if all(char in border for char, _, _ in visible):
        break
    if any(not is_dim and color == marker_foreground
           for _, is_dim, color in visible):
        print("busy")
        raise SystemExit

print("clear")
') ; then
    printf 'unknown\n'
    return 0
  fi
  case $state in
    clear|busy|unknown) printf '%s\n' "$state" ;;
    *) printf 'unknown\n' ;;
  esac
}

wait_for_clear() {
  local id=$1 timeout_seconds=$2 started=$SECONDS state
  while :; do
    state=$(input_state "$id")
    [[ $state == clear ]] && return 0
    (( SECONDS - started < timeout_seconds )) || return 1
    sleep "$poll_interval"
  done
}

send_and_enter() {
  local id=$1 text=$2 timeout_seconds=$3
  local started=$SECONDS remaining state
  while :; do
    remaining=$((timeout_seconds - SECONDS + started))
    (( remaining >= 0 )) || return 1
    wait_for_clear "$id" "$remaining" || return 1
    state=$(input_state "$id")
    [[ $state == clear ]] && break
    (( SECONDS - started < timeout_seconds )) || return 1
  done
  kitty_send_text "$id" "$text" || return 1
  sleep 0.5
  kitty_send_text "$id" $'\r'
}

send_native() {
  local id=${1:-} destination message_id script
  if [[ $# -eq 2 && ( $2 == --enter || $2 == --enter-only ) ]]; then
    die 'send no longer types into a terminal; use type ID [--enter] for explicit keyboard input.'
  fi
  [[ $# -eq 1 ]] || usage
  valid_id "$id"
  refuse_self send "$id"
  destination=$(native_target_session "$id")
  script=$(mailbox_script)
  if ! message_id=$(python3 "$script" publish --to "$destination"); then
    die "could not store message for Kitty window $id."
  fi
  printf 'stored as pending; recipient must acknowledge: %s\n' "$message_id"
}

ack_message() {
  local message_id=${1:-} script
  [[ $# -eq 1 ]] || usage
  script=$(mailbox_script)
  python3 "$script" ack "$message_id"
}

mailbox_internal() {
  local script
  script=$(mailbox_script)
  python3 "$script" "$@"
}

claude_hook() {
  local script_dir
  script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
  python3 "$script_dir/claude_hook.py"
}

type_text() {
  local id=${1:-} enter=0 enter_only=0 text
  [[ $# -ge 1 && $# -le 2 ]] || usage
  case ${2:-} in
    '') ;;
    --enter) enter=1 ;;
    --enter-only) enter_only=1 ;;
    *) usage ;;
  esac
  valid_id "$id"
  refuse_self type "$id"
  require_window "$id"

  if [[ $enter_only == 1 ]]; then
    kitty_send_text "$id" $'\r'
    return
  fi

  text=$(cat; printf '\001')
  text=${text%$'\001'}
  text=${text//$'\r'/}
  if [[ -z $text ]]; then
    if [[ $enter == 1 ]]; then
      die 'type --enter requires nonempty input; use --enter-only for Return.'
    fi
    die 'type requires nonempty standard input.'
  fi

  if [[ $enter == 1 ]]; then
    if ! send_and_enter "$id" "$text" "$send_wait_seconds"; then
      die "input stayed occupied or unrecognized after ${send_wait_seconds}s."
    fi
  else
    kitty_send_text "$id" "$text"
  fi
}

record_metrics() {
  local status=$1 report=$2 script_dir metrics_script summary
  script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
  metrics_script=$script_dir/metrics.sh
  if [[ -f $metrics_script ]] &&
    summary=$(bash "$metrics_script" record --status "$status" \
      --report "$report" 2>/dev/null) &&
    [[ -n $summary && $summary != *$'\n'* ]]; then
    printf '%s\n' "$summary"
  else
    printf 'metrics unavailable\n'
  fi
}

notify_parent() {
  local status=${1:-} report=${2:-} parent message destination script
  [[ $# -eq 2 ]] || usage
  [[ -n $status ]] || die 'notify STATUS must not be empty.'
  [[ -n ${CREW_TASK:-} ]] || die 'notify requires CREW_TASK.'
  [[ -n ${CREW_NODE:-} ]] || die 'notify requires CREW_NODE.'
  [[ -n ${CREW_PARENT:-} ]] || die 'notify requires CREW_PARENT.'
  [[ -n $report && -f $report ]] ||
    die "notify REPORT must be an existing file: $report"

  parent=$CREW_PARENT
  valid_id "$parent"
  refuse_self notify "$parent"
  metrics=$(record_metrics "$status" "$report")
  message="$CREW_TASK/$CREW_NODE: $status. Report: $report. Metrics: $metrics"
  destination=$(native_target_session "$parent")
  script=$(mailbox_script)
  if ! printf '%s' "$message" | python3 "$script" publish --to "$destination" \
    >/dev/null; then
    die "could not store notice for parent Kitty window $parent."
  fi
}

spawn_node() {
  local name='' cli='' cwd='' task=${CREW_TASK:-} reply directory_error
  local started_at session_id crew_home inbox
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
  [[ $cli == claude || $cli == codex || $cli == pi ]] ||
    die 'spawn --cli must be claude, codex or pi.'
  if [[ -z $cwd || ! -d $cwd ]]; then
    directory_error="spawn --cwd must be an existing directory: $cwd"
    die "$directory_error"
  fi
  if [[ $cli == pi ]]; then
    local pi_task=${task:-_untasked}
    [[ -n $pi_task && $pi_task != . && $pi_task != .. &&
      $pi_task != */* && $pi_task != *$'\n'* &&
      $pi_task != *$'\r'* ]] ||
      die 'invalid task path component for Pi worker.'
  fi
  [[ -n ${KITTY_WINDOW_ID:-} ]] ||
    die 'KITTY_WINDOW_ID is not set; spawn must run inside a Kitty window.'
  valid_id "$KITTY_WINDOW_ID"
  [[ -n ${CREW_BIN:-} ]] || die 'CREW_BIN is not set.'
  [[ -x $CREW_BIN ]] || die "CREW_BIN is not executable: $CREW_BIN"
  started_at=$(date +%s)
  session_id=$(python3 -c 'import uuid; print(uuid.uuid4())') ||
    die 'could not create worker session identity.'
  crew_home=${CREW_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/crew}
  inbox=$crew_home/mailboxes/$session_id
  local script
  script=$(mailbox_script)
  if ! CREW_HOME=$crew_home CREW_SESSION_ID=$session_id \
    CREW_INBOX=$inbox python3 "$script" reserve \
      --cli "$cli" --node "$name" --task "$task" \
      --parent "$KITTY_WINDOW_ID" --started-at "$started_at" \
      >/dev/null; then
    die 'could not reserve worker session identity.'
  fi

  if ! reply=$(kitty_remote launch --type=tab --keep-focus --copy-env \
    --tab-title "$name · $cli" \
    --cwd "$cwd" \
    --env "CREW_CLI=$cli" \
    --env "CREW_HOME=$crew_home" \
    --env "CREW_SESSION_ID=$session_id" \
    --env "CREW_INBOX=$inbox" \
    --env CREW_SESSION_PREALLOCATED=1 \
    --env CREW_ROLE=worker \
    --env "CREW_NODE=$name" \
    --env "CREW_TASK=$task" \
    --env "CREW_PARENT=$KITTY_WINDOW_ID" \
    --env "CREW_STARTED_AT=$started_at" \
    --var "crew_node=$name" \
    --var "crew_cli=$cli" \
    --var "crew_session=$session_id" \
    --var crew_native=0 \
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
require_runtime_tools
command_name=$1
shift
case $command_name in
  ack) ack_message "$@" ;;
  _mailbox) mailbox_internal "$@" ;;
  claude-hook) [[ $# -eq 0 ]] || usage; claude_hook ;;
  *)
    require_connection
    case $command_name in
      list)
        [[ $# -eq 0 ]] || usage
        list_windows
        ;;
      read) read_window "$@" ;;
      send) send_native "$@" ;;
      type) type_text "$@" ;;
      notify) notify_parent "$@" ;;
      spawn) spawn_node "$@" ;;
      interrupt) interrupt_window "$@" ;;
      close) close_window "$@" ;;
      *) usage ;;
    esac
    ;;
esac

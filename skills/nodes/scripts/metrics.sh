#!/usr/bin/env bash
# Read only this worker's CLI transcript and append content-free metrics.
set -euo pipefail

fail() {
    printf 'metrics unavailable\n'
    printf 'crew metrics: %s\n' "$1" >&2
    exit 1
}

[[ ${1:-} == record ]] || fail 'expected record --status S --report R'
shift
status='' report=''
while (($#)); do
    case "$1" in
        --status|--report)
            (($# >= 2)) || fail 'missing option value'
            case "$1" in
                --status) status=$2 ;;
                --report) report=$2 ;;
            esac
            shift 2
            ;;
        *) fail 'unknown option' ;;
    esac
done
[[ -n $status && -n $report ]] || fail 'status and report are required'
command -v jq >/dev/null 2>&1 || fail 'jq is required'

cli=${CREW_CLI:-}
case "$cli" in
    claude)
        session=${CLAUDE_CODE_SESSION_ID:-}
        log_root=$HOME/.claude/projects
        pattern=$session.jsonl
        ;;
    codex)
        session=${CODEX_THREAD_ID:-}
        log_root=$HOME/.codex/sessions
        pattern="rollout-*-$session.jsonl"
        ;;
    *) fail 'CREW_CLI must be claude or codex' ;;
esac
# Never allow path traversal or glob metacharacters in a session selector.
[[ -n $session && $session != *[!a-zA-Z0-9_-]* ]] ||
    fail 'missing or invalid session ID'
[[ -d $log_root ]] || fail 'CLI log directory is missing'
log=
while IFS= read -r -d '' candidate; do
    [[ -z $log ]] || fail 'session log is ambiguous'
    log=$candidate
done < <(find "$log_root" -type f -name "$pattern" -print0 2>/dev/null)
[[ -n $log && -r $log ]] || fail 'session log is missing or unreadable'

crew_home=${CREW_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/crew}
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
price_file=$script_dir/../prices.json
[[ ! -f $crew_home/prices.json ]] || price_file=$crew_home/prices.json
# Bad or missing rates mean unknown cost, not invented prices.
prices=$(jq -cse '
    if length == 1 and (.[0] | type) == "object" then .[0] else {} end
    ' "$price_file" 2>/dev/null) || prices='{}'
now=$(date +%s)
time=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Parse JSON lines individually. A CLI can still be writing its final line.
# Retain only numeric usage, model IDs, versions, session IDs and timestamps.
record=$(jq -Rnc \
    --arg cli "$cli" --arg session "$session" \
    --arg time "$time" --argjson now "$now" \
    --arg started "${CREW_STARTED_AT:-}" \
    --arg task "${CREW_TASK:-}" --arg node "${CREW_NODE:-}" \
    --arg parent "${CREW_PARENT:-}" --arg repo "${CREW_REPO_ID:-}" \
    --arg status "$status" --arg report "$report" \
    --argjson prices "$prices" '
    def num: if type == "number" and . >= 0 then . else 0 end;
    def nullable_num: if type == "number" and . >= 0 then . else null end;
    def text: if type == "string" then . else null end;
    def epoch:
        if type == "string" then
            try (. as $stamp
                | (sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601)
                + ((try ($stamp | capture("\\.(?<digits>[0-9]+)Z$").digits
                         | "0." + . | tonumber) catch 0) // 0)) catch null
        else null end;
    def zero: {input:0, cache_read:0, cache_write:0, output:0, reasoning:0};
    def add($a; $b):
        reduce (zero | keys[]) as $k (zero; .[$k] = $a[$k] + $b[$k]);
    def total($usage): reduce ($usage[]?) as $u (zero; add(.; $u));
    def claude_tokens:
        {input: ((.inputTokens | num) + (.cacheReadInputTokens | num)
                 + (.cacheCreationInputTokens | num)),
         cache_read: (.cacheReadInputTokens | num),
         cache_write: (.cacheCreationInputTokens | num),
         output: (.outputTokens | num), reasoning: (.thinkingTokens | num)};
    def message_tokens:
        {input: ((.input_tokens | num) + (.cache_read_input_tokens | num)
                 + (.cache_creation_input_tokens | num)),
         cache_read: (.cache_read_input_tokens | num),
         cache_write: (.cache_creation_input_tokens | num),
         output: (.output_tokens | num),
         reasoning: (.output_tokens_details.thinking_tokens | num)};
    def codex_tokens:
        {input: (.input_tokens | num),
         cache_read: (.cached_input_tokens | num),
         cache_write: (.cache_write_input_tokens | num),
         output: (.output_tokens | num),
         reasoning: (.reasoning_output_tokens | num)};
    def by_model($responses):
        reduce ($responses[]?) as $r ({};
            .[$r.model] = add((.[$r.model] // zero); $r.tokens));
    def ms: nullable_num | if . == null then null else . / 1000 end;
    def priced($usage):
        [ $usage | to_entries[] | .key as $m | .value as $u
          | $prices[$m] as $p
          | if ($p | type) != "object" then null
            elif (["input", "cache_read", "cache_write", "output"]
                  | all(. as $k | ($p[$k] | type) == "number"
                                 and $p[$k] >= 0)) | not then null
            elif $u.input < ($u.cache_read + $u.cache_write) then null
            else (($u.input - $u.cache_read - $u.cache_write) * $p.input
                  + $u.cache_read * $p.cache_read
                  + $u.cache_write * $p.cache_write
                  + $u.output * $p.output) / 1000000 end ]
        | if length == 0 or any(. == null) then null else add end;

    reduce (inputs | fromjson? | select(type == "object")) as $r
        ({cs:null, responses:{}, cumulative:null, model:"unknown",
          models:{}, first:null, last:null, version:null,
          valid:false, index:0};
         .index += 1
         | ($r.timestamp | epoch) as $stamp
         | if $stamp != null then
               .first = ([.first, $stamp] | map(select(. != null)) | min)
               | .last = ([.last, $stamp] | map(select(. != null)) | max)
           else . end
         | if $cli == "claude" then
               if ($r.sessionId // $r.session_id // $session) != $session
                  or $r.isSidechain == true then .
               else
                   .version = (($r.version | text) // .version)
                   | if $r.type == "cost-state" then
                         .valid = true
                         | .cs = {
                             cost: ($r.totalCostUSD | nullable_num),
                             duration: ($r.totalDuration //
                                 $r.totalDurationMs | ms),
                             api: ($r.totalAPIDuration //
                                 $r.totalAPIDurationMs | ms),
                             api_without_retries:
                                 ($r.totalAPIDurationWithoutRetries | ms),
                             tool: ($r.totalToolDuration | ms),
                             usage: (($r.modelUsage // {}) | with_entries(
                                 .value |= claude_tokens))}
                     elif $r.type == "assistant"
                          and ($r.message.usage | type) == "object" then
                         .valid = true
                         | ($r.message.id //
                            ("line:" + (.index | tostring))) as $id
                         | .responses[$id] = {
                             model: ($r.message.model // "unknown"),
                             tokens: ($r.message.usage | message_tokens)}
                     else . end
               end
           else
               if $r.type == "session_meta" then
                   if $r.payload.id != $session then error("session mismatch")
                   else
                       .version = ($r.payload.cli_version | text)
                       | ($r.payload.timestamp | epoch) as $start
                       | if $start != null then .first = $start else . end
                   end
               elif $r.type == "turn_context" then
                   .model = ($r.payload.model // "unknown")
                   | .models[.model] = true
               elif $r.type == "token_usage_record"
                    and ($r.payload.thread_id // $r.payload.session_id //
                         $session) == $session
                    and ($r.payload.usage | type) == "object" then
                   .valid = true
                   | ($r.payload.response_id //
                      ("line:" + (.index | tostring))) as $id
                   | .responses[$id] = {model:.model,
                       tokens: ($r.payload.usage | codex_tokens)}
               elif $r.type == "event_msg"
                    and $r.payload.type == "token_count"
                    and ($r.payload.info.total_token_usage | type)
                        == "object" then
                   .valid = true
                   | .cumulative = ($r.payload.info.total_token_usage
                                    | codex_tokens)
               else . end
           end)
    | if .valid | not then error("no session usage") else . end
    | (if $cli == "claude" then
           if (.cs.usage // {} | length) > 0 then
               {usage:.cs.usage, source:"cost_state"}
           else {usage:by_model(.responses), source:"message_usage"} end
       elif (.responses | length) > 0 then
           {usage:by_model(.responses), source:"token_usage_record"}
       else
           # Cumulative counters cannot attribute usage across model changes.
           {usage:{(if (.models | length) == 1 then .model
                    else "unknown" end): .cumulative}, source:"token_count"}
       end) as $data
    | (total($data.usage)) as $tokens
    | (if $cli == "claude" then .cs.cost
       else priced($data.usage) end) as $cost
    | {time:$time, task:$task, node:$node, parent:$parent, repo_id:$repo,
       cli:$cli, cli_version:.version, session_id:$session,
       models:(($data.usage | keys) + (.models | keys) | unique),
       status:$status, report:$report,
       wall_seconds:(try ($started | tonumber) catch null
           | if . == null or . < 0 then null else [0, $now - .] | max end),
       session_seconds:(.cs.duration //
           (if .first != null and .last != null then
                ((.last - .first) * 1000 | round) / 1000 else null end)),
       api_seconds:.cs.api,
       api_without_retries_seconds:.cs.api_without_retries,
       tool_seconds:.cs.tool, tokens:$tokens, model_usage:$data.usage,
       cost_usd:$cost,
       cost_source:(if $cost == null then "unavailable"
                    elif $cli == "claude" then "claude"
                    else "price_table" end),
       usage_source:$data.source}
    ' < "$log" 2>/dev/null) || fail 'could not extract session usage'

summary=$(printf '%s\n' "$record" | jq -r '
    def compact:
        if . >= 1000000 then ((. / 100000 | round) / 10 | tostring) + "M"
        elif . >= 1000 then ((. / 100 | round) / 10 | tostring) + "k"
        else tostring end;
    ((.wall_seconds // .session_seconds) as $s
      | if $s == null then "?" else ($s | round | tostring) + "s" end)
    + " · " + (.tokens.input | compact) + " in ("
    + (.tokens.cache_read | compact) + " cached) / "
    + (.tokens.output | compact) + " out · "
    + (if .cost_usd == null then "cost unavailable"
       else (.cost_usd * 100 | round) as $c
         | "$" + ($c / 100 | floor | tostring) + "."
           + ("0" + ($c % 100 | tostring) | .[-2:]) end)
    ') || fail 'could not summarize session usage'
# One compact append limits interleaving between workers without Linux locks.
# Do not change the permissions of existing human-owned directories or files.
(
    umask 077
    mkdir -p "$crew_home"
    printf '%s\n' "$record" >> "$crew_home/metrics.jsonl"
) || fail 'could not append metrics'
printf '%s\n' "$summary"

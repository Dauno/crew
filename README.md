# crew

One shared core for Claude Code, Codex and Pi on any machine with Nix. Same
instructions, skills and private memory in every CLI. Worker nodes in Kitty
tabs coordinate work across repositories.

## Requirements

Use Nix with flakes enabled, Kitty for worker tabs and a configured Claude
Code, Codex or Pi CLI.

## Install

```sh
nix profile add github:Dauno/crew
```

## Update

```sh
nix profile upgrade --refresh crew
```

This installs the latest commit on `main`. Open a new `crew` session to use
it.

## Use

Run any supported CLI in the current repository:

```sh
crew claude
crew codex
crew pi
```

Outside a remote-controllable Kitty session, `crew` opens its own Kitty
window. Ask the agent to open workers and describe their tasks. The agent uses
the `nodes` skill and helper to open Claude Code, Codex or Pi worker nodes as
Kitty tabs. Workers send completion notices to their parent through mailboxes.

Helper reference:

```sh
crew-nodes spawn \
  --name reviewer --cli claude --cwd "$PWD" --task review [-- ARGS...]
```

`--task` takes a short label, such as `review`. It identifies the task in
`$CREW_RUNS/<task>/` and the worker's `CREW_TASK` variable. Arguments after
`--` pass unchanged to the CLI. Pass them only when the human requests a model
or option; otherwise, workers use their CLI's default model.

## Native messages

Each `crew` session has a UUID and a private mailbox under
`$CREW_HOME/mailboxes/`. `crew-nodes send ID` uses the Kitty window ID to find
that session and atomically stores a message. Success means stored, not read.
Messages may contain up to 8 KiB of UTF-8 text. Send a report path for longer
content. The receiver delivers through its CLI integration, never by typing
into the editor.

After reading a message, the recipient runs `crew-nodes ack MESSAGE_ID`.
Only this explicit acknowledgement moves the message to `received`.
Acknowledgement does not report task completion or promise exactly-once work.
`notify STATUS REPORT` uses the same mailbox and keeps its current notice text
and one metrics record per call.

Use `crew-nodes type ID [--enter]` only for deliberate terminal input.
Native task messages never fall back to `type`. Pending messages stay with
closed sessions; crew does not migrate them to a new session automatically.
Codex messaging stops if its TUI switches to another root conversation.
Restart the crew session before sending to that conversation.

## Memory and permissions

Memory stays on each machine. By default, it lives at
`~/.local/share/crew/memory`; it follows `$XDG_DATA_HOME` when set. Memory has
global, machine and repository scopes. The coordinator writes entries;
workers propose them. The human's current request takes precedence.

Claude Code's human session keeps confirmation prompts; a settings rule
permits the nodes helper. The human's Codex session runs with
`--sandbox danger-full-access`. Pi keeps its usual configuration. Workers
always run without tool confirmation prompts. Pi 1.3.0 needs no permission
flag. Pi can ask whether to trust project resources under `.pi`.
The human answers project trust dialogs.

CLI provider settings, including Vertex URLs, stay in the CLI's own
configuration. crew never passes model, provider or credential settings. Its
default instructions forbid pushing, opening PRs, merging, or acting on
production or shared environments without a human request.

## Node metrics

Worker notices include time, tokens and cost. Each notice appends a JSON line
at `$CREW_HOME/metrics.jsonl`, normally `~/.local/share/crew/metrics.jsonl`.
The collector reads only that worker's CLI session, never other workers.

Records contain `time`, `task`, `node`, `parent`, `repo_id`, `cli`,
`cli_version`, `session_id`, `models`, `status` and `report`.
`wall_seconds` measures elapsed time since launch. `session_seconds`,
`api_seconds`, `api_without_retries_seconds` and `tool_seconds` describe the
CLI session when available. Unknown durations use `null`.

`tokens` holds `input`, `cache_read`, `cache_write`, `output` and `reasoning`.
Input includes both cache counts; reasoning already belongs to output.
`model_usage` holds the same counters per model. `usage_source` identifies
`cost_state`, `message_usage`, `token_usage_record` or `token_count`.
Repeated response IDs count once. Cumulative Codex counters act as a
fallback, not additional usage. A cumulative session with model changes
uses `unknown` attribution rather than guessing each model's share.

`cost_usd` comes from Claude Code's own total, a Codex price estimate, or
Pi's reported estimate. `cost_source` identifies `claude`, `price_table`,
`pi` or `unavailable`. Unknown costs use `null`, never zero. Pi reports
estimated costs. Subscription limits and actual charges can differ.

The shipped `skills/nodes/prices.json` stays empty until prices are verified.
Override it per machine with `$CREW_HOME/prices.json`. Both files map exact
model IDs to `input`, `cache_read`, `cache_write` and `output` rates in USD
per million tokens. All four rates must be nonnegative numbers.
For example, this format uses synthetic rates, not actual model prices:

```json
{"example-model":{"input":2,"cache_read":0.2,"cache_write":3,"output":8}}
```

Input rates apply only to uncached tokens. Output rates include reasoning.
An override replaces the shipped table. Missing or invalid rates leave
cost unknown. Metrics contain identifiers and numbers, never session content.
A collection failure never blocks the worker's notice.

Compare single-model worker records without counting unknown costs as zero:

```sh
jq -s '
  map(select(.models | length == 1)) | group_by(.models[0])
  | map({model: .[0].models[0], runs: length,
      wall_seconds: (map(.wall_seconds // empty) | add),
      input: (map(.tokens.input) | add),
      output: (map(.tokens.output) | add),
      priced_runs: (map(select(.cost_usd != null)) | length),
      cost_usd: (map(.cost_usd // empty) | add)})
' "${CREW_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/crew}/metrics.jsonl"
```

## Skills

The `plan`, `implement`, `review`, `git` and `handoff` skills guide planning,
changes, reviews, delivery and work transfers. The `nodes`, `memory` and
`onboard` skills support collaboration and repository work. The role skills
draw on [ponytail](https://github.com/DietrichGebert/ponytail) and
[mattpocock/skills](https://github.com/mattpocock/skills), both MIT.

## Develop

Run a local checkout with any supported CLI:

```sh
nix run ~/Projects/crew -- claude
nix run ~/Projects/crew -- codex
nix run ~/Projects/crew -- pi
nix flake check
nix develop -c bash tests/live/nodes_live.sh
nix develop -c bash tests/live/messaging_live.sh
```

The messaging smoke starts Claude with Haiku and the configured provider.
It can incur model usage. It never starts a paid Codex or Pi turn.
The default development shell supplies the tools for live tests. They require
a desktop Kitty session. Scripts in `tests/live/` start
their own hidden Kitty and do not use the human's windows.

See `AGENTS.md` and the skills for contracts and details.

# crew

crew gives Claude Code and Codex shared instructions, skills, Kitty workers
and private machine-local memory. It helps agents carry decisions and lessons
across sessions and repositories.

## Requirements

Use Nix with flakes enabled, SSH access to this private repository, Kitty for
worker tabs and a configured Claude Code or Codex CLI.

## Install

```sh
nix profile add git+ssh://git@github.com/Dauno/crew
```

## Update

```sh
nix profile upgrade --refresh crew
```

This installs the latest commit on `main`. Open a new `crew` session to use
it.

## Use

Run either CLI in the current repository:

```sh
crew claude
crew codex
```

Outside a remote-controllable Kitty session, `crew` opens its own Kitty
window. Ask the agent to open workers and describe their tasks. The agent uses
the `nodes` skill and helper to open Claude Code or Codex workers as Kitty
tabs. Workers send completion notices to their parent.

Helper reference:

```sh
crew-nodes spawn \
  --name reviewer --cli claude --cwd "$PWD" --task review [-- ARGS...]
```

`--task` takes a short label, such as `review`. It identifies the task in
`$CREW_RUNS/<task>/` and the worker's `CREW_TASK` variable. Arguments after
`--` pass unchanged to the CLI. Pass them only when the human requests a model
or option; otherwise, workers use their CLI's default model.

## Memory and permissions

Memory stays on each machine. By default, it lives at
`~/.local/share/crew/memory`; it follows `$XDG_DATA_HOME` when set. Memory has
global, machine and repository scopes. The coordinator writes entries;
workers propose them. The human's current request takes precedence.

Claude Code's human session keeps confirmation prompts; a settings rule
permits the nodes helper. The human's Codex session runs with
`--sandbox danger-full-access`. Workers run without confirmation prompts by
default. Set `CREW_UNATTENDED_WORKERS=0` before launching crew to require
prompts for workers. The human's session keeps its usual permissions.

CLI provider settings, including Vertex URLs, stay in the CLI's own
configuration. crew never passes model, provider or credential settings. Its
default instructions forbid pushing, opening PRs, merging, or acting on
production or shared environments without a human request.

## Worker metrics

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

`cost_usd` comes from Claude Code's own total or a Codex price estimate.
`cost_source` identifies `claude`, `price_table` or `unavailable`.
Unknown costs use `null`, never zero. Prices depend on the provider;
subscription billing may differ from an API estimate.

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

## Develop

Run a local checkout with either CLI:

```sh
nix run ~/Projects/crew -- claude
nix run ~/Projects/crew -- codex
nix flake check
nix develop -c bash tests/live/nodes_live.sh
```

The default development shell supplies the tools for live tests. They require
a desktop Kitty session. Scripts in `tests/live/` start
their own hidden Kitty and do not use the human's windows.

See `AGENTS.md` and the skills for contracts and details.

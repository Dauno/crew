# AGENTS.md

## Mission

crew gives Claude Code and Codex one shared core on any machine with Nix.
The core holds base instructions, skills, memory and Kitty messaging.
Whichever CLI the human starts, the agent has the same abilities.
Agents in separate Kitty tabs coordinate work across repositories.

Keep crew small. Add machinery only when real use shows that it helps.
crew is private. It runs on this Linux host and on a macOS work machine.

## Repository structure

- `flake.nix`: inputs, the `crew` package and checks.
  Systems: x86_64-linux, aarch64-linux and aarch64-darwin.
- `bin/crew`: the launcher. `crew claude` or `crew codex` starts that CLI.
- `core/instructions.md`: base instructions that both CLIs receive.
- `claude/`: the Claude Code adapter, a plugin that carries the skills.
- `skills/nodes/`: Kitty messaging between agents, with `scripts/nodes.sh`.
- `skills/memory/`: how to read and record decisions and lessons.
- `skills/onboard/`: how to learn a repository on the first visit.
- `tests/`: unit tests that `nix flake check` runs.
- `tests/live/`: scripts that need a desktop Kitty session.

## Contracts

These names connect the parts. Change them only with the coordinator.

### Environment

The launcher exports these variables to the CLI and its tools:

| Variable | Value |
| --- | --- |
| `CREW_HOME` | `${XDG_DATA_HOME:-$HOME/.local/share}/crew` |
| `CREW_MEMORY` | `$CREW_HOME/memory` |
| `CREW_RUNS` | `$CREW_HOME/runs` |
| `CREW_SKILLS` | the store path of `skills/` |
| `CREW_BIN` | the store path of the `crew` executable |
| `CREW_CLI` | `claude` or `codex` |
| `CREW_ROLE` | `worker` in spawned nodes; unset in the human's session |
| `CREW_NODE` | the node name, in workers |
| `CREW_TASK` | the task label, in workers |
| `CREW_PARENT` | the Kitty window ID of the spawning node, in workers |
| `CREW_REPO_ID` | the repository ID; empty outside Git |

`CREW_REPO_ID` comes from the `origin` URL as `host/owner/repo`.
It is lowercase, without `.git`, a user or credentials.
Without `origin`, it is `local/<directory name>`.
Memory directory names replace each `/` with `_`.

### Instructions

The launcher appends a `## This session` block to `core/instructions.md`.
The block lists the CLI, role, node, task, parent window and repository ID.
It also lists the memory, runs and skills paths and the nodes helper.
Instructions refer to these values instead of hard-coded paths.

### Memory

Memory lives outside Git, on each machine:

    $CREW_MEMORY/
    ├── index.md
    ├── global/index.md
    ├── machine/index.md
    ├── repos/index.md
    └── repos/<repository ID with _>/index.md

Each entry is a Markdown file with YAML frontmatter:

```yaml
---
type: Decision # Decision, Lesson, Observation or Command
date: 2026-10-18
scope: repo:github.com/acme/payments # global, machine or repo:<ID>
source: 'Human on 2026-10-18: "use ISO 4217 codes"'
by: claude/coordinator
status: active # active or superseded
encoded_in: "" # optional path, commit or PR that now enforces it
---
```

The coordinator writes memory. Workers propose entries in their reports.

### Nodes helper

```text
bash "$CREW_SKILLS/nodes/scripts/nodes.sh" <command>
  list                     one JSON object per window in this Kitty
  read ID [screen|all]     print a window's text
  send ID [--enter]        send standard input; --enter adds Return
  spawn --name N --cli claude|codex --cwd DIR [--task T]
                           open a worker tab; print its window ID
  interrupt ID             send Escape to a worker window
  close ID                 close a worker window
```

IDs are Kitty window IDs within one Kitty instance.
The helper refuses to send to, interrupt or close its own window.
`interrupt` and `close` act only on windows labeled `crew_role=worker`.
`send --enter` sends Return separately, after a 0.5 second pause.
`spawn` runs `kitten @ launch --type=tab --keep-focus --copy-env`.
It titles the tab `<name> · <cli>`.
It sets `CREW_ROLE=worker`, `CREW_NODE`, `CREW_TASK` and `CREW_PARENT`.
It labels the tab with `crew_node`, `crew_cli`, `crew_role`, `crew_task`
and `crew_parent` user variables, then runs `"$CREW_BIN" <cli>`.

### Runs

Each task keeps briefs and reports in `$CREW_RUNS/<task>/`.
A notice is one line: `<task>/<node>: <status>. Report: <path>`.

### Kitty

crew uses `kitten @` through `$KITTY_LISTEN_ON` only.
Outside a remote-controllable Kitty, the launcher opens a new Kitty.
It passes `-o allow_remote_control=socket-only` and a unique `--listen-on`
socket under `${TMPDIR:-/tmp}`.
crew never edits `kitty.conf`, `~/.claude` or `~/.codex`.
It writes only under `$CREW_HOME` and its own temporary files.
It creates no links in `~/.agents` or other shared agent directories.
Pi and plain Codex read `~/.agents/skills`, so a link there leaks crew.
Codex finds the skills through the paths in `## This session`.

### Permissions

The human's Claude Code session keeps its prompts.
A settings rule allows the nodes helper without a prompt.
The human's Codex session runs with `--sandbox danger-full-access`.

Workers keep each CLI's normal prompts by default.
Claude Code workers also get the settings rule for the nodes helper.
Codex workers run with `--sandbox danger-full-access`, like the human's.
Codex's sandbox blocks the Kitty socket, so a sandboxed worker cannot report.
The human opts in to unattended workers with `CREW_UNATTENDED_WORKERS=1`.
Then Claude Code workers get `--dangerously-skip-permissions`.
Codex workers get `--dangerously-bypass-approvals-and-sandbox`.
crew never sets this variable itself; only the human does.

Never pass model, provider or credential settings.
Each CLI keeps the human's configuration, including Vertex endpoints.

## Verification

Run `nix flake check` for unit tests and `shellcheck`.
Unit tests use fake CLIs and a temporary `HOME`.
They unset `HYPRLAND_INSTANCE_SIGNATURE` and `XDG_RUNTIME_DIR`.
They must not depend on Linux-only paths.
Evaluate the macOS package with
`nix eval .#packages.aarch64-darwin.default.drvPath`.
Run `tests/live/` scripts only in a desktop Kitty session.
Live tests start their own hidden Kitty, never the human's windows.
On Linux, Kitty needs `XDG_RUNTIME_DIR` to reach Wayland.
Keep it for live tests; crew code must still never read it.

Report exactly what you ran, what passed and what you did not check.
A statement by a model is not evidence.

## Rules

- Do not commit, push or create remotes unless the coordinator asks.
- Stage your new files with `git add`; flakes ignore untracked files.
- Never put secrets, work data or real memory in the repository.
- Do not edit other repositories.

## Writing

Write repository text in English. Agents answer in the human's language.
Keep each sentence to 25 words or fewer. Use active voice.
Do not use em dashes, en dashes or emojis. Wrap text at 78 columns.

# AGENTS.md

## Mission

crew gives Claude Code, Codex and Pi one shared core on any machine with Nix.
The core holds base instructions, skills, memory and Kitty messaging.
Whichever CLI the human starts, the agent has the same abilities.
Agents in separate Kitty tabs coordinate work across repositories.

Keep crew small. Add machinery only when real use shows that it helps.
crew is a public repository at `github.com/Dauno/crew`. It runs on this
Linux host and on a macOS work machine. Everything committed is world
readable, so commit nothing private.

## Repository structure

- `flake.nix`: inputs, the `crew` package and checks.
  Systems: x86_64-linux, aarch64-linux and aarch64-darwin.
- `bin/crew`: launcher for `crew claude`, `crew codex` or `crew pi`.
- `core/instructions.md`: base instructions that all three CLIs receive.
- `claude/`: the Claude Code adapter, a plugin that carries the skills.
- `skills/nodes/`: Kitty messaging between agents, with `scripts/nodes.sh`.
  The package installs it on the PATH as `crew-nodes`.
- `skills/plan/`: verify requests and agree on scope before implementation.
- `skills/implement/`: make and verify requested code changes.
- `skills/review/`: inspect changes and report concrete findings.
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
| `CREW_CLI` | `claude`, `codex` or `pi` |
| `CREW_ROLE` | `worker` in spawned nodes; unset in the human's session |
| `CREW_NODE` | the node name, in workers |
| `CREW_TASK` | the task label, in workers |
| `CREW_PARENT` | the Kitty window ID of the spawning node, in workers |
| `CREW_REPO_ID` | the repository ID; empty outside Git |
| `CREW_SESSION_ID` | a UUID unique to this crew CLI session |
| `CREW_INBOX` | `$CREW_HOME/mailboxes/$CREW_SESSION_ID` |

`CREW_REPO_ID` comes from the `origin` URL as `host/owner/repo`.
It is lowercase, without `.git`, a user or credentials.
Without `origin`, it is `local/<directory name>`.
Memory directory names replace each `/` with `_`.

### Instructions

The launcher appends a `## This session` block to `core/instructions.md`.
The block lists the CLI, role, node, task, parent window, repository ID,
session ID and inbox path. It also lists memory, runs and skills paths and
the nodes helper.
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

Every crew session has the helper on its PATH as `crew-nodes`.
It runs `skills/nodes/scripts/nodes.sh`. Agents call it only by that name,
never through a path or a shell variable.

```text
crew-nodes <command>
  list                     one JSON object per window in this Kitty
  read ID [screen|all]     print a window's text
  send ID                  publish nonempty standard input to a crew session
  type ID [--enter]        type nonempty standard input into a window
  type ID --enter-only     type only Return; read no input
  ack MESSAGE_ID           acknowledge a message in this session's inbox
  notify STATUS REPORT     publish a worker notice to its parent
  spawn --name N --cli claude|codex|pi --cwd DIR [--task T] [-- ARGS...]
                           open a worker tab; print its window ID
  interrupt ID             send Escape to a worker window
  close ID                 close a worker window
```

IDs are Kitty window IDs within one Kitty instance.
The helper refuses to send to, interrupt or close its own window.
`interrupt` and `close` act only on windows labeled `crew_role=worker`.
`send ID` resolves the live window's `crew_session` user variable and stores
its message in that session's mailbox. The success result confirms storage,
not receipt. Text is limited to 8 KiB of UTF-8; send a report path for longer
content. It never types into the target's editor. `send --enter` and
`send --enter-only` fail; use `type` for explicit keyboard input.
`type` preserves the previous terminal behavior, including its editor checks.
`ack MESSAGE_ID` accepts only the current session's delivered message. It is
idempotent after receipt. Only `ack` moves a message from `pending` to
`received`; adapters never infer receipt from native API calls or hook output.
Agents acknowledge each crew message after reading it. An acknowledgement does
not report task completion and does not promise exactly-once execution.

`notify` needs `CREW_TASK`, `CREW_NODE` and `CREW_PARENT`. It records the
worker's metrics once, then publishes this existing notice text natively:
`<task>/<node>: <STATUS>. Report: <REPORT>. Metrics: <summary>`.
A successful notice only confirms storage. It does not wait for or simulate
an empty parent editor.
`spawn` also sets `CREW_STARTED_AT` to the Unix time of the launch.

### Native message delivery

Each CLI session owns `$CREW_HOME/mailboxes/<session-id>/`. Messages contain
only `id`, `from` and `text`; the recipient comes from the mailbox route.
Publication writes a temporary file and renames it atomically into `pending/`.
A private dispatch marker prevents repeated native injection before `ack`.

Each receiver processes one message at a time. An acknowledgement validates
`CREW_SESSION_ID`, moves that message into `received/` and permits the next
message. If a receiver crashes after reserving delivery, crew does not inject
the same message again automatically. The pending file remains for explicit
reconciliation. New sessions never inherit pending files automatically.
There is no terminal fallback when a native receiver is missing.

Pi uses a session extension. Claude uses `SessionStart` `watchPaths` and a
one-shot `FileChanged` hook with `asyncRewake`. The hook emits context but
never acknowledges it. Codex runs its visible TUI on a per-session local
app-server. A supervised receiver queues to that server's loaded root thread.
A new root thread invalidates the route; messaging fails closed until crew
starts a fresh session.

### Metrics

`skills/nodes/scripts/metrics.sh record --status S --report R` appends one
JSON line to `$CREW_HOME/metrics.jsonl` and prints a one-line summary.
`notify` calls it. It reads only the worker's own CLI log: Claude Code by
`CLAUDE_CODE_SESSION_ID`, Codex by `CODEX_THREAD_ID`.

Each line has the time, task, node, parent, repository ID, CLI and its
version, models, status, report and wall seconds since `CREW_STARTED_AT`.
It also has the session's own durations and tokens: input, cache read, cache
write, output and reasoning. Cost comes from Claude Code's own total. For
Codex, it comes from a price table when the table lists the model. Pi cost
comes from its recorded per-message estimates. Missing or invalid Pi costs
remain null. `cost_source` is `claude`, `price_table`, `pi` or `unavailable`.
Pi reports estimated costs. Subscription limits and actual charges can differ.
The package ships
`skills/nodes/prices.json`; `$CREW_HOME/prices.json` overrides it per
machine, for example with Vertex prices at work.

Pi workers use only the session directory selected at launch:
`$CREW_RUNS/<task>/pi/<window>-<started>`. The launcher validates the task,
window ID and start time, then refuses to reuse an existing directory. The
collector requires one JSONL file and reads `session_id` from its header
`id`. It gets `cli_version` from `pi --version`. Header `version` means the
file format.

Metrics hold numbers and identifiers, never prompts, code or output. They
stay on the machine with the rest of `$CREW_HOME`. A metrics failure never
blocks a notice: the summary then says `metrics unavailable`.
`spawn` runs `kitten @ launch --type=tab --keep-focus --copy-env`.
It titles the tab `<name> · <cli>`.
It sets `CREW_ROLE=worker`, `CREW_NODE`, `CREW_TASK`, `CREW_PARENT`,
`CREW_SESSION_ID` and `CREW_INBOX`. It labels the tab with `crew_node`,
`crew_cli`, `crew_role`, `crew_task`, `crew_parent`, `crew_session` and
`crew_native` user variables, then runs `"$CREW_BIN" <cli>`.
Arguments after `--` go to that CLI unchanged, for example a model flag.
Agents pass them only when the human asks; by default workers get none.

### Runs

Each task keeps briefs and reports in `$CREW_RUNS/<task>/`.
A notice is one line:
`<task>/<node>: <status>. Report: <path>. Metrics: <summary>`.

### Kitty

crew uses `kitten @` through `$KITTY_LISTEN_ON` only.
Outside a remote-controllable Kitty, the launcher opens a new Kitty.
It passes `-o allow_remote_control=socket-only`,
`-o macos_quit_when_last_window_closed=yes` and a unique `--listen-on`
socket under `${TMPDIR:-/tmp}`.
crew never edits `kitty.conf` or CLI settings and authentication under
`~/.claude` or `~/.codex`. The CLIs manage their own native logs. Crew-owned
state stays under `$CREW_HOME` and its own temporary files.
It creates no links in `~/.agents` or other shared agent directories.
Pi and plain Codex read `~/.agents/skills`, so a link there leaks crew.
Codex finds the skills through the paths in `## This session`.

### Permissions

The human's Claude Code session keeps its prompts.
A settings rule allows `crew-nodes` without a prompt.
The human's Codex session runs with `--sandbox danger-full-access`.

Workers run without tool confirmation prompts.
Claude Code workers get `--dangerously-skip-permissions`.
Codex workers get `--dangerously-bypass-approvals-and-sandbox`.
Pi 1.3.0 has no tool permission prompts and needs no bypass flag.
Pi can ask whether to trust project resources under `.pi`.
The human answers project trust dialogs.
Codex's sandbox blocks the Kitty socket, so a sandboxed worker cannot report.

Never pass model, provider or credential settings.
Each CLI keeps the human's configuration, including Vertex endpoints.

## Verification

Run `nix flake check` for unit tests and `shellcheck`.
Unit tests use fake CLIs and a temporary `HOME`.
They unset `HYPRLAND_INSTANCE_SIGNATURE` and `XDG_RUNTIME_DIR`.
They must not depend on Linux-only paths.
Evaluate the macOS package with
`nix eval .#packages.aarch64-darwin.default.drvPath`.
Run the fake nodes live test with
`nix develop -c bash tests/live/nodes_live.sh`.
The default shell provides Kitty, jq, Python, ShellCheck, Bash and coreutils.
Run `tests/live/` scripts only in a desktop Kitty session.
Live tests start their own hidden Kitty, never the human's windows.
`tests/live/messaging_live.sh` runs a real Claude smoke with Haiku and the
current provider; it may incur model usage. Do not start paid Pi or Codex
turns without coordinator approval.
On Linux, Kitty needs `XDG_RUNTIME_DIR` to reach Wayland.
Keep it for live tests; crew code must still never read it.

Report exactly what you ran, what passed and what you did not check.
A statement by a model is not evidence.

## Rules

- Do not commit, push or create remotes unless the coordinator asks.
- Commit with the repository's configured Git identity. Never pass or set
  `user.name` or `user.email`.
- Stage your new files with `git add`; flakes ignore untracked files.
- Never put secrets, work data or real memory in the repository. It is
  public, and Git history keeps every commit.
- Use generic examples in tests, docs and commit messages. Do not name
  employers, work repositories, internal hosts or private endpoints.
- Do not edit other repositories.
- Never signal or close a process you did not start. Track a child by the
  PID your own command returned, never by a name search.

## Commits

Commit subjects follow Conventional Commits:

    type(scope): summary

- `type` is `feat`, `fix`, `docs`, `refactor`, `test`, `chore` or `ci`.
- `scope` is optional. Use a directory or area, such as `nodes` or `pi`.
- Write the summary in the imperative, lowercase, without a final period.
  Keep the whole subject to 72 characters or fewer.
- Add a body when the reason is not obvious. Separate it from the subject
  with a blank line. Explain why, not what.
- Mark a breaking change with `!` after the type, such as `feat!: ...`,
  and describe it in the body.
- Make one logical change per commit. Keep tests with the code they cover.
- Commits on a branch follow the same format. The squash merge then
  replaces them with the PR title, as Pull requests describes.

Commit text follows the rules in Writing and the privacy rules above.

## Pull requests

Open a pull request only when the human asks.

- Branch from `main`. Name the branch with short, lowercase, hyphenated
  words, such as `pi-support`.
- Give each PR one purpose. Split unrelated changes into separate PRs.
- Write the title like a commit subject: `type(scope): summary`.
- Run `nix flake check` before you open the PR.
- Write the body with these sections:
  - `## Summary`: a short list of what changed and why.
  - `## Checks`: each command you ran and its observed result.
  - `## Limits`: what you did not run or could not verify, such as
    macOS, aarch64-linux or live tests. Write `None` if nothing applies.
- Do not claim a check passed unless you ran it and saw the result.
- Link a related issue in the Summary with `Closes #N`, when one exists.
- Merge with a squash merge. The PR title becomes the commit subject and the
  PR Summary becomes its body. Keep the title in the format above.
- Delete the branch after the merge.

PR text follows the rules in Writing and the privacy rules above.

## Writing

Write repository text in English. Agents answer in the human's language.
Keep each sentence to 25 words or fewer. Use active voice.
Do not use em dashes, en dashes or emojis. Wrap text at 78 columns.

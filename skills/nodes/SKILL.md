---
name: nodes
description: >-
  Coordinate Claude Code, Codex and Pi workers in Kitty windows. Workers use
  it to notify their parent about task results.
---

# Agent nodes

Use nodes for bounded work that benefits from separate Claude Code, Codex or
Pi sessions. The coordinate skill defines coordinator responsibilities.
Create fresh nodes for every new task. Never reuse a node from another task.

## Find and message nodes

The helper is on `PATH` as `crew-nodes`. Call it by that name in every
command. This matches Claude Code's preapproved rule for the helper.

```bash
crew-nodes list
crew-nodes read 123 screen
crew-nodes read 123 all
crew-nodes send 123 <<'MESSAGE'
Please review the generic example and report your findings.
MESSAGE
crew-nodes type 123 --enter <<'INPUT'
/clear
INPUT
crew-nodes ack 550e8400-e29b-41d4-a716-446655440000
crew-nodes spawn --name reviewer --cli CLI \
  --cwd /path/to/repository --task example
crew-nodes spawn --name guide --cli CLI \
  --cwd /path/to/repository --task example --split
crew-nodes interrupt 456
crew-nodes close 456
```

Workers send their one-line notice to their parent with `notify`:

```bash
crew-nodes notify done /path/to/report.md
```

The helper records one metrics line and publishes the existing notice text
through the parent's native mailbox. Metrics stay in
`$CREW_HOME/metrics.jsonl`. The command succeeds after storage, not receipt.

`send ID` stores text in the session labeled by that Kitty window ID.
It does not inspect or type into the target editor. Use `type ID` only for
explicit terminal input. `notify` resolves `CREW_PARENT` through the parent's
`crew_session` label. `list` shows the crew labels needed for routing.

`list` prints one JSON object per window. Each object includes its ID, title,
working directory, foreground command, `crew_*` variables and `self` flag.
Pi windows also include `delivery: null`, a held delivery's ID and age in
seconds, or `status: unavailable` if inspection fails. Unavailable does not
mean received. This status is read-only; holds never expire.
Confirm the exact ID and command with `list` before sending. Never send to a
window marked `self` or to your own window. The helper rejects sends,
interrupts and closes to its own window.

`send ID` reads nonempty UTF-8 text from standard input and stores it
atomically. Messages allow up to 8 KiB of UTF-8 text. For longer reports,
write a file and send its path. The receiver presents the message ID and
sender to the agent.
Claude and Codex agents acknowledge each message after reading it, using
`crew-nodes ack MESSAGE_ID` before acting. Pi automatically runs `ack` only
after its receiver verifies the exact custom message in the active Pi session
branch and persisted JSONL file, whose header matches that Pi session. This
records persisted incorporation, not model reading or task completion. Pi does
not require a routine model acknowledgement; manual `ack` remains supported.
Read a message before manually acknowledging it, and use only its delivered
`CREW_MESSAGE_ID`. Never read or list `$CREW_INBOX` files directly. To wait
for a reply, end the turn. Do not poll with sleep loops; the receiver delivers
messages when they arrive.

`ack` validates the current `CREW_SESSION_ID` and accepts only the current
session's dispatched message. Repeating an acknowledgement is harmless.
Receivers hold one delivery marker until that acknowledgement. They never
reinject a pending message on each poll or signal. A crash after reserving
delivery leaves the message held for explicit reconciliation; crew does not
promise exactly-once delivery.

`send --enter` and `send --enter-only` fail with guidance to use `type`.
`type ID` keeps the previous raw Kitty input behavior. Its `--enter` form
waits for a clear, recognized editor. Its `--enter-only` form sends Return
only.
Agent task messages must never fall back to `type`.

## Check a worker before messaging

After `spawn`, read the worker screen before sending its brief. Confirm the
CLI is ready and no trust or permission dialog is open. A title or process
alone does not prove readiness. Native messages do not require an empty
editor.

Claude Code can ask whether to trust a new project. Codex can also ask for
repository trust. Pi can ask whether to trust project resources under `.pi`.
Unattended permissions can trigger a one-time notice.

Ask the human to answer trust or permissions dialogs in that worker's tab.
Never answer a dialog yourself or send a brief to it. Return could accept it.
Pi 1.4.0 has no tool permission prompts and needs no bypass flag.

`send` and `notify` never inspect or change the destination editor.
`type --enter` uses Kitty screen parsing to avoid replacing human input.
Pi draws its editor between matching full-width horizontal borders above two
footer rows. Drafts, scroll indicators, autocomplete lists, overlays,
incomplete frames and unknown layouts make `type --enter` wait or fail closed.
The Pi extension never parses or writes to the editor.

```bash
crew-nodes read 456 screen
```

## Task context and reuse

Keep each brief and report in `$CREW_RUNS/<task>/`. A brief names the skill
for each role: `plan`, `implement`, `review`, `git`, `coordinate` or
`explore`. Each request must specify how to return its result: a report path
and `notify`, or a short native answer using `send`.
Use one-line notices in this format:
`<task>/<node>: <status>. Report: <path>`. The coordinator writes memory.
Workers propose memory entries in their reports.

Create a new node for every new task. For a continuation within the same task,
first confirm its ID, directory, CLI and task labels with `list`. Then inspect
its screen and context before assigning more work.

`--task` is a label, not the prompt. Pi requires one flat path component;
empty task labels use `_untasked`. A returned Kitty ID means Kitty created a
tab, not that the CLI started. Read the window screen after launch. If no
window appears, report the failure and investigate before repeating the same
command. Keep credentials and sensitive arguments out of diagnostics.

In Claude Code, `/context` opens a `Context Usage` view. `/context all`
expands the view. Record only its summary. The full view can expose private
file paths.

In Codex, use `/status` to inspect context usage. Read its current label
before interpreting a percentage. Record only the context indicator.

In Pi, use `/session` for session totals. Read context usage from its footer.
Record only context indicators, never the displayed session path.

At 70% context or 250k tokens, whichever comes first, use the `handoff` skill.

## Stop and close workers

Use only the helper to interrupt a worker. It sends Escape to that worker's
window and rejects human windows and non-worker windows:

```bash
crew-nodes interrupt 456
```

Inspect the screen after interruption. If input returned to the editor, clear
it before sending a task-specific stop message. Ask for a visible
acknowledgement and verify the window is idle. Do not assume that Escape
stopped a handoff.

When the work is complete, close the CLI normally. Claude Code accepts
`/exit`. Codex accepts `/quit`. Check `list` once after sending the command.
If an idle worker shell remains, close its ID with the helper. The helper
closes only windows labeled `crew_role=worker`.
Do not close a busy or unrelated window.

Pi also exits through `/quit`. Escape aborts active Pi work and can restore a
queued message to the editor. Escape does not reliably clear an ordinary
draft, so inspect the screen before sending a stop command.

## Spawn and report

`spawn` requires `CREW_BIN` and a running Kitty window. It creates a worker
tab with a fresh `CREW_SESSION_ID`, `CREW_INBOX`, task labels and parent ID.
It prints the new window ID. Keep the worker's task, repository and report
path explicit in its brief. Use `spawn --split` for the guide role by default.
It opens a window next to the caller in the current tab. It respects Kitty's
active layout and does not change Kitty configuration.
Pass CLI arguments after `--` only when the human requests a model or option.
By default, each worker uses its CLI's default model. A brief alone does not
change a model; pass the requested model in the `spawn` command.

After a task, write a report with completed work, checks, limits and
unresolved decisions. Then run `crew-nodes notify done /path/to/report.md`.

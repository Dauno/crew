---
name: nodes
description: >-
  Coordinate Claude Code, Codex and Pi workers in Kitty windows. Workers use
  it to notify their parent about task results.
---

# Agent nodes

Use nodes for bounded work that benefits from separate Claude Code, Codex or
Pi sessions. The coordinator assigns tasks, checks results and stays
accountable.
Create fresh nodes for every new task. Never reuse a node from another task.

## Find and message nodes

The helper is on `PATH` as `crew-nodes`. Call it by that name in every
command. This matches Claude Code's preapproved rule for the helper.

```bash
crew-nodes list
crew-nodes read 123 screen
crew-nodes read 123 all
crew-nodes send 123 --enter <<'MESSAGE'
Task: example. Please finish the assigned work and report to the coordinator.
MESSAGE
crew-nodes spawn --name reviewer --cli claude \
  --cwd /path/to/repository --task example
crew-nodes interrupt 456
crew-nodes close 456
```

Workers send their one-line notice to their parent with `notify`:

```bash
crew-nodes notify done /path/to/report.md
```

The helper records metrics and adds `Metrics: <summary>` to the notice.
Metrics stay in `$CREW_HOME/metrics.jsonl`. If the parent input stays
occupied for 60 seconds, a detached sender retries for up to one hour.
The pending notice stays in `$CREW_RUNS/<task>/notices/` until delivery.
The sender records its state and failure reason beside it in a `.status` file.

The helper formats the notice and sends it to the `CREW_PARENT` window.
Use the exact window ID shown by `crew-nodes list` for other destinations.

`list` prints one JSON object per window. Each object includes its ID, title,
working directory, foreground command, `crew_*` variables and `self` flag.
Confirm the exact ID and command with `list` before sending. Never send to a
window marked `self` or to your own window. The helper rejects sends,
interrupts and closes to its own window.

`send` reads nonempty text from standard input. It removes carriage returns
before sending. With `--enter`, it waits up to 60 seconds for an empty input,
sends the text, waits 0.5 seconds, then sends Return separately. Styled
placeholders and suggestions do not count as human text. An unrecognized
input times out instead of blocking forever. Empty input fails; use
`send ID --enter-only` to send Return without reading standard input. Workers
use `notify STATUS REPORT` instead of formatting their own completion message.

Send each message once. Do not poll or run a forwarding loop. Wait for the
worker's notice, then read its window when you need a deliberate status check.
A successful send proves delivery to Kitty, not acceptance or completion.

## Check a worker before messaging

After `spawn`, read the worker screen before sending its brief. Confirm the
interactive editor is ready and no dialog is open. A title or process alone
does not prove readiness.

Claude Code can ask whether to trust a new project. Codex can also ask for
repository trust. Unattended permissions can trigger a one-time notice.

Ask the human to answer trust or permissions dialogs in that worker's tab.
Never answer a dialog yourself or send a brief to it. Return could accept it.
Pi 0.75.4 has no permission prompts and needs no bypass flag.

Pi draws its editor between matching full-width horizontal borders above two
footer rows. Draft text keeps a notice waiting, regardless of its color.
Long drafts can show scroll indicators. Autocomplete lists, overlays,
incomplete frames and unknown editor layouts keep notices waiting too. An
empty editor remains available while Pi runs a command, so it can accept a
notice or steering input. The helper rechecks the editor before sending.

```bash
crew-nodes read 456 screen
```

## Task context and reuse

Keep each brief and report in `$CREW_RUNS/<task>/`. Use one-line notices in
this format: `<task>/<node>: <status>. Report: <path>`. The coordinator writes
memory. Workers propose memory entries in their reports.

Create a new node for every new task. For a continuation within the same task,
first confirm its ID, directory, CLI and task labels with `list`. Then inspect
its screen and context before assigning more work.

In Claude Code, `/context` opens a `Context Usage` view. `/context all`
expands the view. Record only its summary. The full view can expose private
file paths.

In Codex, use `/status` to inspect context usage. Read its current label
before interpreting a percentage. Record only the context indicator.

In Pi, use `/session` for session totals. Read context usage from its footer.
Record only context indicators, never the displayed session path.

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
tab with the selected CLI, task labels and parent window ID. It prints the
new ID. Keep the worker's task, repository and report path explicit in its
brief.
Pass CLI arguments after `--` only when the human requests a model or option.
By default, each worker uses its CLI's default model. A brief alone does not
change a model; pass the requested model in the `spawn` command.

After a task, write a report with completed work, checks, limits and
unresolved decisions. Then run `crew-nodes notify done /path/to/report.md`.

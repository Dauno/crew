---
name: memory
description: >-
  Use at session start to read crew memory, and when the human decides
  something or a task ends, to record decisions, lessons and verified
  commands.
---

# Memory

Memory records durable decisions, lessons and evidence across sessions. It
lives outside Git at `$CREW_MEMORY` and stays on its machine. Never copy work
data, credentials or private memory into the crew repository or messages.
The human's current request always takes precedence over memory.

## Read at session start

Read the available files at these paths:

- `$CREW_MEMORY/index.md`
- `$CREW_MEMORY/global/index.md`
- `$CREW_MEMORY/machine/index.md`
- `$CREW_MEMORY/repos/index.md`
- The current repository's index under `repos/`, if it exists.

Use `CREW_REPO_ID` to find the repository index. Replace each `/` with `_`
for its directory name. Follow only links relevant to the current task. Do not
read unrelated repository entries or treat an old note as current authority.

## Record decisions and task results

Record a human decision as soon as the human states it. Preserve its exact
wording and date. At the end of each task, record other durable decisions,
lessons, observations and verified commands. Do not wait for the whole
session; one session may include several tasks. Avoid session diaries,
transcripts, speculation presented as fact, credentials and unnecessary work
data.

The coordinator writes memory. Workers do not edit memory files. When a human
decision occurs, workers promptly send its exact quote and intended scope to
their parent. At task end, workers propose other entries in their reports,
including the intended scope and evidence. The coordinator reviews and
records appropriate proposals.

Every entry uses Markdown with YAML frontmatter:

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

Use the matching template in `templates/`. Keep one durable topic per entry.
Use a clear filename, such as `2026-10-18-currency-codes.md`.

## Sources and human wording

For a human decision or preference, preserve the exact relevant words and
record the date: `Human on YYYY-MM-DD: "exact quotation"`. Do not paraphrase
inside quotation marks or invent a quote. If no human quote applies, identify
the actual evidence source, such as a command result or code location. Keep
source details sufficient to verify the claim without copying sensitive data.

## Scope and privacy

- `global` applies across repositories and machines.
- `machine` applies only to this machine.
- `repo:<ID>` applies only to the repository identified by `CREW_REPO_ID`.

Store each entry in its scope directory:

- `global`: `$CREW_MEMORY/global/<entry>.md`
- `machine`: `$CREW_MEMORY/machine/<entry>.md`
- `repo:<ID>`: `$CREW_MEMORY/repos/<ID with / replaced by _>/<entry>.md`

Link each entry from its scope's `index.md`. Memory is machine-local and does
not synchronize between machines. Put repository paths and IDs in
`$CREW_MEMORY/repos/index.md`, not in Git. Keep work-specific information in
the relevant repo scope. Never store secrets.

## Status and promotion

Do not delete replaced entries. Set their status to `superseded` and link the
replacement in the body or index. Keep the historical decision intact.

Use this promotion ladder, with human review where repository policy requires
it:

1. Record a useful fact or lesson as a memory entry.
2. Propose a repository rule for its `AGENTS.md` through a PR, or a general
   crew rule through a commit. Crew rules must contain no work-specific data.
3. Promote a repeatable behavior into code and cover it with a test.

Do not promote information just because it appears in memory. Preserve
privacy boundaries and follow the current request before proposing changes.

## Indexes

Update the applicable indexes when adding or superseding an entry. Keep
indexes short, topical and useful for finding current entries. Link each
entry under a concise subject. Mark superseded links clearly and point to the
replacement. Do not turn an index into a chronological diary or duplicate the
full entry. Keep `$CREW_MEMORY/index.md` as the entry point to the scope
indexes. Keep `$CREW_MEMORY/repos/index.md` as the local repository ID and
path registry. Repo entries link from their own scope index.

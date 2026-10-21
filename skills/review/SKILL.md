---
name: review
description: >-
  Use when asked to review, inspect or find issues in a diff, branch, pull
  request, files or uncommitted changes.
---

# Review a change

Review only the scope the requester names. If none is named, review
uncommitted changes; if none exist, review the last commit.

## Understand the change

1. Read the diff before forming findings.
2. Read relevant callers, callees, tests, fixtures, documentation and
   repository contracts such as `AGENTS.md`.
3. Identify the expected load and state it in the report.
4. Check in this order: correct, safe, holds at the expected load, tested,
   fast, lean.
5. Rerun the repository's documented checks. Another agent's claim is not
   evidence.

## Report findings

Use numbered findings grouped under `Must fix`, `Should fix` and
`Nice to have`. Each finding states:

- What is wrong and the concrete input or situation that triggers it.
- The resulting problem and the smallest adequate fix.
- What happens if the issue remains.

A finding without a concrete case is not a finding. Re-read the reported
lines and confirm the case before including it. Do not report speculation as
fact. Do not change code while reviewing.

End the report with `Verdict:` and `Not checked:`. If you find nothing,
say so and state what you inspected and checked.

When working as a crew node, write the report under
`$CREW_RUNS/<task>/` in the human's language. Notify the parent using the
nodes skill. Number findings so the implementer can answer, for example,
"fixed 1 and 3".

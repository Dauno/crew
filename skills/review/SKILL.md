---
name: review
description: >-
  Use to review a diff, branch, pull request, files or uncommitted changes.
---

# Review a change

Review only the scope the requester names. If none is named, review
uncommitted changes; if none exist, review the last commit.

## Understand the change

1. Pin the comparison base first. Confirm it resolves, then confirm its diff
   is not empty. State the base in the report.
2. Read the diff before forming findings.
3. Read relevant callers, callees, tests, fixtures, documentation and
   repository contracts such as `AGENTS.md`.
4. Identify the expected load and state it in the report.
5. Check in this order: correct, safe, holds at the expected load, tested,
   fast, lean.
6. Rerun the repository's documented checks. Another agent's claim is not
   evidence.

## Report findings

Use separate sections for `Brief or request` and `Repository rules`. The
first checks what is missing, added without request, or implemented
incorrectly. Quote the exact brief or request line for each finding. The
second checks contracts and rules in `AGENTS.md` or similar files.

Within each axis, use numbered findings grouped under `Must fix`,
`Should fix` and `Nice to have`. Number findings continuously across both
sections so implementers can refer to them unambiguously. Each finding states:

- What is wrong and the concrete input or situation that triggers it.
- The resulting problem and the smallest adequate fix.
- What happens if the issue remains.

A finding without a concrete case is not a finding. Re-read reported lines
and confirm the case before including it. Do not report speculation as fact.
Do not change code while reviewing.

End the report with `Verdict:` and `Not checked:`. If you find nothing, say
so and state what you inspected and checked. When working as a crew node,
write the report under `$CREW_RUNS/<task>/` in the human's language. Notify
the parent using the nodes skill.

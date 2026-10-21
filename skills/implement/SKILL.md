---
name: implement
description: >-
  Use to implement a change, fix a bug or refactor code, tests, configuration
  or documentation.
---

# Implement a change

Before editing, read the task and the code it touches. Follow the crew
instructions and applicable repository contracts.

## Scope the work

1. List where the change must reach: callers, tests, fixtures, configuration,
   documentation and contracts. List every affected caller.
2. Check what the change could break or expose.
3. For a bug fix, build one command that reproduces the reported symptom and
   fails before forming a theory. Find every caller and fix the root cause
   once.
4. Choose the first option that fully works: no change; existing repository
   behavior; the standard library or platform; an installed dependency; then
   the minimum new code.

## Make the change

For a bug fix, write a regression test and watch it fail. Apply the fix, watch
the test pass, then rerun the original reproduction command. Prefix temporary
debug output with a unique tag and remove it before finishing. The
reproduction must fail before the fix and pass after it.

Keep the repository's structure and conventions. Do not add unrequested
abstractions, options, configuration or code for later. Prefer deletion over
addition when it solves the task.

Keep validation at trust boundaries, error handling that prevents data loss,
security and accessibility behavior, and anything the human requested. Never
remove these.

Non-trivial logic, including branches, loops, parsers, money or security,
needs one small test. Test behavior through public interfaces, not internals.
Get expected values from an independent source, not by recomputing them the
way the code does.

## Verify and report

Run the repository's documented checks and inspect the final diff. Report
what changed, commands and observed results. State anything skipped or not
verified, plus remaining risks.

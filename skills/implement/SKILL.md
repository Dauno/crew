---
name: implement
description: >-
  Use when asked to implement, change, fix or refactor code, tests,
  configuration or documentation.
---

# Implement a change

Before editing, read the task and the code it touches. Follow the crew
instructions and applicable repository contracts.

## Scope the work

1. List where the change must reach: callers, tests, fixtures, configuration,
   documentation and contracts.
2. Check what the change could break or expose.
3. For a bug fix, find every caller and fix the root cause once.
4. Choose the first option that fully works: no change; existing repository
   behavior; the standard library or platform; an installed dependency; then
   the minimum new code.

## Make the change

Keep the repository's structure and conventions. Do not add unrequested
abstractions, options, configuration or code for later. Prefer deletion over
addition when it solves the task.

Never remove validation at trust boundaries, error handling that prevents
data loss, security or accessibility behavior, or anything the human
requested.

Non-trivial logic, including branches, loops, parsers, money or security,
needs one small test. Trivial changes do not need a test.

## Verify and report

Run the repository's documented checks and inspect the final diff. Report
what changed, the commands and observed results. State anything skipped or
not verified, plus remaining risks. Do not claim a check passed unless you
observed its result.

---
name: onboard
description: >-
  Use when the current repository has no repo-specific crew memory yet.
---

# Onboard a repository

Use this skill when the current repository has no repo-specific memory entry.
Onboarding is read-only. Do not modify repository files, configuration, Git
state or remote services.

## Inspect the repository

1. Read applicable `AGENTS.md` and `CLAUDE.md` files, starting at the
   repository's top level and checking parent directories as needed.
2. Read the README, `CONTRIBUTING` guidance and continuous integration
   configuration. Look for workflow files and other CI definitions.
3. Identify the language, build system and package manager from tracked files.
4. Find documented build, test and lint commands. Note which commands are
   missing or unclear.
5. Check for existing repo memory through `CREW_REPO_ID` and
   `$CREW_MEMORY/repos/`.

Do not read credential files or unrelated private data. Do not assume a
command is safe because its name suggests a check.

## Verify safely

Run only quick, local commands that do not delete data, change shared state,
access production or require unreviewed network access. Prefer the documented
format, lint and unit test checks. Ask the human before running anything
ambiguous or destructive. Do not install dependencies or edit files as part
of onboarding.

For every command you run, record its exact command, date, observed result and
evidence. Include failures and limits. Propose one `Command` entry per useful
command, using `templates/command.md`. The coordinator writes memory; workers
include proposals in their report.

## Register the repository

Propose an entry in `$CREW_MEMORY/repos/index.md` with the `CREW_REPO_ID` and
its local repository path. The coordinator maintains this private registry.
Do not put local paths or real memory in Git.

## Report

Summarize the repository purpose, its rules, build/test/lint commands, and
what you verified. State what you did not run and why. Include proposed
`Command` entries and the repository registry entry. Confirm that onboarding
made no repository changes.

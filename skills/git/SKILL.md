---
name: git
description: >-
  Use to commit, push, open a pull request or sync a local branch after
  a merge.
---

# Deliver a change with Git

Repository rules in `AGENTS.md` govern commits, pull requests and writing.
Follow them. This skill adds a workflow; it does not replace those rules.

## Confirm scope

1. Inspect `git status` and the diff.
2. Confirm exactly the expected paths changed. Stop and report any others.
3. The git role edits no file content. Report what needs fixing instead.

## Commit

1. Keep one logical change per commit. Follow the repository's commit
   convention and explain why in the body when needed.
2. Stage whole files. If one file has separate changes, stage a filtered
   patch with `git apply --cached`. Interactive staging is unavailable.
3. Commit with the configured Git identity. Never pass or set `user.name` or
   `user.email`.
4. Add no attribution lines unless the repository asks for them.

## Verify and push

1. Rerun documented checks without cached results. Confirm the committed
   tree is clean.
2. Check authors with `git log --format='%an <%ae>' <base>..HEAD`.
3. Push plainly with an upstream. Rewriting a pushed branch needs explicit
   approval for that branch. Then use
   `git push --force-with-lease=<branch>:<expected sha>`.

## Pull requests

Open a pull request only when asked. Follow the repository's title and body
rules. List only checks you ran and their observed results. Add before and
after evidence when it applies. Confirm the pull request head matches local
`HEAD`.

## Forbidden actions

Never merge, delete branches, reset, rebase, stash or clean unless explicitly
asked.

## Sync after a merge

Sync the local base branch with `git pull --ff-only` only.

## Report

Report the branch, commit hashes, authors, commands with observed results,
pull request URL and head SHA.

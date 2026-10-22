---
name: coordinate
description: >-
  Use to coordinate a task with worker nodes, from the brief to the summary
  for the human.
---

# Coordinate a task

## Human session

Coordinate with the human, agree on scope and run the final objective gate.
Read the reports, not the implementation. The reviewer's verdict decides
quality; do not re-review approved work.

## Coordinator node

Orchestrate the assigned task and report to the human session. Do not run the
final objective gate or independently judge implementation quality.

## Prepare the work

1. Confirm scope, decisions, contracts, risks and verification with the human.
2. Before launch, show planned nodes in a table with node, CLI, model, effort
   and role. Do not show spawn commands. Wait for approval.
3. Choose models from crew memory and the human, never this skill.
4. Write `$CREW_RUNS/<task>/brief.md`. Include the goal, exact decision
   quotes, approved contract changes, rules, report paths and the skill for
   each role.
5. Start one explorer per task before other roles. Include its window in every
   brief. Close it at task end. At 70% context, replace it with `handoff` and
   tell the roles its new window.
6. Refer to `nodes` for spawning, messaging, screen checks and closing. Refer
   to `handoff` for replacement.

## Run the work

1. Have implementer and reviewer message each other directly. They loop until
   the reviewer approves. Refer to `nodes` for messaging.
2. Never read the full diff or judge implementation quality. Ask the reviewer
   a concrete question if you doubt a finding or verdict.
3. Read reports, not code. Check the reviewer's `Brief or request`, `Verdict`
   and `Not checked` sections against the human's decisions.
4. Close each node when its part is done.

## Final objective gate

Whoever writes the summary to the human runs this once, with short outputs:

1. Confirm the PR is open and its head equals local `HEAD` with `gh pr view`.
2. Check commit authors and subjects with `git log --format`.
3. Check with `git diff --stat` that changed files stay within the approved
   scope and that no contract changed without approval.
4. Run one documented check on the PR head and show only final result lines.

Summarize commits, gate results, deviations worth review and what nobody
checked. The coordinator records memory using the `memory` skill.

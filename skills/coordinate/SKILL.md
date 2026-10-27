---
name: coordinate
description: >-
  Use to coordinate a task with worker nodes, from the brief to the summary
  for the human.
---

# Coordinate a task

## Human session

Coordinate with the human, agree on scope and run the final objective gate.
Read reports, not implementation. The reviewer's verdict decides quality;
do not re-review approved work.

## Coordinator node

Orchestrate the assigned task and report to the human session. Do not run the
final objective gate or independently judge implementation quality.

## Plan deliveries

1. Confirm approved scope, decisions, contracts, risks and verification.
2. Size the task and split large work into milestones with concrete done
   criteria. Sequential work is the default.
3. Check dependencies, shared files, runtime resources, provider quota and
   human review capacity for each milestone. Any failed check means sequential
   work. Run no more than two milestones in parallel.
4. Choose roles and models per milestone from crew memory and the human,
   never this skill. Size them by cost, risk and work size. Write
   `$CREW_RUNS/<task>/deliveries.md` with one row per milestone: deliverable,
   done criteria, roles and models, parallel or sequential, status and PR.
   Use `pending`, `running`, `review` or `merged` for status. Ask the human
   again only when something has changed.
5. For large tasks, use a fresh coordinator node for each milestone. It reads
   `deliveries.md`; never use one node for the whole task.
6. Before the first launch, show planned nodes in a table with node, CLI,
   model, effort and role. Do not show spawn commands. Wait for approval.
   For later milestones, announce the launch in one line unless a new risk or
   usage limit appeared.
7. Write `$CREW_RUNS/<task>/brief.md`. Include the goal, exact decision
   quotes, approved contract changes, rules, report paths and each role's
   skill.
8. Parallel writers each use a separate branch and worktree at
   `$CREW_RUNS/<task>/worktrees/<milestone>`. The coordinator creates and
   removes these worktrees after merge. Read-only roles use their milestone's
   worktree.
9. Start one explorer per task before other roles. Include its window in
   every brief and close it at task end. At 70% context or 250k tokens,
   whichever comes first, replace it with `handoff` and tell the roles its new
   window.
10. A Claude Code worker in a new worktree opens a project trust dialog.
    The coordinator makes that window visible and asks the human to answer.
    Agents never answer trust dialogs.
11. Refer to `nodes` for spawning, messaging and closing. Refer to `handoff`
    for checkpoints and fresh sessions.

## Run the work

1. Have implementer and reviewer message each other directly. Allow at most
   three review rounds. If they do not converge, stop and ask the human to
   redefine done or defer work to a later milestone.
2. Never read the full diff or judge implementation quality. Ask the reviewer
   a concrete question if you doubt a finding or verdict.
3. Read reports, not code. Check the reviewer's `Brief or request`, `Verdict`
   and `Not checked` sections against the human's decisions.
4. Update the rolling handoff at each milestone or iteration end. Apply this
   rule to the human session too, and suggest a fresh session at each
   milestone end.
5. Close each node when its part is done.

## Final objective gate

Whoever writes the summary to the human runs this once, with short outputs:

1. Confirm the PR is open and its head equals local `HEAD` with `gh pr view`.
2. Check commit authors and subjects with `git log --format`.
3. Check with `git diff --stat` that changed files stay within the approved
   scope and that no contract changed without approval.
4. Run one documented check on the PR head and show only final result lines.

Summarize commits, gate results, deviations worth review and what nobody
checked. The coordinator records memory using the `memory` skill.

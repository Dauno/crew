---
name: plan
description: >-
  Use to plan, scope or assess a proposal before implementation.
---

# Plan a change

Use this skill only while planning. Wait for human approval before acting.

## Verify and question

1. Read the request and inspect the relevant repository and environment.
   Verify facts yourself; never ask the human for facts you can look up.
2. Mark claims you cannot verify and assumptions that could affect scope or
   sequence.
3. Identify repository contracts. A contract change needs approval from the
   coordinator and the human. Record applicable contracts in the brief.
4. Challenge work the need does not justify.

## Present decisions

1. Present numbered decisions with a recommendation. Word each so "yes"
   accepts it. If a decision remains unanswered, take the recommendation and
   say so explicitly.
2. Ask only decisions whose prerequisites are settled. Defer dependent
   decisions until their prerequisites have answers.
3. After each answer round, recompute which decisions are ready. Repeat until
   no decision remains open and nothing is silently assumed.
4. If answers leave an assumption, surface it as a decision.
5. Record each human decision with its exact quote through the memory skill.
   If you work as a node, send the exact quote and intended scope to the
   parent.

## Plan work with nodes

When implementation uses worker nodes, list each planned node, CLI, model and
effort. Wait for approval before spawning any node.

Write the brief under `$CREW_RUNS/<task>/`. Include the goal, decisions and
quotes, approved contract changes, rules and report paths.

When no nodes are needed, state the implementation scope and verification
plan.

---
name: handoff
description: >-
  Use to hand off work to a fresh agent near the context limit or when asked.
---

# Hand off work

Use for worker nodes and the coordinator's own session. Keep one handoff
format for both.

## When to hand off

At 70% context usage or 250k tokens, whichever comes first, take no new
substantive work. Hand off instead of compacting. This rule also applies to
the human session. At each milestone or iteration end, update the latest
numbered handoff file in place. Fresh sessions resume from that latest file.
After a pause over one hour with context over 100k, resume in a fresh session
from the checkpoint, not the old session. Hand off sooner when
the coordinator or human asks.

## Outgoing agent

1. Stop at a safe point. Leave no half-finished edit.
2. Write the handoff to
   `$CREW_RUNS/<task>/handoff-<node>-<n>.md`. Set `<n>` one higher than
   the largest existing number for that node, starting at 1. At later
   checkpoints, overwrite that latest file.
3. Notify the parent with the path. Workers use `crew-nodes notify`. The
   coordinator tells the human, who starts a fresh session with that path.
4. Stay idle and edit nothing after notifying.

Include pointers, not copied contents:

- The goal and brief path.
- What is done, in progress and the concrete next steps.
- Every uncommitted path from `git status`, one line on its contents and
  whether it is ready.
- Pointers to relevant decisions in the brief or memory.
- Verified commands and observed results, plus what remains unverified.
- Open review findings and known pitfalls.
- Skills the successor should read.
- No secrets or private data.

A handoff is complete when a fresh agent can continue without the old
transcript and every uncommitted path is explained.

## Coordinator

At each human-session milestone end, write or update the numbered handoff
file in the same format. Suggest a fresh session, which resumes from the
latest handoff.

1. Confirm the old agent is idle on screen. Check the handoff against
   `git status`.
2. Spawn a fresh node with the same role, following the `nodes` skill.
3. Send it the brief and latest handoff paths. Wait for it to confirm
   understanding.
4. Close the old node only after that confirmation.

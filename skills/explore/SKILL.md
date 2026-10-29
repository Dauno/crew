---
name: explore
description: >-
  Use to ask the task explorer a read-only question, or when working as the
  explorer.
---

# Explore a task

## Ask the explorer

Any role can ask the task explorer.

1. Delegate broad or unknown-location searches, Git history, logs and external
   documentation. Do not delegate a file you will read anyway, such as a file
   you must edit.
2. Send one question with `crew-nodes send` to the explorer's window from the
   brief. Include your role, window ID, scope paths, purpose and answer length
   limit. End the turn to wait.
3. Treat the answer as leads. Read cited lines before relying on facts for a
   change or finding.

## Work as the explorer

1. Work strictly read-only. Do not edit, commit, write memory or use nodes.
   Use the network only when the question asks for it.
2. Answer one question at a time. Write
   `$CREW_RUNS/<task>/explore-<role>-<n>.md`, about 60 lines maximum. Include
   the direct answer, evidence as `file:line` or a short command output, what
   you could not verify, the commit and whether uncommitted changes exist.
3. Reread each cited line before citing it. Earlier reads may be stale after
   other roles edit files.
4. Reply only to the asker. Use `crew-nodes list` to match the message's
   `from` session to a window's `crew_session`, and confirm the window ID
   from the question. Send the answer path with `crew-nodes send`.
5. Answer facts with evidence. Do not opine on design or another role's work.
   Never reveal another role's questions or answers.
6. When the coordinator asks you to finish, publish your final report with
   `crew-nodes notify` before window closure. This records metrics once.

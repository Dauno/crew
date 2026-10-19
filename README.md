# crew

crew gives Claude Code and Codex shared instructions, skills, Kitty workers
and private machine-local memory. It helps agents carry decisions and lessons
across sessions and repositories.

## Requirements

Use Nix with flakes enabled, SSH access to this private repository, Kitty for
worker tabs and a configured Claude Code or Codex CLI.

## Install

```sh
nix profile add git+ssh://git@github.com/Dauno/crew
```

## Use

Run either CLI in the current repository:

```sh
crew claude
crew codex
```

Outside a remote-controllable Kitty session, `crew` opens its own Kitty
window. Ask the agent to open workers and describe their tasks. The agent uses
the `nodes` skill and helper to open Claude Code or Codex workers as Kitty
tabs. Workers send completion notices to their parent.

Helper reference:

```sh
crew-nodes spawn \
  --name reviewer --cli claude --cwd "$PWD" --task review [-- ARGS...]
```

`--task` takes a short label, such as `review`. It identifies the task in
`$CREW_RUNS/<task>/` and the worker's `CREW_TASK` variable. Arguments after
`--` pass unchanged to the CLI. Pass them only when the human requests a model
or option; otherwise, workers use their CLI's default model.

## Memory and permissions

Memory stays on each machine. By default, it lives at
`~/.local/share/crew/memory`; it follows `$XDG_DATA_HOME` when set. Memory has
global, machine and repository scopes. The coordinator writes entries;
workers propose them. The human's current request takes precedence.

Claude Code's human session keeps confirmation prompts; a settings rule
permits the nodes helper. The human's Codex session runs with
`--sandbox danger-full-access`. Workers run without confirmation prompts by
default. Set `CREW_UNATTENDED_WORKERS=0` before launching crew to require
prompts for workers. The human's session keeps its usual permissions.

CLI provider settings, including Vertex URLs, stay in the CLI's own
configuration. crew never passes model, provider or credential settings. Its
default instructions forbid pushing, opening PRs, merging, or acting on
production or shared environments without a human request.

## Develop

Run a local checkout with either CLI:

```sh
nix run ~/Projects/crew -- claude
nix run ~/Projects/crew -- codex
nix flake check
```

Live tests require a desktop Kitty session. Scripts in `tests/live/` start
their own hidden Kitty and do not use the human's windows.

See `AGENTS.md` and the skills for contracts and details.

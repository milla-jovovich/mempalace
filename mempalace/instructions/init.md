# MemPalace Init

Guide the user through a complete MemPalace setup. The goal is a working
bootstrap, not just an installed package.

## Step 1: Check Python version

Run `python3 --version` (or `python --version` on Windows) and confirm the
version is 3.9 or higher. If Python is not found or the version is too old,
tell the user they need Python 3.9+ installed and stop.

## Step 2: Check if mempalace is already installed

Run `pip show mempalace`. If it is already present, report the installed
version and skip to Step 4.

## Step 3: Install mempalace

Run `pip install mempalace`.

If that fails, try these fallbacks in order:
1. `pip3 install mempalace`
2. `python -m pip install mempalace` (or `python3 -m pip install mempalace`)
3. If the error is about native build tools, explain the missing prerequisite
   clearly, then retry
4. If all attempts fail, stop and report the exact error

## Step 4: Ask for project directory

Ask which directory should be initialized. Offer the current working directory
as the default and wait for the user's answer.

## Step 5: Run guided init

Run `mempalace init <dir>`.

Explain that init now does four things:
- seeds the onboarding/entity registry
- writes `aaak_entities.md`, `critical_facts.md`, `wing_config.json`, and
  `identity.txt`
- scaffolds the default specialist agents in `~/.mempalace/agents/`
- detects rooms for the project-local mining setup

If init fails, stop and report the error.

## Step 6: Configure the host integration

Choose the setup that matches the user's environment:

- **Codex**: make sure `.codex-plugin/` exists in the repo root and tell the
  user to start Codex from that repo root so the plugin is discovered
- **Claude / MCP hosts**: show `mempalace mcp` and use the printed server
  command

If host integration fails, report the error but keep going if the local CLI is
working.

## Step 7: Verify installation

Run `mempalace status` and confirm the palace is readable. If possible, also
mention that `mempalace mcp` prints the exact server command for manual wiring.

## Step 8: Show next steps

Suggest the most useful follow-ups:
- `/mempalace:mine` to ingest a project or conversation export
- `/mempalace:search` to query stored memories
- `mempalace_list_agents` once the MCP tools are connected

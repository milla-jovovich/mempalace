# MemPalace rebrand and compile plan

This plan assumes you want a working fork that conforms to your package, command, plugin, launch, storage, and taxonomy conventions.

## Objective

Produce a fork that:

1. uses your package, command, plugin, and state-directory conventions
2. preserves upstream ingest, search, and MCP behavior unless intentionally changed
3. compiles, installs, and launches cleanly across CLI, hooks, and plugin surfaces
4. gives you one central config file for future convention changes

## Recommended execution order

### Step 1 — package identity

Change:

- package directory name
- `project.name` in `pyproject.toml`
- script entrypoint names in `pyproject.toml`
- version source consistency if you keep `version.py`

Reason: everything else depends on the import path and command surface being stable.

### Step 2 — runtime storage identity

Change:

- hidden app dir replacing `~/.mempalace`
- default palace path
- hook state dir
- entity and people map paths
- KG DB path
- export default paths if any

Reason: you want all state to land under your convention before testing begins.

### Step 3 — collection and backend identity

Change:

- drawer collection name
- compressed collection name
- closet collection name if present
- any Chroma metadata assumptions that include naming

Reason: this isolates your fork from upstream local data.

### Step 4 — launch surfaces

Change:

- `.claude-plugin/.mcp.json`
- `.claude-plugin/plugin.json`
- `.codex-plugin/plugin.json`
- `.codex-plugin/hooks.json`
- shell hooks under `hooks/`

Reason: launch contracts are the most fragile part of the user experience.

### Step 5 — taxonomy and behavior

Change:

- default wings
- hall keywords
- onboarding prompts
- room detector rules
- entity detector conventions
- general extractor conventions

Reason: this is where your conventions become operational instead of cosmetic.

### Step 6 — docs and public surface

Change:

- README
- website docs
- plugin READMEs
- contribution docs
- any example commands

Reason: do this after runtime is stable so docs reflect the real fork.

## Compile plan

### Install

```bash
python -m pip install -e ".[dev]"
```

### Verify package entrypoints

```bash
python -m <your_package>.cli --help
<your_command> --help
```

### Run lint and tests

```bash
ruff check .
ruff format --check .
python -m pytest tests/ -v --ignore=tests/benchmarks
```

### Smoke-test runtime

```bash
<your_command> init <dir>
<your_command> mine <dir>
<your_command> search "test query"
<your_command> wake-up
python -m <your_package>.mcp_server --help
```

## High-risk files

### Critical
- `pyproject.toml`
- `mempalace/config.py`
- `mempalace/palace.py`
- `mempalace/cli.py`
- `mempalace/mcp_server.py`
- `hooks/mempal_save_hook.sh`
- `hooks/mempal_precompact_hook.sh`

### High
- `mempalace/miner.py`
- `mempalace/convo_miner.py`
- `mempalace/normalize.py`
- `mempalace/searcher.py`
- `mempalace/knowledge_graph.py`
- `.claude-plugin/*`
- `.codex-plugin/*`

## Strategy

Use one central convention file and a repeatable rewrite script. Do not hand-edit every string across the repo. The execution kit in `tools/mempalace_execution_kit/` is built for the mechanical part of that rewrite.

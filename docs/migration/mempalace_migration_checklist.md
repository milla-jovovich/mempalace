# MemPalace migration checklist

This checklist is for folding MemPalace into your conventions without breaking ingest, search, hooks, packaging, or MCP integrations.

## Phase 0 — freeze the baseline

- [ ] Pin a source commit or release tag for your fork.
- [ ] Snapshot the repo before any rename work.
- [ ] Record the current package name, CLI command, MCP module path, hidden state dir, collection names, and plugin names.
- [ ] Run the current test suite and save the result as the baseline.
- [ ] Decide whether ChromaDB and SQLite remain unchanged.

## Phase 1 — convention decisions

Decide these before touching code:

- [ ] target Python package directory name
- [ ] target package name
- [ ] target CLI command name
- [ ] target hidden app dir replacing `~/.mempalace`
- [ ] target MCP server name
- [ ] target plugin name for Claude/Codex
- [ ] target collection names for drawers, compressed, and closets
- [ ] target repository URLs
- [ ] target interpreter policy for hooks and plugin launchers
- [ ] target wing and hall taxonomy
- [ ] target onboarding defaults
- [ ] whether optional LLM closet regeneration stays enabled

## Phase 2 — hard runtime surfaces first

Change these before docs or branding:

- [ ] `pyproject.toml`
- [ ] `mempalace/config.py`
- [ ] `mempalace/palace.py`
- [ ] `mempalace/cli.py`
- [ ] `mempalace/mcp_server.py`
- [ ] `mempalace/searcher.py`
- [ ] `mempalace/knowledge_graph.py`
- [ ] `hooks/mempal_save_hook.sh`
- [ ] `hooks/mempal_precompact_hook.sh`
- [ ] `.claude-plugin/.mcp.json`
- [ ] `.claude-plugin/plugin.json`
- [ ] `.codex-plugin/plugin.json`
- [ ] `.codex-plugin/hooks.json`

## Phase 3 — mechanical rename surfaces

- [ ] rename the Python package directory
- [ ] rewrite imports from `mempalace` to your package name
- [ ] rewrite CLI command mentions
- [ ] rewrite `python -m mempalace...` launch paths
- [ ] rewrite hidden state-dir references
- [ ] rewrite collection names
- [ ] rewrite plugin manifest names and descriptions
- [ ] rewrite docs-site references
- [ ] rewrite repo URLs and homepage fields

## Phase 4 — taxonomy and behavior

- [ ] adjust `DEFAULT_TOPIC_WINGS` and `DEFAULT_HALL_KEYWORDS` in config
- [ ] adjust onboarding default wings
- [ ] adjust entity detection conventions
- [ ] adjust room detection conventions
- [ ] adjust general extraction conventions
- [ ] decide whether BM25/vector weights stay unchanged
- [ ] decide whether AAAK keeps the same name
- [ ] decide whether KG vocabulary stays unchanged

## Phase 5 — portability and compileability

- [ ] remove hardcoded `python3` assumptions from hooks and plugin launch configs
- [ ] standardize interpreter selection through one env var
- [ ] ensure entrypoints in `pyproject.toml` match the renamed package
- [ ] ensure plugin manifests call the renamed module path
- [ ] ensure hook scripts call the renamed CLI/module
- [ ] ensure docs examples use the new command names
- [ ] ensure workflow matrices and lint versions still pass

## Phase 6 — validation

- [ ] run Ruff
- [ ] run unit tests
- [ ] run smoke tests for init, project mining, convo mining, search, wake-up, MCP launch, and hook invocation
- [ ] scan for stale `mempalace` literals
- [ ] scan for stale `.mempalace` literals
- [ ] scan for stale `python3` launch assumptions

## Phase 7 — packaging and docs

- [ ] update `README.md`
- [ ] update `CLAUDE.md`
- [ ] update `AGENTS.md`
- [ ] update `CONTRIBUTING.md`
- [ ] update website docs
- [ ] update plugin READMEs
- [ ] update changelog and roadmap

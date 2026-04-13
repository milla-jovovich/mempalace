<div align="center">

<img src="assets/mempalace_logo.png" alt="MemPalace" width="280">

# MemPalace

**Persistent, searchable memory for AI assistants. Local. Free. No API key.**

[![][version-shield]][release-link]
[![][python-shield]][python-link]
[![][license-shield]][license-link]
[![][discord-shield]][discord-link]

</div>

---

> **⚠ Important:** There are [fake MemPalace websites](NOTICES.md) distributing malware. MemPalace has no website — install only from [GitHub](https://github.com/milla-jovovich/mempalace) or [PyPI](https://pypi.org/project/mempalace/). See also [errata and corrections from launch week](NOTICES.md).

---

## What MemPalace does

MemPalace stores your AI conversations and project files in a local vector database (ChromaDB), organized into a navigable structure of **wings** (projects/people), **rooms** (topics), and **drawers** (verbatim text). A companion **knowledge graph** (SQLite) tracks entity relationships with temporal validity.

Your AI assistant connects to MemPalace via [MCP](docs/mcp-server.md) and gets persistent memory across sessions — it can search past conversations, recall decisions, and track how facts change over time. Everything runs locally on your machine.

**96.6% R@5 on [LongMemEval](benchmarks/BENCHMARKS.md)** in raw verbatim mode, zero API calls.

## Install

```bash
pip install mempalace
```

Requires Python 3.9+. Dependencies: `chromadb>=0.5.0`, `pyyaml>=6.0`. No internet needed after install.

## Quick start

```bash
# 1. Detect rooms from your project structure
mempalace init ~/projects/myapp

# 2. Mine project files into the palace
mempalace mine ~/projects/myapp

# 3. Mine conversation exports (Claude, ChatGPT, Slack, Codex)
mempalace mine ~/chats/ --mode convos

# 4. Search
mempalace search "why did we switch to GraphQL"
```

Then connect your AI assistant:

```bash
# Claude Code
claude mcp add mempalace -- mempalace mcp run

# Gemini CLI (use absolute path to python for venvs)
gemini mcp add mempalace mempalace mcp run --scope user
```

Now ask your AI anything about your past work — it searches the palace automatically.

→ Full walkthrough: [docs/getting-started.md](docs/getting-started.md)

## How the palace is organized

MemPalace uses a spatial metaphor to organize memories. This isn't cosmetic — the structure drives metadata filtering that improves retrieval accuracy.

```
WING (project or person)
  └── ROOM (topic: auth, billing, deploy, ...)
        └── DRAWER (verbatim text chunk)
```

- **Wings** — one per project, person, or domain. `myapp`, `kai`.
- **Rooms** — specific topics within a wing. `auth-migration`, `pricing-model`.
- **Tunnels** — when the same room appears in multiple wings, a tunnel connects them. The room `auth-migration` in both `kai` and `myapp` means Kai worked on that topic in that project.
- **Halls** — memory type corridors: `hall_facts`, `hall_events`, `hall_discoveries`, `hall_preferences`, `hall_advice`.
- **Drawers** — the actual verbatim text. Never summarized.

Filtering by wing + room yields up to +34% retrieval improvement over unfiltered search (measured on 22,000+ real memories, using standard ChromaDB metadata filtering).

→ Architecture details: [docs/architecture.md](docs/architecture.md)

## Memory layers

MemPalace loads memory in layers to minimize token usage:

| Layer | What | Size | When |
|-------|------|------|------|
| **L0** | Identity — who is this AI? | ~50 tokens | Always loaded |
| **L1** | Top facts from the palace | ~500–800 tokens | Always loaded |
| **L2** | On-demand wing/room retrieval | ~200–500 each | When topic comes up |
| **L3** | Full semantic search | Unlimited | When explicitly asked |

Wake-up loads L0 + L1 (~600–900 tokens). Deep searches fire only when needed.

```bash
mempalace wake-up                    # L0 + L1 context
mempalace wake-up --wing myapp       # project-specific wake-up
```

→ Layer system details: [docs/architecture.md](docs/architecture.md)

## MCP server

MemPalace exposes 19 tools via [MCP](https://modelcontextprotocol.io/) (Model Context Protocol). Once connected, your AI assistant can read, write, and search the palace without manual commands.

**Read tools:** `mempalace_status`, `mempalace_search`, `mempalace_list_wings`, `mempalace_list_rooms`, `mempalace_get_taxonomy`, `mempalace_check_duplicate`, `mempalace_get_aaak_spec`

**Write tools:** `mempalace_add_drawer`, `mempalace_delete_drawer`

**Knowledge graph:** `mempalace_kg_query`, `mempalace_kg_add`, `mempalace_kg_invalidate`, `mempalace_kg_timeline`, `mempalace_kg_stats`

**Navigation:** `mempalace_traverse`, `mempalace_find_tunnels`, `mempalace_graph_stats`

**Agent diary:** `mempalace_diary_write`, `mempalace_diary_read`

→ Full tool reference and setup: [docs/mcp-server.md](docs/mcp-server.md)

## Knowledge graph

Temporal entity-relationship triples stored in SQLite. Track facts that change over time.

```python
from mempalace.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()
kg.add_triple("Kai", "works_on", "Orion", valid_from="2025-06-01")
kg.add_triple("Maya", "assigned_to", "auth-migration", valid_from="2026-01-15")

# What's true about Kai right now?
kg.query_entity("Kai")

# What was true in January?
kg.query_entity("Maya", as_of="2026-01-20")

# Mark a fact as ended
kg.invalidate("Kai", "works_on", "Orion", ended="2026-03-01")
```

→ Full API and schema: [docs/knowledge-graph.md](docs/knowledge-graph.md)

## Mining

Two ingest modes, six input formats.

**Project mining** scans directories for code, docs, and notes. Chunks by paragraph, respects `.gitignore`.

**Conversation mining** parses chat exports (Claude Code JSONL, Claude.ai JSON, ChatGPT JSON, Slack JSON, OpenAI Codex CLI JSONL, plain text). Chunks by exchange pair (question + answer).

```bash
mempalace mine ~/projects/myapp                              # project files
mempalace mine ~/chats/ --mode convos --wing myapp           # conversations
mempalace mine ~/chats/ --mode convos --extract general      # auto-classify into 5 memory types
mempalace split ~/chats/                                     # split mega-files first
```

→ Mining guide: [docs/mining.md](docs/mining.md)

## Auto-save hooks

Shell hooks for Claude Code and Gemini CLI that trigger automatic memory saves during work. The save hook fires every 15 messages; the precompact hook fires before context compression.

```bash
# Install hooks (Claude Code)
# Add to .claude/settings.local.json — see docs/hooks.md for full config
```

→ Hook setup: [docs/hooks.md](docs/hooks.md)

## AAAK dialect (experimental)

A lossy abbreviation system for compressing repeated entities into fewer tokens. Entity codes, structural markers, sentence truncation. Readable by any LLM without a decoder.

**Current status:** AAAK regresses LongMemEval vs raw mode (84.2% R@5 vs 96.6%). The 96.6% headline is from raw verbatim mode, not AAAK. AAAK is a separate compression layer, not the storage default. It may save tokens at scale with many repeated entities; it does not save tokens on short text.

→ Dialect spec and status: [docs/aaak.md](docs/aaak.md)

## Benchmarks

| Benchmark | Mode | Score | API Calls |
|-----------|------|-------|-----------|
| LongMemEval R@5 | Raw (ChromaDB) | **96.6%** | Zero |
| LongMemEval R@5 | Hybrid + Haiku rerank | **100%** | ~500 |
| LoCoMo R@10 | Raw, session level | **60.3%** | Zero |

Runners and full methodology in [benchmarks/](benchmarks/). See [BENCHMARKS.md](benchmarks/BENCHMARKS.md) for detailed results.

## Documentation

| Document | Contents |
|----------|----------|
| [Getting started](docs/getting-started.md) | Install, first palace, first search, MCP setup |
| [Architecture](docs/architecture.md) | Palace model, memory layers, data flow |
| [Mining](docs/mining.md) | Project files, conversations, formats, splitting |
| [Searching](docs/searching.md) | CLI search, programmatic API, filtering |
| [MCP server](docs/mcp-server.md) | Setup, all 19 tools, integration guides |
| [Knowledge graph](docs/knowledge-graph.md) | Temporal triples, queries, Python API |
| [Hooks](docs/hooks.md) | Auto-save for Claude Code and Gemini CLI |
| [Configuration](docs/configuration.md) | Config files, env vars, defaults |
| [CLI reference](docs/cli-reference.md) | Every command, every flag |
| [Python API](docs/python-api.md) | Programmatic usage |
| [AAAK dialect](docs/aaak.md) | Compression format, status, limitations |
| [Notices](NOTICES.md) | Security warnings, launch errata |

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and guidelines.

## License

MIT — see [LICENSE](LICENSE).

<!-- Link Definitions -->
[version-shield]: https://img.shields.io/badge/version-3.1.0-4dc9f6?style=flat-square&labelColor=0a0e14
[release-link]: https://github.com/milla-jovovich/mempalace/releases
[python-shield]: https://img.shields.io/badge/python-3.9+-7dd8f8?style=flat-square&labelColor=0a0e14&logo=python&logoColor=7dd8f8
[python-link]: https://www.python.org/
[license-shield]: https://img.shields.io/badge/license-MIT-b0e8ff?style=flat-square&labelColor=0a0e14
[license-link]: https://github.com/milla-jovovich/mempalace/blob/main/LICENSE
[discord-shield]: https://img.shields.io/badge/discord-join-5865F2?style=flat-square&labelColor=0a0e14&logo=discord&logoColor=5865F2
[discord-link]: https://discord.com/invite/ycTQQCu6kn

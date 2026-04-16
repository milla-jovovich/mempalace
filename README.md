<div align="center">

<img src="assets/mempalace_logo.png" alt="MemPalace" width="280">

# MemPalace (jphein fork)

**JP's production fork of [milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace)**

[![version-shield]][release-link]
[![python-shield]][python-link]
[![license-shield]][license-link]

</div>

---

Fork of [MemPalace v3.3.0](https://github.com/milla-jovovich/mempalace/releases/tag/v3.3.0). Running in production with 134K+ drawers across 60+ rooms. See upstream README for full feature docs.

**[Fork direction](docs/fork-direction.md)** — competitive analysis, what we learned, roadmap.

## Fork Changes

What this fork adds beyond upstream v3.3.0:

### Still Ahead of Upstream

| Area | Change | Files |
|------|--------|-------|
| **Reliability** | Epsilon mtime comparison (`abs() < 0.01` vs `==`) prevents re-mining | `palace.py`, `miner.py` |
| **Reliability** | Stale HNSW mtime detection + `mempalace_reconnect` MCP tool | `mcp_server.py` |
| **Performance** | `bulk_check_mined()` — paginated pre-fetch for concurrent mining | `palace.py`, `miner.py` |
| **Performance** | Graph cache — 60s TTL, invalidated on writes | `palace_graph.py` |
| **Performance** | L1 importance pre-filter — `importance >= 3` first, full scan fallback | `layers.py` |
| **Search** | `max_distance` parameter (cosine distance threshold, default 1.5) | `mcp_server.py`, `searcher.py` |
| **Hooks** | Silent save mode — direct Python API, deterministic, zero data loss | `hooks_cli.py` |
| **Hooks** | Tool output mining — per-tool formatting strategies in `normalize.py` | `normalize.py` |
| **Features** | Diary wing routing — derive project wing from transcript path | `hooks_cli.py`, `mcp_server.py` |

### Merged Upstream (in v3.3.0)

- BLOB seq_id migration repair (#664)
- `--yes` flag for init (#682)
- Unicode `sanitize_name` (#683)
- VAR_KEYWORD kwargs check (#684)
- New MCP tools + export (via #667)

### Superseded by Upstream

- Hybrid keyword fallback (`$contains`) — upstream shipped Okapi-BM25 (60/40 blend)
- Batch ChromaDB writes — upstream has file-level locking for concurrent agents
- Inline transcript mining in hooks — upstream uses `mempalace mine` in background

## Open Upstream PRs

| PR | Status | Description |
|----|--------|-------------|
| [#629](https://github.com/milla-jovovich/mempalace/pull/629) | needs rework | Batch writes, concurrent mining |
| [#632](https://github.com/milla-jovovich/mempalace/pull/632) | needs rework | Repair, purge, --version |
| [#659](https://github.com/milla-jovovich/mempalace/pull/659) | rebase needed | Diary wing parameter |
| [#660](https://github.com/milla-jovovich/mempalace/pull/660) | rebase needed | L1 importance pre-filter |
| [#661](https://github.com/milla-jovovich/mempalace/pull/661) | rebase needed | Graph cache with write-invalidation |
| [#673](https://github.com/milla-jovovich/mempalace/pull/673) | needs rework | Deterministic hook saves |
| [#681](https://github.com/milla-jovovich/mempalace/pull/681) | rebase needed | Unicode checkmark → ASCII |

Closed: #626, #633, #662 (superseded by BM25), #663 (upstream wrote #757), #738 (docs stale).

## Setup

```bash
git clone https://github.com/jphein/mempalace.git
cd mempalace
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"

mempalace init ~/Projects --yes
mempalace mine ~/Projects/myproject
mempalace status
```

## Development

```bash
source venv/bin/activate
python -m pytest tests/ -x -q           # 858 tests expected
mempalace status                         # palace health
ruff check . && ruff format --check .    # lint + format
```

## License

MIT — see [LICENSE](LICENSE).

<!-- Link Definitions -->
[version-shield]: https://img.shields.io/badge/version-3.3.0-4dc9f6?style=flat-square&labelColor=0a0e14
[release-link]: https://github.com/MemPalace/mempalace/releases
[python-shield]: https://img.shields.io/badge/python-3.9+-7dd8f8?style=flat-square&labelColor=0a0e14&logo=python&logoColor=7dd8f8
[python-link]: https://www.python.org/
[license-shield]: https://img.shields.io/badge/license-MIT-b0e8ff?style=flat-square&labelColor=0a0e14
[license-link]: https://github.com/jphein/mempalace/blob/main/LICENSE

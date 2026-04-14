# Changelog

All notable changes to [MemPalace](https://github.com/MemPalace/mempalace) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/).

---

## [Unreleased] — v3.3.0 (on develop)

### New Features
- Closet layer — a compact searchable index of pointers to verbatim drawers, enabling fast topical lookup without reading all content (#788)
- BM25 hybrid search — closets boost ranking, drawers remain the source of truth (#795, #829)
- Entity metadata on every drawer for filterable search (#829)
- Diary ingest — day-based rooms for conversation transcripts (#829)
- Cross-wing tunnels — explicit links between rooms in different wings for multi-project agents (#829)
- Drawer-grep — returns the best-matching chunk plus adjacent context drawers (#829)
- Offline fact checker against the entity registry and knowledge graph (#829)
- LLM-based closet regeneration — optional, bring-your-own endpoint, no mandatory API key (#793)
- Hall detection — routes drawer content to `emotions` / `technical` / `family` / `memory` / `identity` / `consciousness` / `creative` halls, enabling hall-based graph connectivity within wings (#835)

### Bug Fixes
- Set `hnsw:space=cosine` metadata on all collection creation sites — fixes broken similarity scoring under ChromaDB's default L2 distance (#807, #218)
- File-level locking prevents duplicate drawers when agents mine the same file concurrently (#784, #826)
- Hybrid closet+drawer retrieval — closets boost ranking, never gate results (#795)
- Stop hooks from making agents write in chat — saves tokens on every turn (#786)
- Strip system tags, hook output, and Claude UI chrome from drawers before filing (#785)
- Verbatim-safe `strip_noise` scoped to Claude Code JSONL only (#785)
- Prevent diary entry ID collisions via microsecond timestamp and full content hash (#819)
- Auto-rebuild stale drawers via `NORMALIZE_VERSION` schema gate
- Enforce atomic topics in closets and extract richer pointers
- Sync `version.py` to match `pyproject.toml` (#820)
- Remove unused `main` import from `mempalace/__init__.py` (#827)
- README audit — fix 7 stale claims (tool count, version badge, wake-up token cost, `dialect.py` lossless disclaimer, `pyproject.toml` version) with 42 regression-guard tests (#835)

### Improvements
- Optimize entity detection with regex caching and pre-compilation (#828)
- Extract locked filing block into helper to keep `mine_convos` under C901 complexity

### Documentation
- Add `docs/CLOSETS.md` — closet layer overview
- Fix stale `milla-jovovich/*` org URLs in website and plugin manifests (#787)
- Fix remaining stale org URLs in contributor docs (#808)

### Internal
- Add test coverage for `mine_lock`, closets, entity metadata, BM25, and diary
- Verify `mine_lock` via disjoint critical-section intervals
- Serialize `mine_lock` concurrency test with multiprocessing
- Make diary state path assertion platform-neutral
- Add `TestTunnels` coverage for cross-wing tunnel operations
- Ruff format with CI-pinned version (0.4.x); format `mempalace/palace.py`

---

## [3.2.0] — 2026-04-12

### Packaging
- Remove `chromadb<0.7` upper bound — unblocks installs against chromadb 1.x palaces (#690)
- Bump version to 3.2.0 across `pyproject.toml`, `mempalace/version.py`, README badge, and OpenClaw SKILL (#761)

### Security
- Harden palace deletion, WAL redaction, and MCP search input handling (#739)
- Consistent input validation, argument whitelisting, concurrency safety, and WAL fixes (#647)
- Remove hardcoded credential paths from benchmark runners (#177)
- Remove global SSL verification bypass in convomem_bench (#176)

### Bug Fixes
- Parse Claude.ai privacy export with `messages` key and sender field (#685, #677)
- Detect mtime changes in `_get_client` to prevent stale HNSW index (#757)
- Hash full content in `tool_add_drawer` drawer ID — stable re-mines (#716)
- Remove 10k drawer cap from status display (#707, #603)
- Correct typo in entity_detector interactive classification prompt (#755)
- Prevent convo_miner from re-processing 0-chunk files on every run (#732, #654)
- Remove silent 8-line AI response truncation in convo_miner (#708, #692)
- Store full AI response in convo_miner exchange chunking (#695)
- Fix `mine --dry-run` TypeError on files with room=None (#687, #586)
- Skip arg whitelist for handlers accepting `**kwargs` (#684, #572)
- Allow Unicode in `sanitize_name()` — Latvian, CJK, Cyrillic (#683, #637)
- Auto-repair BLOB seq_ids from chromadb 0.6→1.5 migration (#664)
- Remove no-op `ORT_DISABLE_COREML` env var (#653, #397)
- Disambiguate hook block reasons to name MemPalace explicitly (#666)
- Use epsilon comparison for mtime to prevent unnecessary re-mining (#610)
- Correct token count estimate in compress summary (#609)
- Implement MCP ping health checks (#600)
- Align `cmd_compress` dict keys with `compression_stats()` return values (#569)
- Skip unreachable reparse points in `detect_rooms_from_folders` on Windows (#558)
- Prevent HNSW index bloat from duplicate `add()` calls (#544, #525)
- Purge stale drawers before re-mine to avoid hnswlib segfault (#544)
- Mitigate system prompt contamination in search queries (#385, #333)
- Count Codex `user_message` turns in `_count_human_messages` (#373, #347)
- Paginate large collection reads and surface errors in MCP tools (#371, #339, #338)
- Expand `~` in split command directory argument (#361)
- Ignore `wait_for_previous` argument to support Gemini MCP clients (#322)
- Close KnowledgeGraph SQLite connections in test fixtures (#450)
- Remove duplicate cache variable declarations in mcp_server.py (#449)
- Add `--yes` flag to init instructions for non-interactive use (#682, #534)
- Add `mcp` command with setup guidance (#315)

### New Features
- i18n support — 8 languages (en, es, fr, de, ja, ko, zh-CN, zh-TW) (#718)
- New MCP tools: get/list/update drawer, hook settings, export (#667, #635)
- `mempalace migrate` — recover palaces from different ChromaDB versions (#502)
- Add OpenClaw/ClawHub skill (#491)
- Backend seam for pluggable storage backends (#413)

### Improvements
- Disable broken auto-bump workflow (#414)
- Improve agent readiness — AGENTS.md, dependabot, CODEOWNERS, labels (#497)

### Documentation
- Add CLAUDE.md and mission/principles to AGENTS.md (#720)
- Add VitePress documentation site (#439)
- Add warning about fake MemPalace websites (#598)
- Fix stale org URLs and PR branch target in contributor docs (#679)
- Fix misaligned architecture diagram (#734, #733)
- Add ROADMAP.md — v3.1.1 stability patch and v4.0.0-alpha plan

### Internal
- ruff format convo_miner.py (#741)
- ruff format all Python files (#675)
- CI: trigger tests on develop branch PRs and pushes (#674)
- CI: fix GitHub Pages publishing (#691)

---

## [3.1.0] — 2026-04-09

### Security
- Harden inputs, fix shell injection, optimize DB access (#387)
- Sanitize SESSION_ID in save hook to prevent path traversal (#141)
- Sanitize error responses and remove `sys.exit` from library code (#139)
- Shell injection fix in hooks, Claude Code mining, chromadb pin (#114)

### Bug Fixes
- MCP null args hang, repair infinite recursion, OOM on large files (#399)
- Release ChromaDB handles before rmtree on Windows (#392)
- Use `os.utime` in mtime test for Windows compatibility (#392)
- Negotiate MCP protocol version instead of hardcoding (#324)
- Use upsert and deterministic IDs to prevent data stagnation (#140)
- Make `drawer_id` deterministic for idempotent writes (#387)
- Honest AAAK stats — word-based token estimator, lossy labels (#147)
- Room detection checks keywords against folder paths (#145)
- Use actual detected room in mine summary stats (#165)
- Honour `--palace` flag in mcp_server (#264)
- Preserve default KG path when `--palace` not passed (#270)
- `--yes` flag skips all interactive prompts in init (#123)
- Repair command, split args, Claude export, room keywords (#119)
- Replace Unicode separator in convo_miner.py for Windows compatibility (#129)
- Coerce MCP integer arguments to native Python int (#84)
- Batch ChromaDB reads to avoid SQLite variable limit (#66)
- Respect nested .gitignore rules during mining (#78)
- Narrow bare `except Exception` to specific types where safe (#54)
- Mark MD5 as non-security in miner drawer ID generation (#53)
- Remove dead code and duplicate set items in entity_registry.py (#42)
- Silence ChromaDB telemetry warnings and CoreML segfault on Apple Silicon (#236)
- Unify package and MCP version reporting (#16)
- Fix broken AAAK Dialect link in README (#238)
- Update input prompt for entity confirmation (#83)
- Preserve CLI exit codes, log tracebacks, sanitize search errors (#139)
- Enable SQLite WAL mode and add consistent LIMIT to KG timeline (#136)
- Add limit=10000 safety cap to all unbounded ChromaDB `.get()` calls (#137)
- Re-mine modified files, idempotent `add_drawer`, cleanup ChromaDB handles (#140)
- Resolve formatting, regression logic, and pytest defaults (#270)
- Use `parse_known_args` to allow importing mcp_server during pytest (#270)

### New Features
- Package MemPalace as standard Claude and Codex plugins (#270)
- Add OpenAI Codex CLI JSONL normalizer (#61)
- Add Codex plugin support with hooks, commands, and documentation (#270)
- Add command documentation for help, init, mine, search, and status (#270)

### Improvements
- Cache ChromaDB `PersistentClient` instead of re-instantiating per call (#135)
- Tighten chromadb version range and add `py.typed` marker (#142)
- Consolidate split known-names config loading (#22)
- CI: add separate jobs for Windows and macOS testing
- CI: Upgrade GitHub Actions for Node 24 compatibility (#55)

### Documentation
- Add Gemini CLI setup guide and integration section (#106)
- Add beginner-friendly hooks tutorial (#103)
- Align MCP setup examples with shipped server (#21)
- Honest README update — own the mistakes, fix the claims

### Internal
- Expand test coverage from 20 to 92 tests, migrate to uv (#131)
- Add scale benchmark suite — 106 tests (#223)
- Increase test coverage from 30% to 85%, fix Windows encoding bugs (#281)
- Add WAL mode and entity timeline limit assertions
- Add coverage for `file_already_mined` mtime check

---

## [3.0.0] — 2026-04-06

Initial public release.

- Palace architecture with day-based rooms, drawers (verbatim), and closets (searchable index)
- AAAK compression dialect for memory folding
- Knowledge graph with entity detection and timeline queries
- MCP server for Claude, Codex, and Gemini integration
- CLI: `init`, `mine`, `search`, `status`, `compress`, `repair`, `split`
- Benchmark suite with recall and scale tests
- README with MCP flow, local model flow, and specialist agent documentation

---

[Unreleased]: https://github.com/MemPalace/mempalace/compare/v3.2.0...HEAD
[3.2.0]: https://github.com/MemPalace/mempalace/compare/v3.1.0...v3.2.0
[3.1.0]: https://github.com/MemPalace/mempalace/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/MemPalace/mempalace/releases/tag/v3.0.0

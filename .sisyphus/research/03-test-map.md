# Test Suite Map — MemPalace 3.1.0

Source: `explore` task `bg_33c81d66` (3m06s). Full map of all 38 test files.

## Totals
- Unit tests (tests/*.py): 25 files, ~315 test functions
- Benchmark tests (tests/benchmarks/*.py): 9 files, ~68 tests (all marker-gated)
- Infrastructure: 2 files (data_generator, report) + 2 conftests

Default pytest run excludes `benchmark and slow and stress` markers → only ~315 unit tests.

## conftest fixtures

### `tests/conftest.py`
| Fixture | Scope | Autouse | What |
|---|---|---|---|
| `_isolate_home` | session | **yes** | Redirects HOME/USERPROFILE/HOMEDRIVE/HOMEPATH to temp; restores on teardown |
| `_reset_mcp_cache` | function | **yes** | Clears `_client_cache`/`_collection_cache` in mcp_server before & after |
| `tmp_dir` | function | no | `tempfile.mkdtemp(prefix="mempalace_test_")` |
| `palace_path` | function | no | `{tmp_dir}/palace/` |
| `config` | function | no | `MempalaceConfig(config_dir=...)` with `config.json` containing palace_path |
| `collection` | function | no | empty ChromaDB `mempalace_drawers` collection |
| `seeded_collection` | function | no | 4 drawers: 2 in project/backend, 1 project/frontend, 1 notes/planning |
| `kg` | function | no | empty `KnowledgeGraph` |
| `seeded_kg` | function | no | 4 entities (Alice, Max, swimming, chess) + 5 triples (including 1 expired) |

### `tests/benchmarks/conftest.py`
Adds `--bench-scale`, `--bench-report`, and benchmark-specific fixtures.

## Per-file test counts

| File | Count | Focus | ChromaDB | Mocks |
|---|---|---|---|---|
| test_cli.py | 33 | CLI dispatch, 11 subcommands | **mocked** | heavy |
| test_mcp_server.py | 25 | MCP protocol + 15 tools directly | **real** | monkeypatch _config/_kg |
| test_normalize.py | 32 | 6 chat formats + large-file reject | — | patch getsize, spellcheck |
| test_onboarding.py | 32 | Wizard + auto-detect | — | patch input |
| test_layers.py | 30 | L0/L1/L2/L3/MemoryStack | mocked | patch PersistentClient |
| test_knowledge_graph.py | 17 | Triples, WAL, temporal | — | — |
| test_palace_graph.py | 17 | BFS, tunnels, fuzzy match | mocked | sys.modules chromadb=Mock |
| test_split_mega_files.py | 17 | Mega file splitter | — | monkeypatch caches |
| test_miner.py | 13 | Mine + gitignore (deep coverage) | **real** | — |
| test_entity_registry.py | 20 | Registry, Wikipedia, disambiguation | — | patch wiki lookup |
| test_room_detector_local.py | 15 | Folder→room, yaml | — | patch input |
| test_general_extractor.py | 19 | 80 markers, sentiment | — | — |
| test_entity_detector.py | 18 | Scoring, classification | — | patch input |
| test_dialect.py | 16 | AAAK compression | — | — |
| test_spellcheck.py | 16 | Edit distance, name-aware | — | patch speller |
| test_searcher.py | 14 | Search API + CLI | **real**/mocked | patch PersistentClient |
| test_hooks_cli.py | 21 | Hooks + **security sanitize** | — | patch Popen |
| test_convo_miner_unit.py | 12 | chunk, detect_room, scan | — | — |
| test_convo_miner.py | 1 | Mine convos end-to-end | **real** | — |
| test_knowledge_graph_extra.py | 7 | seed_from_entity_facts | — | — |
| test_spellcheck_extra.py | 5 | EntityRegistry.load | — | patch registry |
| test_config.py | 4 | Defaults, env override | — | — |
| test_config_extra.py | 10 | Bad JSON, people_map | — | — |
| test_instructions_cli.py | 4 | .md printer | — | patch paths |
| test_version_consistency.py | 2 | pyproject vs __version__ | — | — |

## MCP tools coverage

15/19 tools directly tested in test_mcp_server.py:
1. mempalace_status ✓
2. mempalace_list_wings ✓
3. mempalace_list_rooms ✓
4. mempalace_get_taxonomy ✓
5. mempalace_search ✓
6. mempalace_add_drawer ✓
7. mempalace_delete_drawer ✓
8. mempalace_check_duplicate ✓
9. mempalace_kg_add ✓
10. mempalace_kg_query ✓
11. mempalace_kg_invalidate ✓
12. mempalace_kg_timeline ✓
13. mempalace_kg_stats ✓
14. mempalace_diary_write ✓
15. mempalace_diary_read ✓

Indirectly tested (via underlying module):
16. mempalace_traverse — test_palace_graph.py
17. mempalace_find_tunnels — test_palace_graph.py
18. mempalace_graph_stats — test_palace_graph.py

**Not tested at all**:
19. mempalace_get_aaak_spec — add test in Rust port

## CLI commands tested
- `mempalace` (no args), `status`, `search`, `init`, `mine` (projects + convos + --include-ignored),
  `wake-up`, `split`, `mcp`, `repair`, `compress` (+ --config + dry-run), `hook run`, `instructions`

## Security-relevant tests
- `test_sanitize_strips_dangerous_chars` (hooks_cli) — path traversal `../../etc/passwd`
- `test_sanitize_empty_returns_unknown` — empty/invalid session IDs
- `test_normalize_rejects_large_file` — 600 MB raises IOError
- Benchmarks measure OOM/RSS growth (safety, not security per se)

**Gaps the Rust port should close**:
- SQL injection tests (Python relies on `sqlite3` parameterization — we use `rusqlite` same pattern)
- ChromaDB metadata filter injection (we use typed lancedb WHERE clauses)
- Shell injection in hooks (open issue #110) — Rust port does NOT shell out for hooks
- Coverage for `mempalace_get_aaak_spec` MCP tool

## Global state / env manipulation

| Where | What |
|---|---|
| conftest.py | HOME/USERPROFILE redirected to temp (session-autouse) |
| test_onboarding.py | Sets PYTHONUTF8=1 at module level |
| test_config.py | MEMPALACE_PALACE_PATH set/deleted |
| test_config_extra.py | MEMPAL_PALACE_PATH (legacy) |
| test_hooks_cli.py | patch.dict("os.environ", {"MEMPAL_DIR": ...}) |
| test_cli.py | patch("sys.argv", ...) |

In the Rust port we isolate with `tempfile::TempDir` + a `ConfigBuilder` that accepts an explicit `config_dir` override (exactly as the Python `MempalaceConfig(config_dir=...)` does).

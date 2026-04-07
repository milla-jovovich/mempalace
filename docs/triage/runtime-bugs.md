# Runtime Bug Triage

Date: 2026-04-07

This note captures bugs that were confirmed by direct code inspection and local runtime probes.

## Summary

| Item | Confirmed | Can fix safely | Risk |
| --- | --- | --- | --- |
| `collection_name` config ignored by most runtime modules | Yes | Yes | Low |
| `spellcheck` known-name loader reads the wrong registry shape | Yes | Yes | Low |
| Unicode console glyphs can crash on Windows cp1252 terminals | Yes | Yes | Low |
| Version numbers disagree across package surfaces | Yes | Yes | Low |
| Search UI shows `1 - distance` as similarity and can go negative | Yes | Yes | Low |
| Windows tests fail because Chroma files stay open during cleanup | Yes | Maybe | Medium |

## Confirmed Runtime Bugs

### 1. `collection_name` drift

Status: confirmed

Observed behavior:
- `MempalaceConfig.collection_name` exists and `palace_graph.py` uses it.
- `miner.py`, `convo_miner.py`, `searcher.py`, `layers.py`, and `cli.py` hardcode `mempalace_drawers`.
- A probe using `collection_name = "custom_drawers"` succeeded in `build_graph()` but failed in `search_memories()` because search still looked for `mempalace_drawers`.

Why this is a bug:
- The project exposes `collection_name` as config, so runtime modules are expected to honor it consistently.
- Current behavior creates split-brain storage: some features read the configured collection, others read the default collection.

Can fix now:
- Yes.

Expected fix shape:
- Route all Chroma collection lookups through `MempalaceConfig().collection_name`.
- Keep `mempalace_compressed` separate unless the product explicitly wants that configurable too.

### 2. `spellcheck` loader reads `entities`, registry stores `people`

Status: confirmed

Observed behavior:
- `EntityRegistry` persists names under `people`.
- `_load_known_names()` in `spellcheck.py` iterates `reg._data.get("entities", {})`.
- After seeding `Riley` into the real registry file, `_load_known_names()` still returned an empty set.

Why this is a bug:
- Proper names from onboarding are supposed to be preserved during spell correction.
- The current code never loads those names, so the protection path is broken.

Can fix now:
- Yes.

Expected fix shape:
- Read canonical names and aliases from `people`.
- Preserve backward compatibility if an older registry ever used `entities`.

### 3. Unicode console output can crash on Windows cp1252 terminals

Status: confirmed

Observed behavior:
- Running `mine()` under `PYTHONIOENCODING=cp1252` raised `UnicodeEncodeError`.
- The crash happens on box-drawing and arrow glyph output in console `print()` calls.

Why this is a bug:
- The package claims to work on ordinary local developer machines.
- A CLI should not crash because the terminal encoding is cp1252.

Can fix now:
- Yes.

Expected fix shape:
- Replace decorative glyphs with ASCII in runtime console output, or use a small helper that falls back safely.

### 4. Version mismatch across package surfaces

Status: confirmed

Observed behavior:
- `pyproject.toml` says `3.0.0`.
- `mempalace.__version__` says `2.0.0`.
- MCP server `serverInfo.version` says `2.0.0`.

Why this is a bug:
- Packaging, runtime introspection, and MCP metadata disagree about the same release.
- This can confuse debugging, support, and bug reports.

Can fix now:
- Yes.

Expected fix shape:
- Decide the canonical version and derive the others from it.

### 5. Search UI similarity can go negative

Status: confirmed

Observed behavior:
- `searcher.py` reports `similarity = 1 - distance`.
- In a probe, one returned value was negative.

Why this is a bug:
- The displayed number is labeled as similarity, but it is not normalized or bounded.
- Negative similarity in the UI is misleading even if the retrieval itself is valid.

Can fix now:
- Yes.

Expected fix shape:
- Either expose raw distance, clamp the display, or rename the field to avoid implying cosine similarity.

### 6. Windows test cleanup fails with open Chroma files

Status: confirmed

Observed behavior:
- `pytest` ran with `7 passed, 2 failed`.
- Both failures are Windows cleanup failures in `test_miner.py` and `test_convo_miner.py` while deleting temporary Chroma data.

Why this might be a bug:
- The tests are not reliable on Windows in the current setup.
- This may be a test bug, a client-lifecycle bug, or a Chroma dependency behavior.

Can fix now:
- Maybe.

Why not marked safe yet:
- Need to confirm whether Chroma exposes a supported close or shutdown path.
- A test-only retry wrapper may stabilize CI, but that would not prove the runtime lifecycle is correct.

## Not Included Here

The following items were intentionally kept out of this runtime-bug list because they require product intent, documentation changes, or larger architecture work:
- incremental reindexing semantics
- `L1` and `L2` behavior vs README language
- spell-correcting user content before storage
- halls and closets existing more in docs than in runtime
- AAAK "lossless" claims
- benchmark-specific retrieval logic

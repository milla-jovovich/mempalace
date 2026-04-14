# MemPalace PRs — Deep Technical Dive

> **Purpose:** Complete technical context for all 4 open PRs plus the underlying architecture.
> Written for an iOS developer who wants to understand the Python/ChromaDB system thoroughly.
> Intended as input for Claude Deep Research to generate a comprehensive learning resource.

---

## Part 0: The Architecture — What Is MemPalace?

### The Aristotelian Method of Loci (Memory Palace)

MemPalace is named after the ancient Greek *method of loci* — a mnemonic technique attributed to Simonides of Ceos and refined by Aristotle. In the classical technique, you imagine walking through a familiar building (a "palace"), placing vivid mental images in specific locations (rooms, drawers). To recall information, you mentally retrace your steps through the palace.

MemPalace translates this into software:

| Classical Concept | Software Implementation | Data Structure |
|---|---|---|
| **Palace** | A ChromaDB vector database directory on disk | `~/.mempalace/palace/` |
| **Wing** | A project or domain grouping | String metadata field `wing` on every drawer |
| **Room** | A topic or aspect within a wing | String metadata field `room` on every drawer |
| **Drawer** | One piece of memorized content | A ChromaDB document: text chunk + embedding vector + metadata |
| **Hall** | A connection type between rooms | Edge label in graph traversal |
| **Tunnel** | A room name appearing in multiple wings (cross-domain connection) | Computed dynamically from metadata |
| **Knowledge Graph** | Factual relationships (who/what/when) | SQLite database with entities and temporal triples |

### How It Works at 30,000 Feet

1. **Mining**: You point MemPalace at a directory (code project or conversation exports). It reads files, splits them into chunks, converts each chunk into a 384-dimensional embedding vector (using `all-MiniLM-L6-v2` via ONNX), and stores the text + vector + metadata in ChromaDB.

2. **Searching**: An AI agent sends a natural language query. ChromaDB embeds the query with the same model, uses HNSW (Hierarchical Navigable Small World) approximate nearest-neighbor search to find the most similar stored vectors, and returns the matching text chunks.

3. **MCP Protocol**: The AI communicates with the palace via Model Context Protocol — a JSON-RPC 2.0 server that runs as a local subprocess. 19 tools are exposed (search, add, delete, graph query, diary write, etc.).

### The Module Map

```
mempalace/
  __init__.py          ← Apple Silicon CoreML crash workaround
  cli.py               ← All CLI commands (mine, sync, repair, status, etc.)
  config.py            ← Palace path resolution, input sanitizers
  mcp_server.py        ← JSON-RPC 2.0 MCP server with 19 tools
  miner.py             ← Project file mining pipeline
  convo_miner.py       ← Conversation export mining pipeline
  normalize.py         ← Multi-format chat normalizer (Claude.ai, ChatGPT, Codex, Slack)
  palace.py            ← Shared ChromaDB access layer
  dialect.py           ← AAAK lossy compression for diary entries
  knowledge_graph.py   ← SQLite temporal entity-relationship store
  palace_graph.py      ← Graph traversal over ChromaDB metadata
  searcher.py          ← Semantic search with scoring
  layers.py            ← 4-layer memory context manager
  hooks_cli.py         ← Auto-save hooks (stop, precompact, session-start)
  query_sanitizer.py   ← Strips system prompt contamination from queries
  repair.py            ← Surgical palace repair (scan/prune/rebuild)
  dedup.py             ← HNSW bloat deduplication
  migrate.py           ← Cross-version ChromaDB migration
  general_extractor.py ← Regex-based memory type extraction
  entity_detector.py   ← Named entity detection
  room_detector_local.py ← Room routing heuristics
  split_mega_files.py  ← Multi-session file splitter
```

### ChromaDB — The Vector Store (iOS Analogy: Core Data + Embeddings)

Think of ChromaDB like Core Data, but instead of storing structured records with predicates, it stores text documents with high-dimensional embedding vectors. The "query" isn't a predicate — it's "find me text that means something similar to this question."

- **Collection**: Like a Core Data entity/table. MemPalace uses one: `mempalace_drawers`.
- **Document**: The text content of a drawer (a chunk of file content or conversation exchange).
- **Embedding**: A 384-float vector computed by the `all-MiniLM-L6-v2` model. Two texts with similar meaning produce vectors that are close in this 384-dimensional space.
- **Metadata**: Key-value pairs stored alongside each document (`wing`, `room`, `source_file`, `content_hash`, `filed_at`, etc.). Used for filtering, not for search.
- **HNSW Index**: The approximate nearest-neighbor search structure. It's a multi-layer graph where each node is a vector, and edges connect vectors that are close together. The "hierarchical" part means there are multiple layers — the top layer has few nodes for fast routing, lower layers have all nodes for precision.
- **Upsert**: ChromaDB's write operation. If the document ID already exists, it updates; otherwise it inserts. This is idempotent — calling it twice with the same data is safe.

**The HNSW corruption problem**: When you `upsert` a document that already exists, ChromaDB's HNSW C++ library (`hnswlib`) calls `updatePoint`, which on macOS ARM can segfault. Also, repeated upserts without deduplication cause `link_lists.bin` (the HNSW index file) to grow unboundedly. This is why PR #239 exists.

### The Mining Pipeline in Detail

**For project files** (`mempalace mine <dir>`):

```
1. Walk directory tree (skip .git, node_modules, etc.)
2. For each file:
   a. Check if already mined (source_mtime matches) → skip if fresh
   b. Delete existing drawers for this file (avoid HNSW updatePoint segfault)
   c. Read file content
   d. Compute file_content_hash (MD5 of stripped content)
   e. Detect room (directory path → filename → keyword scoring)
   f. Chunk into ~800-char pieces with 100-char overlap
   g. For each chunk: call add_drawer(collection, wing, room, content, metadata)
      → ChromaDB embeds the text and stores it
```

**For conversation exports** (`mempalace mine <dir> --mode convos`):

```
1. Walk directory for .json/.jsonl files
2. For each file:
   a. normalize(filepath) → auto-detect format:
      - Claude Code JSONL (type: human/assistant + message.content)
      - Codex CLI JSONL (session_meta + event_msg)
      - Claude.ai JSON (sender/role + text/content + chat_messages)
      - ChatGPT JSON (mapping tree traversal)
      - Slack JSON (message array)
      - Plain text with > markers (pass-through)
   b. Output: canonical transcript format "> user\nassistant\n\n"
   c. chunk_exchanges() → split on > markers, one drawer per Q+A pair
   d. detect_convo_room() → classify as technical/architecture/planning/decisions/problems
   e. add_drawer() for each exchange with ingest_mode="convos" metadata
```

### The MCP Server — How the AI Talks to the Palace

The MCP server (`mcp_server.py`) is a hand-rolled JSON-RPC 2.0 server. No SDK dependency.

- **Transport**: Reads JSON from stdin, writes JSON to stdout. Runs as a subprocess of Claude Code.
- **19 tools** registered in a `TOOLS` dict, each with description, JSON schema, and handler function.
- **Write-Ahead Log (WAL)**: Every write operation logs to `~/.mempalace/wal/write_log.jsonl` *before* executing. This is an audit trail, not crash recovery.
- **Protocol injection**: The AI's first call to `mempalace_status` returns the `PALACE_PROTOCOL` and `AAAK_SPEC` strings embedded in the response, teaching the AI how to use the palace without a system prompt.

### The AAAK Dialect — Lossy Memory Compression

AAAK is a custom lossy compression format for diary entries. It cannot reconstruct the original text.

Format: `ENTITIES|topic_keywords|"key_quote"|WEIGHT|EMOTIONS|FLAGS`

Example: `ALC,JOR|swift,concurrency,actors|"decided to use async/await"|8|determ,conf|DECISION,TECHNICAL`

The AI is taught this format via `AAAK_SPEC` injected into `mempalace_status` responses. Diary entries use AAAK to stay compact enough for constrained contexts.

### The Knowledge Graph

A SQLite database storing temporal entity-relationship triples:

- **Entities**: `(id, name, type, properties)` — people, projects, concepts
- **Triples**: `(subject, predicate, object, valid_from, valid_to, confidence)` — "Alice works_on ProjectX" with date ranges
- **Temporal queries**: `query_entity("Alice", as_of="2026-01-15")` returns only facts valid at that date
- **Invalidation**: `invalidate(subject, predicate, object, ended="2026-03-01")` sets `valid_to`, making the fact historical

---

## Part 1: PR #239 — Safer Repair Command (HNSW Index Corruption)

**Branch**: `fix/chromadb-hnsw-rebuild`
**URL**: https://github.com/MemPalace/mempalace/pull/239

### The Problem

ChromaDB uses HNSW (Hierarchical Navigable Small World) for its vector search index. On disk, this manifests as `link_lists.bin` inside the palace directory. When documents are upserted repeatedly (normal during re-mining), HNSW appends new node entries instead of deduplicating. The file grows unboundedly — on large palaces, it can reach terabytes.

Eventually, the HNSW C++ layer segfaults on any operation that touches the corrupted index. Critically, even `delete_collection()` crashes — because the delete operation loads HNSW segments to tear them down. This means the "obvious" fix (delete and recreate the collection) itself crashes the process.

The SQLite file (`chroma.sqlite3`) is NOT affected — document/metadata storage and the vector index are decoupled. `get()` calls read from SQLite and bypass HNSW entirely. This is the escape hatch.

### The Old Code (What Failed)

```python
# BEFORE — this crashes with a C-level segfault
client = chromadb.PersistentClient(palace_path)
client.delete_collection("mempalace_drawers")   # SEGFAULT HERE
client.create_collection("mempalace_drawers")
```

If HNSW is corrupt, `delete_collection()` triggers a C-level segfault. No Python exception, no cleanup, the palace is left in a partially-deleted state. Data is lost.

### The Fix — Step by Step

The new `cmd_repair()` in `cli.py` never touches the corrupted HNSW index:

**Step 1 — Read data via `get()`, bypassing HNSW**
```python
client = chromadb.PersistentClient(path=palace_path)
col = client.get_collection("mempalace_drawers")
# get() reads from SQLite, NOT from HNSW
batch = col.get(limit=500, offset=offset, include=["documents", "metadatas"])
```
Data is extracted in batches of 500 to avoid OOM on large palaces.

**Step 2 — Release file handles**
```python
del col
del client
```
Explicit deletion forces ChromaDB to flush and release all SQLite/HNSW file handles before the directory manipulation that follows.

**Step 3 — Build a new palace at a temporary path**
```python
rebuild_path = palace_path + "_rebuild"
new_client = chromadb.PersistentClient(path=rebuild_path)
new_col = new_client.create_collection("mempalace_drawers")
```
Creates a brand-new, clean HNSW index in a sibling directory. The original palace is completely untouched.

**Step 4 — Write data into the new palace**
```python
new_col.add(documents=batch_docs, ids=batch_ids, metadatas=batch_metas)
```
Uses `add()` in batches of 100. If writing fails at any point, `sys.exit(1)` is called and the original palace is still intact.

**Step 5 — Verify the rebuild**
```python
rebuilt_count = new_col.count()
if rebuilt_count != len(all_ids):
    # Abort — original untouched, partial rebuild preserved for inspection
    return
```

**Step 6 — Atomic directory swap**
```python
os.rename(palace_path, backup_path)    # original → .backup
os.rename(rebuild_path, palace_path)   # _rebuild → palace
```
`os.rename` on the same filesystem is atomic at the OS level. At no point is the palace "missing." The backup is preserved until the user manually deletes it.

### Files Changed

| File | What Changed |
|------|-------------|
| `mempalace/cli.py` | Complete rewrite of `cmd_repair()` — the 2-phase rebuild logic described above |
| `mempalace/repair.py` | New module with surgical repair operations: `scan_palace` (find corrupt IDs), `prune_corrupt` (remove them), `rebuild_index` (in-place rebuild alternative) |
| `tests/test_repair.py` | 17 tests covering all repair operations |

### Key Safety Properties

- **Original palace is never mutated during rebuild** — all writes go to `_rebuild` directory
- **Verification before swap** — count mismatch aborts the operation
- **Backup preserved** — the old palace directory is renamed, not deleted
- **No HNSW contact on corrupted index** — only `get()` (SQLite) is used to read
- **Trailing slash defense** — `palace_path.rstrip(os.sep)` ensures backup doesn't land inside the palace

### iOS Analogy

Imagine your Core Data SQLite store has a corrupt WAL file that makes `NSPersistentStoreCoordinator` crash on any write. The fix: open the SQLite directly with `sqlite3` (bypassing Core Data), extract all rows, create a fresh store, insert the rows, then atomically swap the `.sqlite` files.

---

## Part 2: PR #243 — Claude.ai Chat Export Normalizer Fix

**Branch**: `fix/claude-ai-chat-normalizer`
**URL**: https://github.com/MemPalace/mempalace/pull/243

### The Problem

MemPalace can mine conversation exports from multiple AI chat platforms. Each platform exports conversations in a different JSON format. The `normalize.py` module auto-detects the format and converts it to a canonical transcript:

```
> What is context engineering?
Context engineering is designing LLM prompts with the right information.

> How do actors work in Swift?
Actors serialize access to mutable state.
```

The problem: Claude.ai's export format uses **different field names** than every other platform:

| Field | Claude Code / ChatGPT | Claude.ai Privacy Export |
|-------|----------------------|--------------------------|
| Sender role | `"role"` | `"sender"` |
| Role values | `"user"` / `"assistant"` | `"human"` / `"assistant"` |
| Message body | `"content"` (string or block list) | `"text"` (always plain string) |

The old code only checked `role` and `content`. When a Claude.ai export arrived with `sender: "human"` and `text: "..."`:
- `item.get("role", "")` → `""` (empty — no match)
- `item.get("content", "")` → `""` (empty — wrong field name)
- Zero messages accumulated → function returned `None`
- The file fell through to raw JSON pass-through → stored as unparsed JSON blob in ChromaDB
- Search quality for Claude.ai conversations → effectively zero

### The Fix

Three targeted changes in `_try_claude_ai_json`:

**1. Dual-field role extraction:**
```python
# BEFORE
role = item.get("role", "")

# AFTER
role = item.get("sender") or item.get("role") or ""
```

**2. Dual-field text extraction with null safety:**
```python
# BEFORE
text = _extract_content(item.get("content", ""))

# AFTER
text = (item.get("text") or "").strip() or _extract_content(item.get("content", ""))
```
Priority: `text` field first (Claude.ai), then `content` as fallback (all other formats).
The `or ""` handles the case where `"text"` is JSON `null` (Python `None`).

**3. Per-conversation transcript isolation:**
```python
# BEFORE — all conversations merged into one flat transcript
all_messages = []
for convo in data:
    for item in convo["chat_messages"]:
        all_messages.append(...)

# AFTER — each conversation is its own section with a header
transcripts = []
for convo in data:
    messages = []  # per-conversation
    for item in convo["chat_messages"]:
        messages.append(...)
    header = convo.get("name", "").strip()
    if header:
        transcript = f"--- {header} ---\n\n{transcript}"
    transcripts.append(transcript)
return "\n\n".join(transcripts)
```

### The Format Detection Chain

`normalize()` routes files through a parser chain (most-specific to most-general):

```
1. _try_claude_code_jsonl(content)    ← JSONL with type: human/assistant
2. _try_codex_jsonl(content)          ← JSONL with session_meta guard
3. _try_claude_ai_json(data)          ← Array of convos with sender/role fields ← THIS PR FIXES THIS
4. _try_chatgpt_json(data)            ← Mapping tree with author.role
5. _try_slack_json(data)              ← Array of message objects (most permissive)
```

Each parser returns `None` if it doesn't recognize the format, and the chain continues.

### Files Changed

| File | What Changed |
|------|-------------|
| `mempalace/normalize.py` | Fixed `_try_claude_ai_json` — dual field extraction + per-conversation isolation |
| `tests/test_normalize.py` | 7 new Claude.ai-specific test cases covering sender field, text field, multi-conversation boundaries, flat format, role backward compatibility, empty messages, content block fallback |

### Test Cases Added

| Test | What It Verifies |
|------|-----------------|
| `test_claude_ai_sender_field` | `sender: "human"` is recognized as a user message |
| `test_claude_ai_text_field_preferred` | `text` field used even when `content` block list exists |
| `test_claude_ai_multi_conversation_boundaries` | Multiple conversations produce separate sections, not one blob |
| `test_claude_ai_flat_sender_format` | Flat message list (no conversation wrapper) with `sender` field |
| `test_claude_ai_role_field_still_works` | Backward compatibility — old `role`/`content` format still parses |
| `test_claude_ai_empty_chat_messages` | Conversations with zero messages are skipped, not crashed on |
| `test_claude_ai_content_block_list_fallback` | When `text` is empty, falls back to extracting from `content` blocks |

### iOS Analogy

This is like fixing a `JSONDecoder` that expected `codingKeys` matching one API format, but a second API sends the same data with different key names. The fix: check both key names with `decodeIfPresent`, falling through gracefully.

---

## Part 3: PR #251 — Sync Command (Incremental Re-Mining)

**Branch**: `feat/sync-command`
**URL**: https://github.com/MemPalace/mempalace/pull/251

### The Problem

After initial mining, source files change. The palace becomes stale — drawers contain outdated content. The only option was to re-mine everything from scratch (`--force`), which is slow on large palaces.

### The Solution — Content Hash + Incremental Sync

Every drawer now stores a `content_hash` (MD5 of the source file's stripped content). The new `mempalace sync` command compares stored hashes against current files to detect what changed.

### How Content Hashing Works

```python
def file_content_hash(filepath: Path) -> str:
    content = filepath.read_text(encoding="utf-8", errors="replace").strip()
    return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()
```

- **Input**: Full file content, stripped of leading/trailing whitespace
- **Output**: 32-character hex MD5 digest
- **Stored in**: Every drawer's metadata as `content_hash`
- **All chunks from the same file share the same hash** — it's a file-level property
- For conversations: hash is computed on raw content *before* normalize() transforms it — so the hash always matches what's physically on disk

### The Complete Sync Flow

```
mempalace sync [--dir <dir>] [--clean] [--dry-run]
```

**Step 1 — Scan palace for source files**
Iterates all drawers in batches of 500, collecting unique `source_file` paths with their stored `content_hash`, drawer IDs, wing, and ingest_mode.

**Step 2 — Optional directory filter**
If `--dir` is set, only source files under that directory are checked.

**Step 3 — Classify each file into four states:**

| State | Condition | What Happens |
|-------|-----------|-------------|
| **Fresh** | File exists, hash matches stored hash | Nothing — content is current |
| **Stale** | File exists, hash differs from stored hash | Delete old drawers + re-mine |
| **Missing** | File no longer exists on disk | Report; delete drawers if `--clean` |
| **No-hash (legacy)** | Drawer has no `content_hash` (mined before this feature) | Report; suggest `--force` re-mine |

**Step 4 — Report**
```
  Fresh (unchanged):     142
  Stale (changed):       3
  Missing (deleted):     1
  No hash (legacy):      28 (re-mine with --force to add hashes)
```

**Step 5 — Atomic per-file re-mining** (if not `--dry-run`)
For each stale file:
1. Delete all drawer IDs for that file from ChromaDB
2. Immediately re-mine that specific file
3. Route to correct miner based on `ingest_mode`: `"convos"` → conversation miner, otherwise → project miner

"Atomic per-file" means delete+re-mine happens one file at a time. At no point is a file's content absent from the palace for longer than the time to process that one file.

**Step 6 — Optional orphan cleanup**
If `--clean` is set, drawers for missing files are deleted. Otherwise just reported.

### CLI Flags

| Flag | Effect |
|------|--------|
| `--dir <path>` | Only sync files under this directory |
| `--clean` | Delete drawers for files that no longer exist |
| `--dry-run` | Show what would change without modifying the palace |

Also added to `mempalace mine`:
| Flag | Effect |
|------|--------|
| `--force` | Delete ALL existing drawers for the source directory before mining (adds content_hash to legacy drawers) |

### Files Changed

| File | What Changed |
|------|-------------|
| `mempalace/cli.py` | Added `cmd_sync()` (~200 lines), `_force_clean()`, sync argparse, `--force` on mine |
| `mempalace/miner.py` | Added `file_content_hash()`, `content_hash` param to `add_drawer()`, pre-mine delete in `process_file()` |
| `mempalace/convo_miner.py` | Added `filepath_filter` param, stores `ingest_mode: "convos"` and `content_hash` in metadata |
| `mempalace/palace.py` | Added `check_mtime` param to `file_already_mined()` |
| `mempalace/instructions/sync.md` | AI skill instructions for using sync |
| `.claude-plugin/commands/sync.md` | Claude Code `/sync` slash command |
| `tests/test_sync.py` | 8 tests for hash storage, stale detection, missing files, legacy drawers |

### iOS Analogy

This is like Core Data's `NSPersistentHistoryTracking` — tracking what changed since last sync. But instead of tracking individual attribute changes, MemPalace tracks whole-file content hashes. If the hash differs, the entire file is re-processed (all its Core Data objects deleted and recreated).

---

## Part 4: PR #256 — Sync Status MCP Tool + Freshness Hook

**Branch**: `feat/sync-mcp-tool`
**URL**: https://github.com/MemPalace/mempalace/pull/256

### The Problem

PR #251 gives the *human* a sync command. But the *AI* has no way to know if the palace is stale. It might answer questions using outdated drawer content without realizing the source files have changed.

### The Solution — Read-Only MCP Tool + Idempotent Writes

This PR adds `mempalace_sync_status` — an MCP tool the AI can call to check palace freshness. It also makes `tool_add_drawer` idempotent (safe to call twice with the same content).

### The `mempalace_sync_status` MCP Tool

**What it does**: Reads all drawer metadata, compares stored content hashes against current files on disk, and returns a JSON report.

**What it returns**:
```json
{
  "total_source_files": 145,
  "fresh": 142,
  "stale": 2,
  "missing": 1,
  "no_hash_legacy": 0,
  "status": "stale",
  "message": "2 source files changed since last mine",
  "stale_files": [
    {"file": "api_client.py", "drawers": 8, "wing": "myproject"}
  ],
  "remine_commands": [
    "mempalace mine /path/to/src --wing myproject --force"
  ]
}
```

**Key constraint**: This tool is **read-only**. It reports staleness and suggests shell commands. It does NOT mine or delete anything. The AI surfaces the commands to the user.

### CLI Sync vs MCP Sync Status

| | `mempalace sync` (CLI, PR #251) | `mempalace_sync_status` (MCP, PR #256) |
|---|---|---|
| **Invoked by** | Human in terminal | AI via MCP protocol |
| **Action** | Read + Write (deletes + re-mines) | Read-only diagnostic |
| **Output** | Human-readable stdout | JSON for AI consumption |
| **Re-mining** | Executes atomically per-file | Suggests shell commands |
| **Orphan handling** | Deletes if `--clean` | Reports only |

These are complementary halves: the MCP tool is the "diagnostic layer" (AI checks freshness), the CLI command is the "action layer" (human fixes staleness).

### Idempotent `tool_add_drawer`

Before this PR, calling `tool_add_drawer` twice with the same content created two drawers. Now:

**Step 1 — Deterministic ID**: If no `source_file` is provided, one is synthesized from content: `"mcp:" + md5(content)`. The drawer ID is: `drawer_{wing}_{room}_{sha256(source + "0")[:24]}`.

**Step 2 — Pre-check**: `col.get(ids=[drawer_id])` — if the drawer already exists, returns `{"success": true, "reason": "already_exists"}` immediately.

**Step 3 — Semantic duplicate check**: `tool_check_duplicate(content, threshold=0.9)` — even if the exact ID doesn't exist, rejects content that's 90%+ similar to existing drawers.

**Step 4 — Shared routing**: Delegates to `miner.add_drawer()` (the same function used by the mining pipeline), ensuring consistent metadata and hashing.

### The Freshness Concept

"Freshness" = agreement between a drawer's stored `content_hash` and the current MD5 of the file on disk.

```
Fresh:   md5(file_on_disk.strip()) == drawer.metadata["content_hash"]
Stale:   md5(file_on_disk.strip()) != drawer.metadata["content_hash"]
Missing: file no longer exists on disk
Legacy:  drawer has no content_hash field (mined before this feature)
```

### Files Changed

| File | What Changed |
|------|-------------|
| `mempalace/mcp_server.py` | Added `tool_sync_status()`, made `tool_add_drawer` idempotent with shared routing, added WAL logging |
| `mempalace/miner.py` | Added `content_hash` param to `add_drawer()`, `source_mtime` in metadata |
| `mempalace/palace.py` | New shared module: `get_collection()`, `file_already_mined()` |
| `mempalace/hooks_cli.py` | Centralized hook logic (precompact always blocks, stop counts exchanges) |
| `.claude-plugin/hooks/hooks.json` | Removed Stop hook (too frequent), kept PreCompact only |
| `.claude-plugin/skills/mempalace/SKILL.md` | Added sync to skill routing |

### The Hook System

**PreCompact Hook** (the important one): Fires before Claude Code compresses conversation context. Always blocks and tells the AI: "Save everything to MemPalace NOW before context is lost." If `MEMPAL_DIR` is set, also runs `mempalace mine` synchronously.

**Stop Hook** (removed from active use): Was blocking every 15 human messages for auto-save. Too noisy — removed from `hooks.json` but code preserved.

### iOS Analogy

The MCP sync_status tool is like an `NSFetchedResultsController` delegate that monitors for external changes — it doesn't modify data, it just tells you "hey, the underlying store changed since you last fetched." The idempotent `tool_add_drawer` is like Core Data's `NSMergePolicy.mergeByPropertyObjectTrump` — if the same object already exists, the operation succeeds silently.

---

## Part 5: How the 4 PRs Connect

```
PR #239 (Repair)
  └── Fixes: HNSW corruption that breaks the palace
  └── Enables: Safe recovery when things go wrong

PR #243 (Normalizer)
  └── Fixes: Claude.ai conversations not being parsed
  └── Enables: Mining your Claude.ai chat exports

PR #251 (Sync Command)
  └── Adds: content_hash to every drawer during mining
  └── Adds: CLI command to detect and fix stale content
  └── Depends on: mining pipeline from miner.py and convo_miner.py

PR #256 (Sync MCP Tool)
  └── Adds: AI-callable freshness check
  └── Adds: Idempotent drawer creation
  └── Depends on: content_hash from PR #251
  └── Complements: CLI sync from PR #251 (diagnostic vs action)
```

The dependency chain: #243 is independent. #239 is independent. #251 introduces content_hash. #256 builds on #251's content_hash to expose freshness to the AI.

---

## Glossary

| Term | Meaning |
|------|---------|
| **ChromaDB** | Open-source vector database. Stores text + embeddings + metadata. |
| **HNSW** | Hierarchical Navigable Small World — the approximate nearest-neighbor search algorithm ChromaDB uses |
| **MCP** | Model Context Protocol — JSON-RPC 2.0 protocol for AI↔tool communication |
| **Embedding** | A 384-float vector representing the semantic meaning of a text chunk |
| **Upsert** | Insert-or-update operation (idempotent) |
| **AAAK** | Lossy compression format for diary entries: `ENTITIES|topics|"quote"|WEIGHT|EMOTIONS|FLAGS` |
| **WAL** | Write-Ahead Log — audit trail of all write operations |
| **Drawer ID** | Deterministic SHA-256 hash of `(source_file + chunk_index)`, prefixed with `drawer_{wing}_{room}_` |
| **content_hash** | MD5 of a source file's stripped content; shared by all drawers from that file; used for staleness detection |
| **FIPS mode** | Federal Information Processing Standards — Python flag `usedforsecurity=False` suppresses warnings on restricted builds |
| **CoreML** | Apple's ML framework; crashes with ChromaDB's ONNX model on ARM, disabled in `__init__.py` |

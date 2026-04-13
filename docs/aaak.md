# AAAK dialect (experimental)

AAAK is a lossy abbreviation system for compressing repeated entities and relationships into fewer tokens. It is designed to be readable by any LLM without a decoder.

## Current status

**AAAK regresses retrieval quality vs raw mode.** On LongMemEval:

- Raw verbatim mode: **96.6% R@5**
- AAAK mode: **84.2% R@5** (−12.4 points)

The 96.6% headline number is from raw verbatim mode, not AAAK. AAAK is a separate compression layer and is **not** the storage default.

AAAK may save tokens at scale when many entities are repeated across thousands of sessions. It does not save tokens on short text — the overhead of entity codes and structural markers costs more than it saves.

See [NOTICES.md](../NOTICES.md) for the full history of claims and corrections.

## Format

### Entity codes

Three-letter uppercase codes for frequently mentioned entities:

```
ALC = Alice
KAI = Kai
PRI = Priya
MAX = Max
```

### Emotion markers

Action markers before or during text:

```
*warm* = joy
*fierce* = determined
*raw* = vulnerable
*bloom* = tenderness
```

### Structure

Pipe-separated fields with category prefixes:

```
FAM: ALC→♡JOR | 2D(kids): RIL(18,sports) MAX(11,chess+swimming) | BEN(contributor)
```

### Dates and counts

- Dates: ISO format (`2026-03-31`)
- Counts: `Nx` = N mentions (e.g., `570x`)
- Importance: `★` to `★★★★★` (1–5 scale)

### Halls and wings

```
Halls: hall_facts, hall_events, hall_discoveries, hall_preferences, hall_advice
Wings: wing_user, wing_agent, wing_team, wing_code, wing_myproject
Rooms: hyphenated slugs (chromadb-setup, gpu-pricing)
```

## Example

Full AAAK entry:

```
FAM: ALC→♡JOR | 2D(kids): RIL(18,sports) MAX(11,chess+swimming) | BEN(contributor)
```

Reads as: Alice is in a relationship with Jordan. They have 2 kids: Riley (18, into sports) and Max (11, into chess and swimming). Ben is a contributor.

## Usage

### CLI

```bash
mempalace compress --wing myapp --dry-run    # preview compression
mempalace compress --wing myapp              # compress and store
mempalace compress --config entities.json    # with entity config
```

Compressed drawers are stored in a separate `mempalace_compressed` ChromaDB collection. The raw originals are preserved.

### Python API

```python
from mempalace.dialect import Dialect

# Basic usage
dialect = Dialect()
compressed = dialect.compress("Alice and Jordan discussed the auth migration with Kai")
stats = dialect.compression_stats(original_text, compressed)

# With entity config
dialect = Dialect.from_config("entities.json")
compressed = dialect.compress(text, metadata={"wing": "myapp"})

# Token counting
tokens = Dialect.count_tokens(text)
```

### MCP

The AAAK spec is automatically included in the `mempalace_status` response so the AI learns it on first connection. It can also be retrieved explicitly via `mempalace_get_aaak_spec`.

Agent diary entries (`mempalace_diary_write`) are recommended to be written in AAAK format for compression:

```
SESSION:2026-04-04|built.palace.graph+diary.tools|ALC.req:agent.diaries.in.aaak|★★★
```

## Limitations

- **Lossy.** AAAK uses regex-based abbreviation, not reversible compression. Information is lost.
- **Degrades embedding quality.** Compressed AAAK text produces worse vector embeddings than plain English, which is why search quality drops.
- **No token savings at small scale.** Short text already tokenizes efficiently. AAAK overhead exceeds savings on individual sentences.
- **Entity codes require configuration.** Without an entity config file, AAAK cannot assign codes to specific names.

## Tracking

- [Issue #43](https://github.com/milla-jovovich/mempalace/issues/43) — AAAK tokenizer accuracy
- [Issue #27](https://github.com/milla-jovovich/mempalace/issues/27) — AAAK iteration and improvements

# Product Intent Triage

Date: 2026-04-07

This note captures behaviors that were confirmed in code and local probes, but should not be changed blindly because they may reflect product intent, benchmark scope, or an unfinished roadmap.

## Summary

| Item | Confirmed behavior | Safe to change now | Why not |
| --- | --- | --- | --- |
| Incremental reindexing skips already-mined files by `source_file` | Yes | No | Changes the meaning of mining from append-only memory to current-state indexing |
| `L1` and `L2` are simpler than the README story | Yes | No | Need a call on whether code or docs are the source of truth |
| Normalization can spell-correct user text before storage | Yes | No | Could be intentional for retrieval quality even if it mutates source text |
| Rich palace schema exists more in docs than ingest output | Yes | No | Might be roadmap language rather than a shipped contract |
| AAAK is lossy in runtime despite "lossless" language | Yes | No | Needs either claim changes or a deeper storage design |
| LongMemEval `hybrid_v4` logic is benchmark-specific | Yes | No | Need to decide whether benchmark code should move into product runtime at all |

## Confirmed Behaviors That Need Maintainer Intent

### 1. Incremental reindexing semantics

Status: confirmed

Observed behavior:
- `mine()` and conversation mining skip a file once any drawer already exists for that `source_file`.
- A probe that changed file contents from `v1` to `v2` and re-ran mining kept the old content and did not add the new content.

Why this is ambiguous:
- If MemPalace is an append-only memory journal, skipping re-mines may be intentional.
- If MemPalace is meant to be a searchable index of current project state, this is wrong and stale.

What can be fixed safely now:
- Documentation can be clarified now.

What should wait:
- Replacing this with hash-based refresh and stale-chunk cleanup should wait for a product decision about whether drawers are immutable memories or reindexable views of source files.

### 2. `L1` and `L2` behavior versus the README narrative

Status: confirmed

Observed behavior:
- `L1` sorts by weight-like metadata keys and does not actually use recency.
- `L2` is a filtered `get()` by wing and room, not a query-driven semantic retrieval layer.
- `L3` is the first layer that performs semantic search.

Why this is ambiguous:
- The current code may be intentionally simple while the docs describe the target design.
- Changing runtime behavior here affects token budgets, latency, and the system's public story.

What can be fixed safely now:
- Documentation can be aligned with current behavior, or the README can mark the richer layer behavior as aspirational.

What should wait:
- Runtime changes should wait for a maintainer decision on whether `L1` should truly combine importance and recency, and whether `L2` should become semantic retrieval rather than filtered browsing.

### 3. Spell-correcting user text during normalization

Status: confirmed

Observed behavior:
- When the optional spellcheck path is available, normalization rewrites user text before it is stored as transcript content.
- This can improve searchability, but it is not verbatim preservation.

Why this is ambiguous:
- The rewrite may be intentional to help local retrieval work on noisy chat exports.
- It also changes source material, which matters if the product claims exact memory or archival fidelity.

What can be fixed safely now:
- Documentation can explain that normalization is not strictly verbatim when spellcheck is active.

What should wait:
- A code change should wait for a decision between:
  - store only corrected text
  - store raw text plus corrected text
  - make correction opt-in instead of implicit

### 4. Rich palace schema versus ingest output

Status: confirmed

Observed behavior:
- Ingest writes lightweight metadata such as `wing`, `room`, `source_file`, `chunk_index`, and `filed_at`.
- Other modules and docs talk about richer concepts like halls, closets, dates, and importance.

Why this is ambiguous:
- This may be an unfinished architecture rather than a broken one.
- Promoting the richer schema to a hard runtime contract would increase ingest complexity and create migration work.

What can be fixed safely now:
- Documentation can distinguish between shipped metadata and planned metadata.

What should wait:
- Runtime/schema work should wait for a real metadata contract and migration plan.

### 5. AAAK "lossless" positioning versus lossy implementation

Status: confirmed

Observed behavior:
- The current AAAK compression path keeps selected entities, topics, one quote, and a few flags.
- A direct probe showed material content loss compared with the original note.
- Normal retrieval does not read the compressed collection anyway.

Why this is ambiguous:
- The code could be an early approximation while the README describes the intended final method.
- Fixing this is not a one-line bug fix; it requires either changing the claim or redesigning how compressed and raw forms coexist.

What can be fixed safely now:
- Documentation can stop describing the current implementation as lossless.

What should wait:
- Runtime changes should wait for a design decision:
  - lossy summary sidecar
  - reversible encoding
  - fused retrieval across raw and compressed stores

### 6. Benchmark-specific retrieval versus product retrieval

Status: confirmed

Observed behavior:
- The runtime package uses straightforward Chroma-backed retrieval.
- The LongMemEval harness contains additional hybrid scoring and targeted final-step logic that is not used by the shipped runtime.

Why this is ambiguous:
- Benchmark harnesses are allowed to be more specialized than product code.
- Moving benchmark logic into runtime may hurt simplicity and portability.

What can be fixed safely now:
- Documentation can draw a cleaner line between benchmark retrieval and default product retrieval.

What should wait:
- Any engine swap should wait for explicit maintainer intent about whether MemPalace is optimizing for benchmark leadership, product simplicity, or both.

## Recommended Next Decision Order

1. Decide whether mining is append-only memory or current-state indexing.
2. Decide whether docs should describe shipped behavior or target architecture.
3. Decide whether normalized transcripts must remain verbatim.
4. Decide whether AAAK is a summary sidecar or a core retrieval format.
5. Decide how much benchmark logic should graduate into runtime.

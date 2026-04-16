# Milvus backend

MemPalace ships with two interchangeable storage backends:

| Backend | Package | Default storage | When to pick |
|---------|---------|-----------------|-------------|
| **Chroma** (default) | `chromadb` | `chroma.sqlite3` + `./<palace>/` | Single-machine, zero extra setup, works out of the box. |
| **Milvus Lite** | `pymilvus[milvus_lite]` | single `milvus.db` file per palace | Single-file palace you can copy as one artifact; same local-first guarantee; a stepping stone for users who later want to self-host Milvus. |

Both implement the same `BaseCollection` contract
(`mempalace/backends/base.py`), so wings, rooms, drawers, closets, hybrid
search, and the knowledge graph behave identically regardless of which
one is active. Switching backends does **not** migrate data — they each
own a separate storage tree.

## Why Milvus Lite

Milvus Lite is a pure embedded build of the Milvus engine. It runs
in-process, writes to a single `.db` file, requires no server, and has
no cloud or API-key dependency. That matches MemPalace's local-first,
verbatim, zero-API rule exactly. Self-hosted Milvus over `http://…` is
also supported for users who eventually outgrow a single file — but the
default is, and will remain, a file on your laptop.

Zilliz Cloud is deliberately **not documented as an install path** for
MemPalace: cloud storage of verbatim memory is outside MemPalace's
privacy-by-architecture guarantee.

## Install

```bash
pip install 'mempalace[milvus]'
```

The `milvus` extra pulls in:

- `pymilvus>=2.5.0` — modern `MilvusClient` API
- `milvus-lite>=2.4.10` — embedded engine (Linux / macOS; not available on Windows)
- `onnxruntime>=1.17.0` — local embedding runtime
- `huggingface_hub>=0.20.0` — one-time model download

> **Note on Python 3.13 / setuptools 81+**: `milvus-lite<=2.5.1` still
> imports the deprecated `pkg_resources` module, which was removed in
> `setuptools>=81`. The extra pins `setuptools<81` until a newer
> `milvus-lite` release drops the dependency.

## Selecting Milvus as the backend

Set an environment variable before launching any MemPalace command or the MCP server:

```bash
export MEMPALACE_BACKEND=milvus
```

Under the hood, `mempalace.backends.make_default_backend()` reads this
variable and instantiates the right backend. Leave the variable unset or
set it to `chroma` to keep the current default.

## Direct programmatic use

```python
from mempalace.backends import MilvusBackend

backend = MilvusBackend()
col = backend.get_or_create_collection("/path/to/palace", "mempalace_drawers")

col.add(
    ids=["drawer_1"],
    documents=["I am storing exactly these words."],
    metadatas=[{"wing": "notes", "room": "thoughts"}],
)

result = col.query(
    query_texts=["what did I write down"],
    n_results=5,
    where={"wing": "notes"},
)
for text, meta, dist in zip(result.documents, result.metadatas, result.distances):
    print(dist, meta, text)
```

## Self-hosted Milvus

Point `MilvusBackend` at a running Milvus server:

```python
MilvusBackend(uri="http://milvus.example.internal:19530")
```

The same `get_collection` / `query` / `get` / `delete` API is used; only
the URI changes. Remember that any content you send over the network
leaves your machine — which is fine for self-hosted deployments you
control, but is a policy decision MemPalace will never make for you.

## Embeddings

Milvus collections are indexed with
`AUTOINDEX` + `metric_type="COSINE"`, so distances align with the
ChromaDB default (`hnsw:space=cosine`). The embeddings themselves are
generated locally by `mempalace.embeddings.Embedder`, which wraps the
same ONNX-exported `sentence-transformers/all-MiniLM-L6-v2` (384 dim)
model ChromaDB bundles. The model is cached under
`~/.cache/mempalace/onnx/` (override with
`MEMPALACE_EMBEDDINGS_CACHE`). After the one-time download, runtime
calls are fully offline.

To guarantee no network traffic at runtime, call `warmup()` during
startup:

```python
from mempalace.embeddings import warmup
warmup()  # downloads + loads the model; later calls hit disk only
```

## Schema

Each collection stores three fixed fields plus dynamic metadata:

| Field | Type | Notes |
|-------|------|-------|
| `id` | `VARCHAR(128)` | Primary key; MemPalace drawer IDs fit well under this. |
| `document` | `VARCHAR(65535)` | Verbatim text. MemPalace never truncates — callers must chunk before storing. |
| `vector` | `FLOAT_VECTOR(384)` | MiniLM embedding. |
| *(dynamic)* | inferred | Every metadata key you pass (`wing`, `room`, `hall`, `source_file`, `chunk_index`, `filed_at`, …) is stored and filterable. |

## Supported `where` DSL

The abstraction supports the same filter subset on both backends:

| Clause | Example |
|--------|---------|
| Equality | `{"wing": "project"}` |
| Membership | `{"chunk_index": {"$in": [1, 2, 3]}}` |
| AND | `{"$and": [{"wing": "p"}, {"room": "r"}]}` |
| OR  | `{"$or":  [{"wing": "p"}, {"wing": "q"}]}` |

Operators outside this list (`$ne`, `$gt`/`$lt`, regex, full-text
search) are intentionally not part of the portable contract. The Milvus
adapter raises `ValueError` when it sees one so the error is surfaced
at the call site instead of quietly producing wrong results.

Multi-key top-level dicts (`{"wing": "p", "room": "r"}`) also raise —
wrap them in an explicit `$and`. This is stricter than Chroma's
implicit-AND behavior, but it keeps the meaning unambiguous across
backends.

## Limits and known caveats

- **Windows**: `milvus-lite` is not distributed for Windows; stay on the
  Chroma backend there.
- **Verbatim contract**: a single document longer than 65 535
  characters will raise `ValueError` at insert time. MemPalace's
  existing chunking keeps drawers well below this; this is a guardrail
  for user-authored content (e.g. diary entries).
- **pkg_resources deprecation**: `milvus-lite<=2.5.1` emits a
  `UserWarning` about `pkg_resources`. It is harmless and goes away
  once `milvus-lite` updates.
- **Palace migration**: there is no automatic data migration between
  Chroma and Milvus. Pick a backend per palace.

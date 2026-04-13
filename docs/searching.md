# Searching

## CLI search

```bash
mempalace search "why did we switch to GraphQL"
```

Returns the top 5 results ranked by semantic similarity. Each result shows the wing, room, source file, similarity score, and the verbatim text.

### Filtering

```bash
mempalace search "auth decisions" --wing myapp
mempalace search "pricing" --wing myapp --room billing
```

Filtering by wing and/or room restricts the ChromaDB query to matching metadata. This narrows the search space and typically improves relevance.

### Result count

```bash
mempalace search "database migration" --results 10
```

Default is 5.

### Output format

```
============================================================
  Results for: "auth decisions"
  Wing: myapp
============================================================

  [1] myapp / auth-migration
      Source: 2026-01-15_session.md
      Match:  0.892

      We decided to migrate from Auth0 to Clerk because of pricing
      and developer experience. Kai recommended it, Priya approved.

  ────────────────────────────────────────────────────────────
```

## Programmatic search

### search_memories()

Returns structured data instead of printing to stdout. Used by the MCP server and other programmatic callers.

```python
from mempalace.searcher import search_memories

results = search_memories(
    query="auth decisions",
    palace_path="~/.mempalace/palace",
    wing="myapp",
    room="auth-migration",
    n_results=5,
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | required | Search query text |
| `palace_path` | `str` | required | Path to the ChromaDB palace directory |
| `wing` | `str` | `None` | Filter by wing name |
| `room` | `str` | `None` | Filter by room name |
| `n_results` | `int` | `5` | Maximum number of results |

**Returns:** `dict` with the following structure:

```python
{
    "query": "auth decisions",
    "filters": {"wing": "myapp", "room": "auth-migration"},
    "results": [
        {
            "text": "We decided to migrate from Auth0 to Clerk...",
            "wing": "myapp",
            "room": "auth-migration",
            "source_file": "2026-01-15_session.md",
            "similarity": 0.892,
        },
        # ...
    ],
}
```

On error (e.g., no palace found):

```python
{
    "error": "No palace found",
    "hint": "Run: mempalace init <dir> && mempalace mine <dir>",
}
```

### search()

The CLI-oriented function. Prints results to stdout and raises `SearchError` on failure.

```python
from mempalace.searcher import search, SearchError

try:
    search(
        query="auth decisions",
        palace_path="~/.mempalace/palace",
        wing="myapp",
        n_results=5,
    )
except SearchError as e:
    print(f"Search failed: {e}")
```

### SearchError

Raised when search cannot proceed — typically because no palace exists at the given path, or the ChromaDB collection doesn't exist.

```python
from mempalace.searcher import SearchError
```

## How search works

1. The query string is embedded using ChromaDB's default embedding model (Sentence Transformers `all-MiniLM-L6-v2`).
2. ChromaDB performs approximate nearest-neighbor search against stored drawer embeddings.
3. If `wing` or `room` filters are provided, only matching documents are searched (ChromaDB `where` clause).
4. Results are ranked by cosine distance. The similarity score shown is `1 - distance`.

### Query sanitization

When called through the MCP server, search queries are sanitized by `query_sanitizer.py` to strip system prompt contamination. This prevents AI assistants from accidentally including their entire system prompt in the search query, which degrades search quality.

The sanitizer is transparent — if it modifies the query, the response includes a `query_sanitized` flag and a `sanitizer` object with the `clean_query` text, original and cleaned lengths, and the sanitization method used.

## Memory layer search

The [memory layers](architecture.md) provide different search strategies:

- **L2 (on-demand):** metadata-filtered retrieval by wing/room, no semantic search. Fast, returns all matching drawers up to a limit.
- **L3 (deep search):** full semantic search, the same as `mempalace search`. Returns ranked results.

```python
from mempalace.layers import MemoryStack

stack = MemoryStack(palace_path="~/.mempalace/palace")

# L2: filtered retrieval (no semantic search)
stack.recall(wing="myapp", room="auth-migration")

# L3: semantic search
stack.search("why did we switch auth providers", wing="myapp")
```

See [python-api.md](python-api.md) for the full `MemoryStack` API.

# Searching Memories

MemPalace uses ChromaDB's semantic vector search to find relevant memories. When you search, you get **verbatim text** — the exact words, never summaries.

## CLI Search

```bash
# Search everything
mempalace search "why did we switch to GraphQL"

# Filter by wing (project)
mempalace search "database decision" --wing myapp

# Filter by room (topic)
mempalace search "auth decisions" --room auth-migration

# Filter by both
mempalace search "pricing" --wing driftwood --room costs

# More results
mempalace search "deploy process" --results 10
```

## How Search Works

1. Your query is embedded using ChromaDB's default model (`all-MiniLM-L6-v2`)
2. The embedding is compared against all drawers using cosine similarity
3. Optional wing/room filters narrow the search scope
4. Results are returned with similarity scores and source metadata

### Why Structure Matters

Tested on 22,000+ real conversation memories:

```
Search all closets:          60.9%  R@10
Search within wing:          73.1%  (+12%)
Search wing + hall:          84.8%  (+24%)
Search wing + room:          94.8%  (+34%)
```

Wings and rooms aren't cosmetic — they're a **34% retrieval improvement**.

## Programmatic Search

Use the Python API for integration:

```python
from mempalace.searcher import search_memories

results = search_memories(
    query="auth decisions",
    palace_path="~/.mempalace/palace",
    wing="myapp",
    room="auth",
    n_results=5,
)

for hit in results["results"]:
    print(f"[{hit['similarity']}] {hit['wing']}/{hit['room']}")
    print(f"  {hit['text'][:200]}")
```

The `search_memories()` function returns a dict:

```python
{
    "query": "auth decisions",
    "filters": {"wing": "myapp", "room": "auth"},
    "results": [
        {
            "text": "We decided to migrate auth to Clerk because...",
            "wing": "myapp",
            "room": "auth-migration",
            "source_file": "session_2026-01-15.md",
            "similarity": 0.892,
        },
        # ...
    ],
}
```

## MCP Search

When connected via MCP, your AI searches automatically:

> *"What did we decide about auth last month?"*

The AI calls `mempalace_search` behind the scenes. You never type a search command.

See [MCP Integration](/guide/mcp-integration) for setup.

## Wake-Up Context

Instead of searching, you can load a compact context of your world:

```bash
# Load identity + top memories (~600-900 tokens in typical use)
mempalace wake-up

# Project-specific context
mempalace wake-up --wing driftwood
```

This loads Layer 0 (identity) and Layer 1 (essential story) as bounded startup context before the first retrieval call.

See [Memory Stack](/concepts/memory-stack) for details on the 4-layer architecture.

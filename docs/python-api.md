# Python API

Programmatic access to MemPalace. All modules are importable from the `mempalace` package.

## Search

### mempalace.searcher

```python
from mempalace.searcher import search_memories, search, SearchError
```

#### search_memories(query, palace_path, wing=None, room=None, n_results=5) → dict

Returns structured search results. Used by the MCP server and other programmatic callers.

```python
results = search_memories(
    "auth decisions",
    palace_path="~/.mempalace/palace",
    wing="myapp",
    n_results=5,
)

for hit in results.get("results", []):
    print(f"{hit['wing']}/{hit['room']} ({hit['similarity']}): {hit['text'][:100]}")
```

Returns `{"error": "...", "hint": "..."}` if the palace doesn't exist.

#### search(query, palace_path, wing=None, room=None, n_results=5)

Prints results to stdout. Raises `SearchError` on failure.

#### SearchError

Exception raised when search cannot proceed (no palace found, collection missing, query error).

## Memory stack

### mempalace.layers

```python
from mempalace.layers import MemoryStack, Layer0, Layer1, Layer2, Layer3
```

#### MemoryStack(palace_path=None, identity_path=None)

Unified interface to all four memory layers.

```python
stack = MemoryStack(palace_path="~/.mempalace/palace")

# L0 + L1 wake-up (~600-900 tokens)
context = stack.wake_up(wing="myapp")

# L2 on-demand retrieval (metadata-filtered, no semantic search)
memories = stack.recall(wing="myapp", room="auth-migration", n_results=10)

# L3 semantic search
results = stack.search("why did we switch auth providers", wing="myapp", n_results=5)

# Layer status
status = stack.status()
```

#### Layer0(identity_path=None)

Reads `~/.mempalace/identity.txt`.

```python
l0 = Layer0()
text = l0.render()       # identity text or default message
tokens = l0.token_estimate()  # rough token count (len // 4)
```

#### Layer1(palace_path=None, wing=None)

Auto-generates an essential story from the top palace drawers.

```python
l1 = Layer1(palace_path="~/.mempalace/palace", wing="myapp")
text = l1.generate()  # compact summary of top 15 drawers (~800 tokens max)
```

#### Layer2(palace_path=None)

On-demand wing/room-filtered retrieval.

```python
l2 = Layer2(palace_path="~/.mempalace/palace")
text = l2.retrieve(wing="myapp", room="auth", n_results=10)
```

#### Layer3(palace_path=None)

Full semantic search.

```python
l3 = Layer3(palace_path="~/.mempalace/palace")

# Formatted text output
text = l3.search("auth migration", wing="myapp", n_results=5)

# Raw dict list
hits = l3.search_raw("auth migration", wing="myapp", n_results=5)
# [{"text": "...", "wing": "...", "room": "...", "source_file": "...", "similarity": 0.89, "metadata": {...}}]
```

## Knowledge graph

### mempalace.knowledge_graph

```python
from mempalace.knowledge_graph import KnowledgeGraph
```

Full API documented in [knowledge-graph.md](knowledge-graph.md).

Key methods:

```python
kg = KnowledgeGraph()

# Write
kg.add_entity("Kai", entity_type="person", properties={"role": "engineer"})
kg.add_triple("Kai", "works_on", "Orion", valid_from="2025-06-01")
kg.invalidate("Kai", "works_on", "Orion", ended="2026-03-01")

# Read
kg.query_entity("Kai", as_of="2026-01-15", direction="both")
kg.query_relationship("works_on", as_of="2026-01-15")
kg.timeline("Kai")
kg.stats()

# Cleanup
kg.close()
```

## Palace access

### mempalace.palace

```python
from mempalace.palace import get_collection, file_already_mined, SKIP_DIRS
```

#### get_collection(palace_path, collection_name="mempalace_drawers")

Get or create the ChromaDB collection.

```python
col = get_collection("~/.mempalace/palace")
count = col.count()
```

#### file_already_mined(collection, source_file, check_mtime=False) → bool

Check if a file has already been stored.

- `check_mtime=True` (project miner): returns `False` if the file was modified since last mining.
- `check_mtime=False` (convo miner): just checks existence.

#### SKIP_DIRS

Set of directory names that are always skipped during mining: `.git`, `node_modules`, `__pycache__`, `.venv`, `dist`, `build`, etc.

## Configuration

### mempalace.config

```python
from mempalace.config import MempalaceConfig, sanitize_name, sanitize_content
```

#### MempalaceConfig(config_dir=None)

Full API documented in [configuration.md](configuration.md).

```python
config = MempalaceConfig()
config.palace_path       # str
config.collection_name   # str
config.people_map        # dict
config.topic_wings       # list
config.hall_keywords     # dict

config.init()                          # create config dir + default config.json
config.save_people_map({"kai": "Kai"}) # write people_map.json
```

#### sanitize_name(value, field_name="name") → str

Validate a wing/room/entity name. Raises `ValueError` on invalid input.

#### sanitize_content(value, max_length=100_000) → str

Validate content length. Raises `ValueError` on invalid input.

## Normalization

### mempalace.normalize

```python
from mempalace.normalize import normalize
```

#### normalize(filepath) → str

Load a file and convert to transcript format if it's a recognized chat export. Plain text passes through unchanged.

Supported formats: Claude Code JSONL, Claude.ai JSON, ChatGPT JSON, Slack JSON, OpenAI Codex CLI JSONL, plain text with `>` markers.

Raises `IOError` for files that can't be read or exceed 500 MB.

## Palace graph

### mempalace.palace_graph

```python
from mempalace.palace_graph import build_graph, traverse, find_tunnels, graph_stats
```

#### build_graph(col=None, config=None) → (nodes, edges)

Build the palace graph from ChromaDB metadata.

- `nodes`: `dict[str, {"wings": list, "halls": list, "count": int, "dates": list}]`
- `edges`: `list[{"room": str, "wing_a": str, "wing_b": str, "hall": str, "count": int}]`

#### traverse(start_room, col=None, config=None, max_hops=2) → list

BFS traversal from a starting room. Returns connected rooms with hop distances.

#### find_tunnels(wing_a=None, wing_b=None, col=None, config=None) → list

Find rooms that bridge two wings.

#### graph_stats(col=None, config=None) → dict

Summary: total rooms, tunnel rooms, edges, rooms per wing, top tunnels.

## AAAK dialect

### mempalace.dialect

```python
from mempalace.dialect import Dialect
```

#### Dialect() / Dialect.from_config(config_path)

Create a dialect instance, optionally loaded from an entity config file.

```python
dialect = Dialect()
dialect = Dialect.from_config("entities.json")

compressed = dialect.compress(text, metadata={})
stats = dialect.compression_stats(original, compressed)
# {"original_chars": 500, "summary_chars": 180, "original_tokens_est": 125, "summary_tokens_est": 45, "size_ratio": 2.8, "note": "Estimates only. ..."}

token_count = Dialect.count_tokens(text)
```

See [aaak.md](aaak.md) for the dialect specification.

# MCP server

MemPalace provides an [MCP](https://modelcontextprotocol.io/) (Model Context Protocol) server that exposes 19 tools over JSON-RPC via stdin/stdout. Any MCP-compatible AI assistant can connect to it.

## Setup

### Claude Code

```bash
claude mcp add mempalace -- mempalace mcp run
```

With a custom palace path:

```bash
claude mcp add mempalace -- mempalace mcp run --palace /path/to/palace
```

### Gemini CLI

```bash
gemini mcp add mempalace mempalace mcp run --scope user
```

If using a virtual environment where `mempalace` is not on PATH, use the full path to the binary:

```bash
gemini mcp add mempalace /path/to/mempalace/.venv/bin/mempalace mcp run --scope user
```

### Direct invocation

```bash
mempalace mcp run
mempalace mcp run --palace /custom/path
```

The server reads JSON-RPC requests from stdin and writes responses to stdout. Logging goes to stderr.

`python -m mempalace.mcp_server` also works but is not recommended — it breaks in pipx environments and requires the correct Python to be on PATH.

### Show setup command

```bash
mempalace mcp
```

Prints the `claude mcp add` command with the correct path.

## Memory protocol

On first connection, the AI assistant should call `mempalace_status`. The response includes a protocol specification that instructs the AI how to use the memory system:

1. **On wake-up:** call `mempalace_status` to load the palace overview.
2. **Before responding about any person, project, or past event:** call `mempalace_kg_query` or `mempalace_search` first. Verify, don't guess.
3. **After each session:** call `mempalace_diary_write` to record what happened.
4. **When facts change:** call `mempalace_kg_invalidate` on the old fact, `mempalace_kg_add` for the new one.

## Tool reference

### Palace (read)

#### mempalace_status

Palace overview: total drawers, wing and room counts, palace path. Also returns the memory protocol and AAAK dialect spec.

**Parameters:** none

#### mempalace_list_wings

List all wings with their drawer counts.

**Parameters:** none

**Returns:** `{"wings": {"myapp": 142, "kai": 87, ...}}`

#### mempalace_list_rooms

List rooms, optionally filtered by wing.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `wing` | string | no | Filter to rooms in this wing |

#### mempalace_get_taxonomy

Full wing → room → drawer count tree.

**Parameters:** none

**Returns:** `{"taxonomy": {"myapp": {"auth": 12, "billing": 8}, ...}}`

#### mempalace_search

Semantic search across the palace. Returns verbatim text with similarity scores.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | yes | Search keywords or question (max ~200 chars recommended) |
| `limit` | integer | no | Max results (default: 5) |
| `wing` | string | no | Filter by wing |
| `room` | string | no | Filter by room |
| `context` | string | no | Background context (not used for embedding) |

**Important:** The `query` field should contain only the search terms. Do not include system prompts, conversation history, or other context — those degrade search quality. Use the `context` field for background information.

#### mempalace_check_duplicate

Check if content already exists before filing.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | yes | Content to check |
| `threshold` | number | no | Similarity threshold 0–1 (default: 0.9) |

**Returns:** `{"is_duplicate": true/false, "matches": [...]}`

#### mempalace_get_aaak_spec

Returns the AAAK dialect specification.

**Parameters:** none

### Palace (write)

#### mempalace_add_drawer

Store verbatim content in the palace. Uses a deterministic ID based on wing + room + the first 100 characters of content, so upserting the same content is a no-op when those values match. Different drawers with the same first 100 characters of content can collide.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `wing` | string | yes | Wing name |
| `room` | string | yes | Room name |
| `content` | string | yes | Verbatim text to store |
| `source_file` | string | no | Source reference |
| `added_by` | string | no | Who filed it (default: `mcp`) |

All write operations are logged to `~/.mempalace/wal/write_log.jsonl` for audit.

**Returns:** `{"success": true, "drawer_id": "...", "wing": "...", "room": "..."}`

#### mempalace_delete_drawer

Delete a drawer by ID. Irreversible (but logged in WAL).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `drawer_id` | string | yes | ID of the drawer |

### Knowledge graph

#### mempalace_kg_query

Query entity relationships with optional time filtering.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `entity` | string | yes | Entity name (e.g., `Kai`, `MyProject`) |
| `as_of` | string | no | Date filter — only facts valid at this date (YYYY-MM-DD) |
| `direction` | string | no | `outgoing`, `incoming`, or `both` (default: `both`) |

#### mempalace_kg_add

Add a fact to the knowledge graph.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subject` | string | yes | The entity doing/being something |
| `predicate` | string | yes | Relationship type (e.g., `works_on`, `daughter_of`) |
| `object` | string | yes | The connected entity |
| `valid_from` | string | no | When this became true (YYYY-MM-DD) |
| `source_closet` | string | no | Closet ID where this fact appears |

#### mempalace_kg_invalidate

Mark a fact as no longer true.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subject` | string | yes | Entity |
| `predicate` | string | yes | Relationship |
| `object` | string | yes | Connected entity |
| `ended` | string | no | When it stopped being true (YYYY-MM-DD, default: today) |

#### mempalace_kg_timeline

Chronological timeline of facts, optionally filtered to one entity.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `entity` | string | no | Entity to filter by (omit for full timeline) |

#### mempalace_kg_stats

Knowledge graph overview: entity count, triple count, current vs expired facts, relationship types.

**Parameters:** none

### Navigation

#### mempalace_traverse

Walk the palace graph from a starting room. Discovers connected rooms across wings via BFS traversal.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start_room` | string | yes | Room to start from (e.g., `auth-migration`) |
| `max_hops` | integer | no | How many connections to follow (default: 2) |

#### mempalace_find_tunnels

Find rooms that bridge two wings — topics that appear in both domains.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `wing_a` | string | no | First wing |
| `wing_b` | string | no | Second wing |

#### mempalace_graph_stats

Palace graph overview: total rooms, tunnel connections, rooms per wing.

**Parameters:** none

### Agent diary

#### mempalace_diary_write

Write a diary entry for an agent. Each agent gets its own wing with a diary room.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_name` | string | yes | Agent name (creates `wing_<name>/diary`) |
| `entry` | string | yes | Diary content (AAAK format recommended) |
| `topic` | string | no | Topic tag (default: `general`) |

#### mempalace_diary_read

Read an agent's recent diary entries.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_name` | string | yes | Agent name |
| `last_n` | integer | no | Number of recent entries (default: 10) |

## Write-ahead log

All write operations (`add_drawer`, `delete_drawer`, `kg_add`, `kg_invalidate`, `diary_write`) are logged to `~/.mempalace/wal/write_log.jsonl` before execution. This provides an audit trail for detecting memory poisoning and enables review of writes from untrusted sources.

## Input validation

Wing names, room names, entity names, and content are validated before processing:

- Names: 1–128 characters, alphanumeric plus `_ .'- `, no path traversal (`..`, `/`, `\`), no null bytes.
- Content: max 100,000 characters, no null bytes.

Invalid input returns `{"success": false, "error": "..."}`.

See [configuration.md](configuration.md) for details on the validation rules.

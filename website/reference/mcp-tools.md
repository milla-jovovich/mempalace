# MCP Tools Reference

Detailed parameter schemas for all 19 MCP tools.

## Palace — Read Tools

### `mempalace_status`

Palace overview: total drawers, wing and room counts, AAAK spec, and memory protocol.

**Parameters:** None

**Returns:** `{ total_drawers, wings, rooms, palace_path, protocol, aaak_dialect }`

---

### `mempalace_list_wings`

List all wings with drawer counts.

**Parameters:** None

**Returns:** `{ wings: { "wing_name": count } }`

---

### `mempalace_list_rooms`

List rooms within a wing (or all rooms if no wing given).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `wing` | string | No | Wing to list rooms for |

**Returns:** `{ wing, rooms: { "room_name": count } }`

---

### `mempalace_get_taxonomy`

Full wing → room → drawer count tree.

**Parameters:** None

**Returns:** `{ taxonomy: { "wing": { "room": count } } }`

---

### `mempalace_search`

Semantic search. Returns verbatim drawer content with similarity scores.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | **Yes** | What to search for |
| `limit` | integer | No | Max results (default: 5) |
| `wing` | string | No | Filter by wing |
| `room` | string | No | Filter by room |

**Returns:** `{ query, filters, results: [{ text, wing, room, source_file, similarity }] }`

---

### `mempalace_check_duplicate`

Check if content already exists in the palace before filing.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | **Yes** | Content to check |
| `threshold` | number | No | Similarity threshold 0–1 (default: 0.85–0.87) |

**Returns:** `{ is_duplicate, matches: [{ id, wing, room, similarity, content }] }`

---

### `mempalace_get_aaak_spec`

Returns the AAAK dialect specification.

**Parameters:** None

**Returns:** `{ aaak_spec: "..." }`

---

## Palace — Write Tools

### `mempalace_add_drawer`

File verbatim content into the palace. Identical content (same deterministic drawer ID) is silently skipped. For similarity-based duplicate detection before filing, use `mempalace_check_duplicate`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `wing` | string | **Yes** | Wing (project name) |
| `room` | string | **Yes** | Room (aspect: backend, decisions, etc.) |
| `content` | string | **Yes** | Verbatim content to store |
| `source_file` | string | No | Where this came from |
| `added_by` | string | No | Who is filing (default: "mcp") |

**Returns:** `{ success, drawer_id, wing, room }`

---

### `mempalace_delete_drawer`

Delete a drawer by ID. Irreversible.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `drawer_id` | string | **Yes** | ID of the drawer to delete |

**Returns:** `{ success, drawer_id }`

---

## Knowledge Graph Tools

### `mempalace_kg_query`

Query entity relationships with time filtering.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `entity` | string | **Yes** | Entity to query (e.g. "Max", "MyProject") |
| `as_of` | string | No | Date filter — only facts valid at this date (YYYY-MM-DD) |
| `direction` | string | No | `outgoing`, `incoming`, or `both` (default: `both`) |

**Returns:** `{ entity, as_of, facts: [{ direction, subject, predicate, object, valid_from, valid_to, current }], count }`

---

### `mempalace_kg_add`

Add a fact to the knowledge graph.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subject` | string | **Yes** | The entity doing/being something |
| `predicate` | string | **Yes** | Relationship type (e.g. "loves", "works_on") |
| `object` | string | **Yes** | The entity being connected to |
| `valid_from` | string | No | When this became true (YYYY-MM-DD) |
| `source_closet` | string | No | Closet ID where this fact appears |

**Returns:** `{ success, triple_id, fact }`

---

### `mempalace_kg_invalidate`

Mark a fact as no longer true.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subject` | string | **Yes** | Entity |
| `predicate` | string | **Yes** | Relationship |
| `object` | string | **Yes** | Connected entity |
| `ended` | string | No | When it stopped being true (default: today) |

**Returns:** `{ success, fact, ended }`

---

### `mempalace_kg_timeline`

Chronological timeline of facts.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `entity` | string | No | Entity to get timeline for (omit for full timeline) |

**Returns:** `{ entity, timeline: [{ subject, predicate, object, valid_from, valid_to, current }], count }`

---

### `mempalace_kg_stats`

Knowledge graph overview.

**Parameters:** None

**Returns:** `{ entities, triples, current_facts, expired_facts, relationship_types }`

---

## Navigation Tools

### `mempalace_traverse`

Walk the palace graph from a room. Find connected ideas across wings.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start_room` | string | **Yes** | Room to start from |
| `max_hops` | integer | No | How many connections to follow (default: 2) |

**Returns:** `[{ room, wings, halls, count, hop, connected_via }]`

---

### `mempalace_find_tunnels`

Find rooms that bridge two wings.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `wing_a` | string | No | First wing |
| `wing_b` | string | No | Second wing |

**Returns:** `[{ room, wings, halls, count, recent }]`

---

### `mempalace_graph_stats`

Palace graph overview: nodes, tunnels, edges, connectivity.

**Parameters:** None

**Returns:** `{ total_rooms, tunnel_rooms, total_edges, rooms_per_wing, top_tunnels }`

---

## Agent Diary Tools

### `mempalace_diary_write`

Write to your personal agent diary.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_name` | string | **Yes** | Your name — each agent gets its own wing |
| `entry` | string | **Yes** | Diary entry (in AAAK format recommended) |
| `topic` | string | No | Topic tag (default: "general") |

**Returns:** `{ success, entry_id, agent, topic, timestamp }`

---

### `mempalace_diary_read`

Read recent diary entries.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_name` | string | **Yes** | Your name |
| `last_n` | integer | No | Number of recent entries (default: 10) |

**Returns:** `{ agent, entries: [{ date, timestamp, topic, content }], total, showing }`

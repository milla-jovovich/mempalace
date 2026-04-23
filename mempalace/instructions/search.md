# MemPalace Search

When the user wants to search their MemPalace memories, follow these steps:

## 1. Parse the Search Query

Extract the core search intent from the user's message. Identify any explicit
or implicit filters:
- Wing -- a top-level category (e.g., "work", "personal", "research")
- Room -- a sub-category within a wing
- Keywords / semantic query -- the actual search terms

## 2. Determine Wing/Room Filters

If the user mentions a specific domain, topic area, or context, map it to the
appropriate wing and/or room. If unsure, omit filters to search globally. You
can discover the taxonomy first if needed.

## 3. Use MCP Tools (Preferred)

If MCP tools are available, use them in this priority order:

- mempalace_search(query, wing, room, full=false) -- Primary search tool.
  **Returns a SUMMARY by default** (drawer_id + ~30 char text preview per hit)
  to conserve tokens. Follow up with `mempalace_get_drawer` using the
  drawer_ids to fetch full verbatim content only for the hits you actually
  need. Pass `full=true` to get verbatim text in one shot (bypasses progressive
  disclosure; use only when auditing or when every hit matters).
- mempalace_get_drawer(drawer_id) -- Fetch full verbatim content for one or
  many drawer_ids. Accepts a single string **or an array of strings** for
  batch fetch. Use this after `mempalace_search` to pull details for the
  relevant hits.
- mempalace_list_wings -- Discover all available wings. Use when the user asks
  what categories exist or you need to resolve a wing name.
- mempalace_list_rooms(wing) -- List rooms within a specific wing. Use to help
  the user navigate or to resolve a room name.
- mempalace_get_taxonomy -- Retrieve the full wing/room/drawer tree. Use when
  the user wants an overview of their entire memory structure.
- mempalace_traverse(room) -- Walk the knowledge graph starting from a room.
  Use when the user wants to explore connections and related memories.
- mempalace_find_tunnels(wing1, wing2) -- Find cross-wing connections (tunnels)
  between two wings. Use when the user asks about relationships between
  different knowledge domains.

### Progressive Disclosure Pattern (token-efficient)

For most search tasks, follow this two-step flow:

1. `mempalace_search(query="...")` → returns N hits, each with `drawer_id`
   and a truncated `text` summary (marked `summary: true`). Cost: ~50-100
   tokens total.
2. Inspect summaries, pick the relevant drawer_ids, then call
   `mempalace_get_drawer(drawer_id=["id1", "id2", ...])` to fetch full
   content only for those. Cost: ~500-1000 tokens per drawer.

This is **~10x cheaper** than loading full content for every hit, and keeps
the context window lean when the search returns many weakly-relevant
candidates.

When to use `full=true` instead:
- You know every hit will be needed (e.g., summarizing all memories on a
  topic).
- You are auditing search quality and want to see raw scores against full
  text.
- The query is narrow enough that you expect 1-3 hits.

## 4. CLI Fallback

If MCP tools are not available, fall back to the CLI:

    mempalace search "query" [--wing X] [--room Y]

## 5. Present Results

When presenting search results:
- Always include source attribution: wing, room, and drawer for each result
- Show relevance or similarity scores if available
- Group results by wing/room when returning multiple hits
- Quote or summarize the memory content clearly

## 6. Offer Next Steps

After presenting results, offer the user options to go deeper:
- Drill deeper -- search within a specific room or narrow the query
- Traverse -- explore the knowledge graph from a related room
- Check tunnels -- look for cross-wing connections if the topic spans domains
- Browse taxonomy -- show the full structure for manual exploration

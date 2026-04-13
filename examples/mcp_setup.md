# MCP Integration

Claude Code setup below; see [Cursor Memory-First Workflow](#cursor-memory-first-workflow-token-aware) for Cursor.

## Setup (Claude Code)

Run the MCP server:

```bash
python -m mempalace.mcp_server
```

Or add it to Claude Code:

```bash
claude mcp add mempalace -- python -m mempalace.mcp_server
```

## Available Tools

The server exposes the full MemPalace MCP toolset. Common entry points include:

- **mempalace_status** — palace stats (wings, rooms, drawer counts)
- **mempalace_search** — semantic search across all memories
- **mempalace_list_wings** — list all projects in the palace

## Usage in Claude Code

Once configured, Claude Code can search your memories directly during conversations.

## Cursor Memory-First Workflow (Token-Aware)

This is a practical setup for Cursor users who want memory when it helps, but avoid extra token
spend on generic questions.

### 1) Save durable chat outcomes

Store important outcomes verbatim so future searches can quote exact context:

```text
tool: mempalace_add_drawer
wing: cursor
room: technical | decisions | problems | general
content: full user/assistant snippet (verbatim)
source_file: cursor-agent/chat-YYYY-MM-DD-topic
```

(`mempalace_add_drawer` checks for near-duplicates before filing; you do not need to call `mempalace_check_duplicate` first.)

Also save a compact timeline note:

```text
tool: mempalace_diary_write
agent_name: cursor-agent
topic: short-tag
entry: SESSION:YYYY-MM-DD|TOPIC:...|DECISION:...|NEXT:...|★★★
```

### 2) Query policy (reduce wasted tokens)

The same pattern applies in any MCP-capable editor, not only Cursor.

Use **memory-first** only when the user asks about prior context:

- "remember"
- "before"
- "you said"
- "last time"
- "our project setup"

Skip memory lookup for generic one-off questions (for example, "what is nginx?").

### 3) Retrieval pattern

```text
1. mempalace_search(query, wing="cursor", room=<best room>, limit=3-5)
2. If empty, optionally broaden (remove room filter, then wing filter)
3. Answer from retrieved memory only
4. If still empty, say "No stored memory yet" and answer normally
```

### 4) Suggested room mapping for chat memory

These names are a **convention for chat memory** you choose when filing drawers; they are separate from rooms MemPalace may infer from project structure elsewhere.

- `technical` - tooling, infra, implementation notes
- `decisions` - architectural/product decisions
- `problems` - incidents, bugs, blockers
- `planning` - next steps and work plans
- `general` - preferences and non-technical context

Tip: if you expect a room like `networking`, create a consistent convention in content tags
(for example `Topic: networking`) and keep storage in the closest existing room (`technical`).

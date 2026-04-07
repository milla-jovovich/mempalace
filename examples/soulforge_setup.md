# SoulForge + MemPalace Integration

[SoulForge](https://github.com/proxysoul/soulforge) is an AI coding agent with a live code intelligence system called the [Soul Map](https://github.com/proxysoul/soulforge/blob/main/docs/repo-map.md). MemPalace adds persistent memory across sessions.

- **[Soul Map](https://github.com/proxysoul/soulforge/blob/main/docs/repo-map.md)** = what is the code right now
- **[MemPalace](https://github.com/milla-jovovich/mempalace)** = what happened and why

## Quick Start

### 1. Install MemPalace

```bash
pip install mempalace
mempalace init ~/projects/my-app
```

### 2. Mine your SoulForge sessions

SoulForge stores sessions per project at `<project>/.soulforge/sessions/`. Each session is a folder with `meta.json` and `messages.jsonl`.

```bash
# Mine sessions from a project
mempalace mine ~/projects/my-app/.soulforge/sessions/ --mode convos --wing my-app

# Preview first
mempalace mine ~/projects/my-app/.soulforge/sessions/ --mode convos --wing my-app --dry-run
```

The normalizer auto-detects SoulForge JSONL and extracts:
- **User prompts** verbatim
- **Assistant responses** verbatim
- **Tool calls** as one-line summaries (e.g. `[read: src/config.ts]`)
- **Reasoning** with `[reasoning]` prefix
- **Plans** as step labels

System messages and raw tool output are excluded.

### 3. Search your history

```bash
mempalace search "why did we switch to Postgres"
mempalace search "auth migration" --wing my-app
mempalace search "connection pool timeout" --wing my-app
```

### 4. Connect as MCP server

Add MemPalace to your SoulForge [MCP config](https://github.com/proxysoul/soulforge/blob/main/docs/mcp.md) (`~/.soulforge/config.json` or `<project>/.soulforge/config.json`):

```json
{
  "mcpServers": [
    {
      "name": "mempalace",
      "command": "uvx",
      "args": ["--from", "mempalace", "python", "-m", "mempalace.mcp_server"]
    }
  ]
}
```

If you installed mempalace globally (`pip install mempalace`), you can use `"command": "python"` and `"args": ["-m", "mempalace.mcp_server"]` instead.

Your agent can then call `mempalace_search` during sessions to recall past decisions. See the [MCP tools reference](https://github.com/milla-jovovich/mempalace#mcp-server) for the full list.

## Automatic Memory via Compaction

This is the main integration point. SoulForge has a [compaction system](https://github.com/proxysoul/soulforge/blob/main/docs/compaction.md) that manages context window pressure. When the context gets full, it compacts older messages into a structured summary. With MemPalace connected as an MCP server, that summary is automatically saved to the palace.

### How compaction v2 works

SoulForge's compaction v2 builds a structured working state incrementally as the conversation happens. Every tool call, every edit, every decision is extracted in real-time into typed slots:

| Slot | What it captures |
|---|---|
| **Task** | The original user request |
| **User Requirements** | Follow-up constraints and clarifications |
| **Plan** | Active implementation steps and their status |
| **Files Touched** | Every file read/edited/created, with action summaries |
| **Key Decisions** | Architecture choices, tradeoffs, approach selections |
| **Discoveries** | Things learned about the codebase during the session |
| **Errors & Failures** | What went wrong and how it was resolved |
| **Tool Results** | Condensed output from shell commands, tests, searches |
| **Assistant Notes** | Key reasoning from the agent's responses |

This extraction happens at tool-call time, before output gets truncated, so it sees the full data. When compaction triggers (default: 70% context usage), the working state is serialized into a structured markdown summary.

### What MemPalace receives

When a `mempalace` MCP server is connected, SoulForge calls `mempalace_add_drawer` with the serialized compaction state right before it resets. The content looks like:

```markdown
## Task
Refactor the auth module to support OAuth2

## User Requirements
- Must be backwards compatible with existing JWT tokens
- Add refresh token rotation

## Files Touched
- `src/auth/oauth.ts`: created (142 lines)
- `src/auth/jwt.ts`: edited: added refreshToken field
- `src/middleware/auth.ts`: edited: added OAuth2 flow

## Key Decisions
- Chose PKCE over implicit flow for security
- Kept JWT as fallback during migration period

## Errors & Failures
- project: test src/auth/oauth.test.ts failed: missing mock for token endpoint
```

This is filed into the palace with `wing` set to the project name and `room` set to `compaction`. Every compaction event becomes a searchable drawer.

### Why this matters

Long sessions compact multiple times. Each compaction captures a snapshot of what happened in that chunk of work. Over weeks and months, the palace accumulates a structured history of every significant coding session:

```bash
# Six months later
mempalace search "OAuth2 migration decisions" --wing my-app
# → finds the compaction drawer with the exact tradeoffs and file changes

mempalace search "auth test failures" --wing my-app
# → finds what broke and how it was fixed
```

The combination is:
- **Soul Map** gives the agent live code structure (rebuilt after every edit, lives within a session)
- **Compaction v2** extracts structured context from the conversation in real-time, at zero cost (rule-based, no LLM calls)
- **MemPalace** persists that structured context across sessions via the palace and knowledge graph

No manual `mempalace mine` needed when the MCP server is connected. Compaction handles it automatically.

### Knowledge Graph Integration

Beyond the drawer, SoulForge also files structured facts from the working state into MemPalace's [knowledge graph](https://github.com/milla-jovovich/mempalace#knowledge-graph) as typed triples:

| Working state slot | Knowledge graph triple |
|---|---|
| Decisions | `project → decided → "PKCE over implicit flow"` |
| Discoveries | `project → discovered → "connection pool causes timeouts"` |
| Failures | `project → failed → "OAuth mock missing in tests"` |

These triples have temporal validity (`valid_from` timestamps), so you can query what was true at any point:

```bash
# What decisions have we made on this project?
# → mempalace_kg_query returns a timeline of every decision with dates

# What was true in January?
# → mempalace_kg_query with as_of="2026-01-20" filters to that point in time
```

MemPalace's contradiction detection also kicks in. If a new compaction files a decision that conflicts with a previous one, it flags it.

### Agent Diary

At each compaction, SoulForge writes a diary entry for the `forge` agent summarising the task, decisions, discoveries, failures, and files touched. The diary uses MemPalace's [AAAK-style format](https://github.com/milla-jovovich/mempalace#aaak-compression) for compact storage.

Over time, the forge agent builds a persistent journal of everything it has worked on. Future sessions can read the diary to pick up context:

```
TASK:Refactor auth module for OAuth2|DECISIONS:PKCE over implicit|JWT fallback during migration|FILES:src/auth/oauth.ts|src/auth/jwt.ts|src/middleware/auth.ts
```

### Wake-up Context

On the first message of each session, SoulForge fetches MemPalace's L0+L1 wake-up context (~170 tokens) for the current project. This gives the agent immediate awareness of project history before the user says anything.

The wake-up context includes critical facts, team info, and recent decisions from the palace. It's injected as a system message and costs almost nothing since it's included in the cached system prompt prefix.

## Compaction v2: Zero-Cost Extraction

Worth noting: SoulForge's compaction v2 extraction is entirely rule-based. No LLM calls are made to extract decisions, files, or failures from the conversation. The extractor runs inline at tool-call time using pattern matching:

- `extractFromToolCall` tracks file reads/edits/creates from tool args
- `extractFromToolResult` captures errors, search results, test output
- `extractFromUserMessage` captures the task and follow-up requirements
- `extractFromAssistantMessage` extracts substantive sentences (filters filler like "Let me check...")

An optional cheap LLM gap-fill pass runs only when the working state has fewer than 15 slots (early in a conversation). For most sessions, compaction is pure extraction with zero API cost.

This means the MemPalace integration adds zero token overhead. The structured data that flows into the palace was already being computed for compaction. MemPalace just persists it.

## Session Mining (Manual)

For sessions that already happened (before you connected MemPalace), or if you prefer batch processing over live MCP:

```bash
mempalace mine ~/projects/my-app/.soulforge/sessions/ --mode convos --wing my-app
```

This mines the raw JSONL transcripts. The compaction integration above is preferred for new sessions since it saves the already-structured working state rather than re-parsing raw messages.

## Session Format

SoulForge sessions are JSONL (`messages.jsonl`), one message per line:

```jsonl
{"id":"msg-1","role":"user","content":"Refactor the auth module","timestamp":1712500000000}
{"id":"msg-2","role":"assistant","content":"","timestamp":1712500005000,"durationMs":3200,"segments":[{"type":"text","content":"I'll split it into two files."},{"type":"tools","toolCallIds":["tc-1"]},{"type":"text","content":"Done."}],"toolCalls":[{"id":"tc-1","name":"edit_file","args":{"path":"src/auth.ts"},"result":{"success":true,"output":"..."}}]}
```

Both flat messages (`content` only) and the segments-based format (text, tool calls, reasoning, plans) are supported.

## What Gets Mined

| Element | Included | How |
|---|---|---|
| User messages | ✓ | Verbatim |
| Assistant text | ✓ | Verbatim |
| Tool calls | ✓ | `[tool_name: key_arg]` |
| Reasoning | ✓ | `[reasoning]` prefix, truncated to 500 chars |
| Plans | ✓ | `[plan] Step 1; Step 2; ...` |
| System prompts | ✗ | Excluded |
| Raw tool output | ✗ | Excluded |
| Images | ✗ | N/A |

## MemPalace Features Used

| Feature | How SoulForge uses it |
|---|---|
| **Palace drawers** | Compaction summaries filed per project wing |
| **Knowledge graph** | Decisions, discoveries, failures as temporal triples |
| **Contradiction detection** | Flags conflicting decisions across compactions |
| **Agent diary** | Forge agent writes session summaries in AAAK format |
| **Wake-up context** | L0+L1 injected as system message on first prompt |
| **Semantic search** | Agent calls `mempalace_search` during sessions |
| **Wing/room structure** | Wing = project name, room = compaction / auto-detected |

## Tips

- Connect MemPalace as an MCP server and let compaction handle memory automatically.
- For older sessions, run `mempalace mine` as a one-time backfill.
- Use `--wing my-app` to keep projects separate.
- Add `--extract general` to auto-classify into decisions, preferences, milestones, and problems.
- Run `mempalace wake-up --wing my-app` before a new session for a ~170 token context summary.

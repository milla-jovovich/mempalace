# MCP Integration — Claude Code

## Setup

**Plugin install (recommended):** Installs the MCP server and auto-save hooks in one step:

```bash
claude plugin add mempalace@mempalace --marketplace github:milla-jovovich/mempalace
```

**Manual install:** Add the MCP server directly:

```bash
claude mcp add mempalace -- python -m mempalace.mcp_server
```

**Standalone:** Run the MCP server outside Claude Code:

```bash
python -m mempalace.mcp_server
```

## Available Tools

The server exposes the full MemPalace MCP toolset. Common entry points include:

- **mempalace_status** — palace stats (wings, rooms, drawer counts)
- **mempalace_search** — semantic search across all memories
- **mempalace_list_wings** — list all projects in the palace

## Usage in Claude Code

Once configured, Claude Code can search your memories directly during conversations.

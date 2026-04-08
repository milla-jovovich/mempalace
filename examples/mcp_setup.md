# MCP Integration — Claude Code

## Setup

Run the MCP server:

```bash
python -m mempalace.mcp_server
```

Or add it to Claude Code:

```bash
claude mcp add mempalace -- python -m mempalace.mcp_server
```

Or add it to Antigravity MCP Config:

```bash
{
  "mcpServers": {
    "mempalace": {
      "command": "C:\\your\\python\\path\\python.exe",
      "args": [
        "-m",
        "mempalace.mcp_server"
      ],
      "disabled": false
    }
  }
}
```

file location `C:\Users\yourusername\.gemini\antigravity\mcp_config.json`

## Available Tools

The server exposes the full MemPalace MCP toolset. Common entry points include:

- **mempalace_status** — palace stats (wings, rooms, drawer counts)
- **mempalace_search** — semantic search across all memories
- **mempalace_list_wings** — list all projects in the palace

## Usage in Claude Code

Once configured, Claude Code can search your memories directly during conversations.

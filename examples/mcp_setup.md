# MCP Integration

## Local MCP clients

For Claude Code, Cursor, or any other client that can launch a local stdio server:

```bash
claude mcp add mempalace -- python -m mempalace.mcp_server
```

You can also run the server directly:

```bash
python -m mempalace.mcp_server
```

## ChatGPT custom MCP apps

ChatGPT does not connect to a local stdio server. It needs a remote HTTPS MCP endpoint.

Start MemPalace with Streamable HTTP:

```bash
python -m mempalace.mcp_server --transport streamable-http --host 0.0.0.0 --port 8000
```

The MCP endpoint will be:

```text
http://<host>:8000/mcp
```

Put that behind HTTPS with your normal deployment path or a tunnel/reverse proxy, then register the public URL in ChatGPT developer mode.

Notes:
- ChatGPT custom MCP apps are configured from ChatGPT web
- local MCP servers are not supported
- MemPalace validates `Origin` by default for `https://chatgpt.com` and `https://chat.openai.com`
- for local browser-based testing, add extra origins with `--allow-origin`

Example:

```bash
python -m mempalace.mcp_server \
  --transport streamable-http \
  --host 0.0.0.0 \
  --port 8000 \
  --allow-origin https://chatgpt.com \
  --allow-origin http://localhost:6274
```

## Available tools

- `mempalace_status` — palace stats and protocol bootstrap
- `mempalace_search` — semantic search across memories
- `mempalace_list_wings` — list wings with drawer counts
- `mempalace_list_rooms` — list rooms inside a wing
- `mempalace_get_taxonomy` — full wing/room taxonomy
- `mempalace_kg_*` — knowledge graph read/write tools
- `mempalace_diary_*` — long-term agent diary tools

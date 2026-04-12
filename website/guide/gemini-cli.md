# Gemini CLI

MemPalace works natively with [Gemini CLI](https://github.com/google/gemini-cli), which handles the MCP server and save hooks automatically.

## Prerequisites

- Python 3.9+
- Gemini CLI installed and configured

## Installation

```bash
# Clone the repository
git clone https://github.com/milla-jovovich/mempalace.git
cd mempalace

# Create a virtual environment
python3 -m venv .venv

# Install dependencies
.venv/bin/pip install -e .
```

## Initialize the Palace

```bash
.venv/bin/python3 -m mempalace init .
```

### Identity and Project Configuration (Optional)

You can optionally create or edit:

- **`~/.mempalace/identity.txt`** — plain text describing your role and focus
- **`./mempalace.yaml`** — per-project MemPalace configuration created by `mempalace init`
- **`./entities.json`** — per-project entity mappings used by AAAK compression

## Connect to Gemini CLI

Register MemPalace as an MCP server:

```bash
gemini mcp add mempalace /absolute/path/to/mempalace/.venv/bin/python3 \
  -m mempalace.mcp_server --scope user
```

::: warning
Use the **absolute path** to the Python binary to ensure it works from any directory.
:::

## Enable Auto-Saving

Add a `PreCompress` hook to `~/.gemini/settings.json`:

```json
{
  "hooks": {
    "PreCompress": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/to/mempalace/hooks/mempal_precompact_hook.sh"
          }
        ]
      }
    ]
  }
}
```

Make sure the hook scripts are executable:
```bash
chmod +x hooks/*.sh
```

## Usage

Once connected, Gemini CLI will automatically:
- Start the MemPalace server on launch
- Use `mempalace_search` to find relevant past discussions
- Use the `PreCompress` hook to save memories before context compression

### Manual Mining

Mine existing code or docs:
```bash
.venv/bin/python3 -m mempalace mine /path/to/your/project
```

### Verification

In a Gemini CLI session:
- `/mcp list` — verify `mempalace` is `CONNECTED`
- `/hooks panel` — verify the `PreCompress` hook is active

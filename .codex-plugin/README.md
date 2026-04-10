# MemPalace - Codex CLI Plugin

Give your AI a persistent memory -- mine projects and conversations into a searchable palace backed by ChromaDB, with 19 MCP tools, auto-save hooks, and guided skills.

## Prerequisites

- Python 3.9+
- Codex CLI installed and configured
- `pip install mempalace`

## Installation

### Local Install

1. Copy or symlink the `.codex-plugin` directory into your project root:

```bash
cp -r .codex-plugin /path/to/your/project/.codex-plugin
```

2. Verify the plugin is detected:

```bash
codex --plugins
```

3. Initialize your palace:

```bash
codex /init
```

### Git Install

1. Clone the MemPalace repository:

```bash
git clone https://github.com/milla-jovovich/mempalace.git
cd mempalace
```

2. Install the Python package:

```bash
pip install -e .
```

3. The `.codex-plugin` directory is already in the repo root. Codex CLI will detect it automatically when you run Codex from inside the repository.

4. Initialize your palace:

```bash
codex /init
```

## Available Skills

| Skill | Description |
|-------|-------------|
| `/help` | Show available commands and usage tips |
| `/init` | Initialize a new memory palace |
| `/search` | Semantic search across all mined memories |
| `/mine` | Mine a project or conversation into your palace |
| `/status` | Show palace status, room counts, and health |

## Hooks

The plugin includes auto-save hooks that run on session stop (every 15 messages) and before context compaction, automatically preserving conversation context into your palace.

Set the `MEMPAL_DIR` environment variable to a directory path to automatically run `mempalace mine` on that directory during each save trigger.

## Support

- Repository: https://github.com/milla-jovovich/mempalace
- Issues: https://github.com/milla-jovovich/mempalace/issues

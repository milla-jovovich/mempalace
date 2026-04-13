# CLI reference

All commands accept `--palace PATH` to override the default palace location.

## mempalace init

Detect rooms from a project's folder structure and set up the configuration.

```bash
mempalace init <dir> [--yes]
```

| Argument | Description |
|----------|-------------|
| `<dir>` | Project directory to scan |
| `--yes` | Auto-accept all detected entities (non-interactive) |

**What it does:**

1. Scans files for people and project names (entity detection)
2. Maps folders to room names using 70+ patterns
3. Creates `~/.mempalace/config.json` if it doesn't exist
4. Saves detected entities to `<dir>/entities.json`

## mempalace mine

Mine files into the palace.

```bash
mempalace mine <dir> [options]
```

| Argument | Description |
|----------|-------------|
| `<dir>` | Directory to mine |
| `--mode {projects,convos}` | Ingest mode (default: `projects`) |
| `--wing NAME` | Wing name (default: directory name) |
| `--extract {exchange,general}` | Extraction strategy for convos mode (default: `exchange`) |
| `--no-gitignore` | Don't respect `.gitignore` files |
| `--include-ignored PATHS` | Always scan these paths even if gitignored (comma-separated or repeated) |
| `--agent NAME` | Your name, recorded on every drawer (default: `mempalace`) |
| `--limit N` | Max files to process (0 = all) |
| `--dry-run` | Preview without filing |

**Examples:**

```bash
mempalace mine ~/projects/myapp
mempalace mine ~/chats/ --mode convos --wing myapp
mempalace mine ~/chats/ --mode convos --extract general
mempalace mine ~/projects/myapp --no-gitignore --include-ignored data/fixtures
mempalace mine ~/projects/myapp --dry-run --limit 10
```

## mempalace search

Semantic search across the palace.

```bash
mempalace search <query> [options]
```

| Argument | Description |
|----------|-------------|
| `<query>` | Search text |
| `--wing NAME` | Filter by wing |
| `--room NAME` | Filter by room |
| `--results N` | Number of results (default: 5) |

**Examples:**

```bash
mempalace search "why did we switch to GraphQL"
mempalace search "auth decisions" --wing myapp
mempalace search "pricing" --wing myapp --room billing --results 10
```

## mempalace split

Split concatenated transcript files into per-session files. Run before `mine --mode convos` if your exports contain multiple sessions per file.

```bash
mempalace split <dir> [options]
```

| Argument | Description |
|----------|-------------|
| `<dir>` | Directory containing transcript files |
| `--output-dir DIR` | Write split files here (default: same as source) |
| `--dry-run` | Preview without writing |
| `--min-sessions N` | Only split files with at least N sessions (default: 2) |

## mempalace wake-up

Show L0 (identity) + L1 (essential story) context. Output is designed to be pasted into an AI's system prompt.

```bash
mempalace wake-up [--wing NAME]
```

| Argument | Description |
|----------|-------------|
| `--wing NAME` | Generate wake-up for a specific project/wing |

## mempalace compress

Compress drawers using the AAAK dialect.

```bash
mempalace compress [options]
```

| Argument | Description |
|----------|-------------|
| `--wing NAME` | Wing to compress (default: all) |
| `--dry-run` | Preview without storing |
| `--config PATH` | Entity config JSON (for AAAK entity codes) |

Compressed drawers are stored in a separate `mempalace_compressed` collection, not overwriting the raw originals.

## mempalace status

Show palace overview: total drawers, wings, rooms.

```bash
mempalace status
```

## mempalace mcp

Show the MCP setup command for connecting MemPalace to your AI client.

```bash
mempalace mcp [--palace PATH]
```

## mempalace mcp run

Start the MCP server (JSON-RPC over stdin/stdout). This is the recommended way to connect MemPalace to MCP-compatible AI assistants.

```bash
mempalace mcp run [--palace PATH]
```

| Argument | Description |
|----------|-------------|
| `--palace PATH` | Override the palace directory |

## mempalace repair

Rebuild the palace vector index from stored data. Useful after ChromaDB corruption or segfaults.

```bash
mempalace repair
```

Creates a backup at `<palace_path>.backup` before rebuilding.

## mempalace migrate

Migrate the palace from a different ChromaDB version. Handles the 3.0.0 → 3.1.0 upgrade.

```bash
mempalace migrate [--dry-run]
```

## mempalace hook run

Run hook logic programmatically (reads JSON from stdin, outputs JSON to stdout).

```bash
mempalace hook run --hook {session-start,stop,precompact} --harness {claude-code,codex}
```

Used by the hook shell scripts internally. Not typically called directly.

## mempalace instructions

Output skill instructions for AI assistants.

```bash
mempalace instructions {init,search,mine,help,status}
```

Prints structured instructions to stdout. Used by AI integrations to understand how to use MemPalace.

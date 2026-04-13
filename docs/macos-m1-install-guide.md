# Installing MemPalace on macOS (Apple Silicon / M1+)

This guide covers a reliable, crash-free MemPalace installation on Apple Silicon Macs,
including concurrent multi-repo mining via separate palaces.

---

## Prerequisites

### 1. Install ARM64 Homebrew

Make sure you are running the native ARM64 Homebrew at `/opt/homebrew` (not the Rosetta
x86_64 Homebrew at `/usr/local`). Verify:

```bash
brew --prefix
# Must output: /opt/homebrew
```

If you see `/usr/local`, your shell is running under Rosetta. Open a new terminal without
Rosetta, or install ARM64 Homebrew:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2. Install ARM64 Python 3.12

MemPalace supports Python 3.9–3.12. Python 3.13+ is not yet supported (dependency
compatibility issues). Python 3.12 is recommended for Apple Silicon — it has the best
ARM64 wheel availability. Install it via the native ARM64 Homebrew:

```bash
brew install python@3.12
```

Verify the architecture:

```bash
file /opt/homebrew/bin/python3.12
# Must show: Mach-O 64-bit executable arm64
```

> **Why ARM64 matters**: MemPalace uses ChromaDB, which includes Rust-compiled HNSW
> bindings (`chromadb_rust_bindings.abi3.so`). Running x86_64 Python under Rosetta 2
> causes these bindings to crash with a SIGSEGV (null pointer dereference at address 0x88)
> during mining or MCP server startup. Native ARM64 Python eliminates this crash.

---

## Installation

### Install pipx

```bash
brew install pipx
pipx ensurepath
```

Reload your shell (`source ~/.zshrc` or open a new terminal), then verify:

```bash
which pipx
# Should output: /opt/homebrew/bin/pipx
```

### Install MemPalace

```bash
pipx install mempalace --python /opt/homebrew/bin/python3.12
```

Verify the install used ARM64 Python:

```bash
file ~/.local/pipx/venvs/mempalace/bin/python
# Must show: Mach-O 64-bit executable arm64
```

> **Note**: If you need to reinstall with a specific Python version, use `reinstall`
> rather than `install --force`. The `--python` flag is silently ignored when `--force`
> is passed:
>
> ```bash
> pipx reinstall mempalace --python /opt/homebrew/bin/python3.12
> ```

---

## MCP Server Configuration

To use MemPalace as a memory backend for Claude or other MCP-compatible clients, add it
to your MCP config. For Claude Code, this is `~/.mcp.json` (or `.mcp.json` in a project
root for per-project config). Other MCP clients (Cursor, Windsurf, etc.) use different
config paths — check their documentation.

```json
{
  "mcpServers": {
    "mempalace": {
      "type": "stdio",
      "command": "/Users/YOUR_USERNAME/.local/pipx/venvs/mempalace/bin/python",
      "args": ["-m", "mempalace.mcp_server"],
      "env": {}
    }
  }
}
```

Replace `YOUR_USERNAME` with your macOS username. Using the venv Python directly (rather
than the `mempalace` wrapper script) ensures the MCP server inherits the correct ARM64
environment.

### Pointing an MCP server at a specific palace

The MCP server reads the `MEMPALACE_PALACE_PATH` environment variable at startup. Use
this to direct each Claude instance to a different palace without touching
`~/.mempalace/config.json`.

For a **global default** (`~/.mcp.json`), leave `env` empty — the server falls back to
the path in `config.json`.

For a **project-specific palace**, add a `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "mempalace": {
      "type": "stdio",
      "command": "/Users/YOUR_USERNAME/.local/pipx/venvs/mempalace/bin/python",
      "args": ["-m", "mempalace.mcp_server"],
      "env": {
        "MEMPALACE_PALACE_PATH": "/Users/YOUR_USERNAME/.mempalace/my-project"
      }
    }
  }
}
```

This means each Claude session opened in that project directory automatically queries the
correct palace — no manual switching required. You can run as many project-specific
palaces as you like; each MCP server process is independent.

---

## Initialising and Mining

### Single repo

```bash
# Detect rooms from your project structure (writes mempalace.yaml to the project dir)
mempalace init ~/projects/my-project

# Mine the project into the default palace
mempalace mine ~/projects/my-project
```

### Multiple repos concurrently (safe pattern)

**Key rule**: never run two processes against the same palace simultaneously. Each
concurrent mine must have its own `--palace` directory. Chroma's local persistent store
is backed by SQLite, which only allows one writer at a time — concurrent writers can
produce lock errors, corrupted state, or crashes in the HNSW index. There is no safe
way to share a single palace directory across processes; use separate directories.

`init` does not need `--palace` — it only writes `mempalace.yaml` to the source directory.
Only `mine` (and other read/write commands) need `--palace`.

```bash
# Step 1: init each project (no --palace needed)
mempalace init ~/projects/project-a
mempalace init ~/projects/project-b

# Step 2: mine each into its own isolated palace (run in separate terminals)
mempalace --palace ~/.mempalace/project-a mine ~/projects/project-a
mempalace --palace ~/.mempalace/project-b mine ~/projects/project-b
```

Each palace gets its own `chroma.sqlite3` and HNSW segment directory — fully isolated,
no write contention.

### Searching across a specific palace

```bash
mempalace --palace ~/.mempalace/project-a search "authentication flow"
```

### Waking up from a specific palace

```bash
mempalace --palace ~/.mempalace/project-a wake-up
```

---

## Avoiding Common Pitfalls

### Stop the MCP server before mining into the same palace

If the MemPalace MCP server is running (e.g. via Claude Desktop or Claude Code), it holds
the ChromaDB palace open. Mining into that same palace from a separate terminal creates
concurrent write access and will crash.

Options:
- Mine into a **different palace** (`--palace ~/.mempalace/other`) — safest
- Or stop the MCP server before running `mine`, then restart it after

### x86_64 HNSW index files are not compatible with ARM64

If you previously ran MemPalace under x86_64 Python (Rosetta), the HNSW segment files in
`~/.mempalace/palace/` were written by the x86_64 chromadb process. The ARM64 process
will crash trying to open them.

Fix: wipe the palace and re-mine:

> **Warning**: `~/.mempalace/palace/` is the default palace used by all projects.
> If you have existing data you want to keep, back it up first or use
> `--palace` to mine into a separate directory instead.

```bash
rm -rf ~/.mempalace/palace/
mkdir ~/.mempalace/palace/
mempalace mine ~/projects/my-project
```

The `chroma.sqlite3` is not portable across architectures in this scenario because its
segment UUID references the now-deleted HNSW directory. Wipe both together.

---

## Memory and Disk Footprint

**RAM (per mining process):**
- ~500–700 MB per `mempalace mine` process
- Dominated by the ONNX embedding model (`all-MiniLM-L6-v2`, ~300 MB) loaded per process
- Two concurrent processes: expect ~1–1.4 GB combined

**Disk (per palace, after mining a medium codebase):**
- `chroma.sqlite3`: 50–200 MB
- `data_level0.bin`: 20–100 MB
- `link_lists.bin`: appears large in `ls -lh` (sparse pre-allocation) but actual disk
  usage is small — check with `du -sh ~/.mempalace/your-palace/`
- Total actual disk: typically **100–300 MB per palace**

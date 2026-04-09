# MemPalace — Remote ChromaDB Fork

## Goal

Add optional remote ChromaDB support via `HttpClient`, so a single
ChromaDB instance running on a server (e.g. Docker on an always-on machine)
can be shared by multiple workstations or users. Local `PersistentClient`
behaviour must remain the default — zero breaking changes for existing users.

## Background

Currently every module that touches ChromaDB hardcodes:

```python
chromadb.PersistentClient(path=palace_path)
```

This means the palace is always local. There is no way to point MemPalace
at a remote ChromaDB server, which makes multi-workstation and multi-user
setups impossible without fragile file-sync hacks.

The fix is straightforward: introduce a factory function that returns either
`PersistentClient` or `HttpClient` depending on configuration, and replace
all direct `PersistentClient(...)` calls with that factory.

## Task

### 1. Add remote config keys to `mempalace/config.py`

Add to `MempalaceConfig` (alongside existing keys):

```python
chroma_host: str | None  # e.g. "192.168.1.10" or hostname
chroma_port: int          # default 8000
chroma_ssl: bool          # default False
```

Read from `~/.mempalace/config.json`:

```json
{
  "chroma_host": "m1mini.local",
  "chroma_port": 8000,
  "chroma_ssl": false
}
```

If `chroma_host` is absent or null, behaviour is local (current default).

Also support env var overrides (higher priority than config file):
- `MEMPALACE_CHROMA_HOST`
- `MEMPALACE_CHROMA_PORT`
- `MEMPALACE_CHROMA_SSL`

### 2. Create `mempalace/palace_db.py` (new file)

Central factory — all ChromaDB access must go through this:

```python
def get_client(palace_path: str = None) -> chromadb.ClientAPI:
    """
    Returns HttpClient if remote config present, PersistentClient otherwise.
    palace_path is ignored in remote mode (server manages its own storage).
    """

def get_collection(palace_path: str = None, name: str = "mempalace_drawers"):
    """
    Returns the named collection from whichever client is active.
    Creates the collection if it does not exist.
    """
```

This file does not exist yet upstream (PR #25 proposed it but was closed).

### 3. Replace all direct ChromaDB instantiation

Find every occurrence of `chromadb.PersistentClient(` in the codebase and
replace with a call to `palace_db.get_client()` or `palace_db.get_collection()`.

Files known to contain direct instantiation (verify with grep):
- `mempalace/convo_miner.py`
- `mempalace/miner.py`
- `mempalace/searcher.py`
- `mempalace/layers.py`
- `mempalace/mcp_server.py`

Use grep to confirm the full list before editing — do not assume.

### 4. Update `mempalace/cli.py`

Add a `mempalace remote` status command:

```
mempalace remote status
```

Output should show whether remote or local mode is active, and if remote,
confirm connectivity to the ChromaDB server (attempt a `.heartbeat()` call).

### 5. Update `README.md`

Add a "Remote Mode" section after the Configuration section covering:
- When to use remote mode (multi-workstation, multi-user)
- How to run ChromaDB as a Docker container (provide the compose snippet)
- The three config keys / env vars
- A note that `palace_path` is ignored in remote mode

Docker compose snippet to include:

```yaml
services:
  chromadb:
    image: chromadb/chroma:latest
    ports:
      - "8000:8000"
    volumes:
      - ./chromadb_data:/chroma/chroma
    environment:
      - ANONYMIZED_TELEMETRY=False
```

### 6. Tests

Add `tests/test_palace_db.py` covering:
- `get_client()` returns `PersistentClient` when no host configured
- `get_client()` returns `HttpClient` when host configured (mock chromadb)
- Env var overrides take priority over config file
- `get_collection()` creates collection if absent

## Constraints

- **Do not break existing behaviour.** No host configured = identical
  behaviour to current upstream. All existing tests must still pass.
- **Do not add new required dependencies.** `chromadb` already ships
  `HttpClient` — no extra packages needed.
- **Do not touch AAAK, knowledge_graph.py, or dialect.py.**
  Those are out of scope.
  `palace_graph.py` has been migrated to use `palace_db` (no longer excluded).
- **Keep the PR focused.** This is a single-concern change: remote client
  support. Resist the temptation to refactor anything else while in there.
- Follow existing code style — no type annotation style changes, no formatter
  changes unless the file already uses one.

## Development Workflow

```bash
# Run tests
uv run python -m pytest tests/ -q --ignore=tests/benchmarks

# Lint and format (run before every commit)
uv run ruff check --fix <changed files>
uv run ruff format <changed files>

# Sync upstream changes
git fetch upstream   # upstream = git@github.com:milla-jovovich/mempalace.git
git merge upstream/main
# Conflicts in version.py / pyproject.toml / .claude-plugin/*.json / .codex-plugin/plugin.json
# are always version-number-only — resolve with:
git checkout --theirs <conflicted files> && git add <conflicted files>
```

## Commit Rules

- One commit per logical change (feat, fix, test, ci, docs, bench, chore)
- Run ruff check + format on staged files before every commit — no exceptions
- `tests/benchmarks/` = upstream's benchmark suite (do not edit); `benchmarks/` = our scripts

## Verification

After implementation, verify manually:

```bash
# Local mode (default) — must work identically to upstream
mempalace init /tmp/test-palace
mempalace mine /tmp/test-palace
mempalace search "test"

# Remote mode — requires a running ChromaDB container
docker run -p 8000:8000 chromadb/chroma:latest
MEMPALACE_CHROMA_HOST=localhost mempalace remote status
MEMPALACE_CHROMA_HOST=localhost mempalace mine /tmp/test-palace
MEMPALACE_CHROMA_HOST=localhost mempalace search "test"
```

## PR intent

This fork is intended to be contributed back upstream once the architecture
stabilises. Keep the diff minimal and the commit history clean (one logical
commit per step above, or squash to a single clean commit before PR).
The upstream maintainer has indicated preference for small,
single-concern PRs.

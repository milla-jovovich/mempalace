# Private Personal Setup

This guide is for taking MemPalace into your own private GitHub repository and using it mainly as a local tool.

## Recommended ownership model

For personal use, prefer a fresh private repository over a fork.

- Use a fork when you want to contribute back upstream and keep GitHub's fork relationship.
- Use a fresh private repository when you want isolation, private changes, and a lower chance of pushing to the original project by mistake.

## What stays in the repository

Keep these in git:

- source code in `mempalace/`
- tests in `tests/`
- packaging and dependency metadata in `pyproject.toml`
- docs, examples, and benchmarks code

Do not keep these in git:

- your real `.env` files
- API tokens or keys
- your personal palace data under `~/.mempalace/`
- local write-ahead logs and machine-specific shell settings

## One-time repository setup

### Option A: GitHub CLI authenticated

If `gh auth login` works on your machine, run:

```bash
cd /workspaces/mempalace
bash scripts/setup_private_repo.sh --repo-name supamem_koo
```

This will:

1. keep the current source repository as `upstream`
2. create your private GitHub repository
3. set your private repository as `origin`
4. push `main` and set upstream tracking

### Option B: Manual repository URL

If GitHub CLI is unavailable, create the private repository in GitHub first and then run:

```bash
cd /workspaces/mempalace
bash scripts/setup_private_repo.sh --repo-url https://github.com/<your-user>/supamem_koo.git
```

## Local install for daily use

MemPalace is designed to work locally and does not require cloud services for the core workflow.

```bash
pip install -e ".[dev]"
mempalace init ~/projects/myapp
mempalace mine ~/projects/myapp
mempalace search "why did we change auth"
```

## Where data should live

By default, your personal data lives outside the repository:

- `~/.mempalace/config.json`
- `~/.mempalace/palace/`
- `~/.mempalace/wal/write_log.jsonl`

That separation is important. The repo is for code. The palace directory is for your personal memory data.

## Safe daily workflow

Use these checks before you push:

```bash
git remote -v
git status
```

Recommended daily flow:

```bash
git pull --ff-only origin main
pytest tests/ -v
ruff check .
git push origin main
```

If you keep the original project as `upstream`, you can sync changes later with:

```bash
git fetch upstream
git merge upstream/main
```

## Risks to understand

- A private repository is access-controlled, not encrypted end to end.
- If a secret was ever committed, making the repository private does not remove that secret from history.
- Hook scripts are optional and should be reviewed before enabling automation.
- Keep API keys in environment variables or GitHub secrets, never in tracked files.

## Suggested next steps

1. Set up the private repository with the script.
2. Verify remotes and branch tracking.
3. Install locally and run a small `init -> mine -> search` cycle.
4. Add MCP or editor integrations only after the base CLI flow works.

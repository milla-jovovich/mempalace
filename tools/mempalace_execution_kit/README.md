# MemPalace execution kit

This kit executes the migration and rebrand in-place against a local checkout of the repo.

## Files

- `conventions.example.json` — edit this first
- `apply_conventions.py` — rewrites package, command, hidden-dir, plugin, and hook surfaces
- `verify_conventions.py` — scans for stale literals after rewrite
- `rename_surface_manifest.csv` — known high-impact files and why they matter
- `run_all.sh` — simple wrapper

## Usage

1. Copy the repo locally.
2. Copy `conventions.example.json` to `conventions.json`.
3. Edit the values.
4. Run:

```bash
python apply_conventions.py /path/to/repo /path/to/conventions.json
python verify_conventions.py /path/to/repo /path/to/conventions.json
```

## What the rewriter does

- renames the Python package directory
- rewrites imports from the old package to the new package
- rewrites CLI command names in docs, hooks, and examples
- rewrites `python -m <module>` launch paths
- rewrites hidden state-dir literals such as `~/.mempalace`
- rewrites collection names
- patches plugin manifests
- patches the shell hooks to use your interpreter policy
- rewrites repo URLs if requested

## What it does not do automatically

- semantic changes to retrieval behavior
- semantic changes to entity and room detection
- benchmark methodology changes
- product-positioning rewrite of docs

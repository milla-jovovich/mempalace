# Legacy v1 workflow

The following files are **legacy compatibility paths**:

- `conventions.example.json`
- `apply_conventions.py`
- `run_all.sh`

## Why they are legacy

They require more repeated target values than necessary and make drift between package, command, hidden-dir, plugin, and collection names more likely.

## When to use them

Use v1 only when:

- you already have automation built around the explicit schema
- you need a transitional bridge from an older internal process
- you want side-by-side comparison against the v2 compiler output

## Preferred replacement

Use the v2 identity-compiler path:

- `conventions.single-target.example.json`
- `compile_identity.py`
- `forge.py`
- `apply_conventions_v2.py`
- `run_all_v2.sh`
- `apply_batch_v2.py`

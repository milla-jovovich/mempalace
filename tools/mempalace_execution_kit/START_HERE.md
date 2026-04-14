# Start here

This execution kit now has a **default path** and a **legacy path**.

## Default path (v2)

Use the identity-compiler workflow.

### Single target

```bash
python forge.py plan /path/to/conventions.single-target.json
python run_all_v2.sh /path/to/repo /path/to/conventions.single-target.json
```

### Many targets

```bash
python forge.py batch-plan /path/to/batch_targets.json
python apply_batch_v2.py /path/to/batch_apply_manifest.json
```

## Why v2 is the default

- one canonical target identity
- deterministic derivation
- fewer repeated target values
- plan-before-apply
- many-target support

## Legacy path (v1)

The explicit target mapping workflow is retained only for compatibility and transition:

- `conventions.example.json`
- `apply_conventions.py`
- `run_all.sh`

See `LEGACY_V1.md`.

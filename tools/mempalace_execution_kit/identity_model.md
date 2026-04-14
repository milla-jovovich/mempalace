# Single-target identity model

Yes — this should be a drop-in target identity.

The original template is workable, but it still asks for too many repeated target values. The stronger design is:

- one canonical target object
- deterministic derivation rules
- optional overrides only when you need exceptions

## Canonical model

```json
{
  "source": {
    "package": "mempalace",
    "command": "mempalace",
    "hidden_dir": ".mempalace",
    "module_entry": "mempalace.mcp_server",
    "repo_url": "https://github.com/MemPalace/mempalace"
  },
  "target": {
    "id": "memorymesh",
    "display_name": "MemoryMesh",
    "repo_url": "https://github.com/your-org/memorymesh"
  }
}
```

## What derives automatically

From `target.id = memorymesh`, derive:

- package: `memorymesh`
- CLI command: `memorymesh`
- hidden dir: `.memorymesh`
- module entry: `memorymesh.mcp_server`
- plugin name: `memorymesh`
- collection prefix: `memorymesh_*`
- interpreter env var: `MEMORYMESH_PYTHON`

From `target.display_name = MemoryMesh`, derive:

- plugin display name
- docs-facing product name
- manifest-facing display labels

## Why this is better

- one input works across many targets
- fewer mismatched values
- fewer accidental stale literals
- easier to templatize for batch forks and rebrands
- easier to feed into CI or repo generators

## When overrides still make sense

Only for exceptions:

- command differs from package name
- hidden dir differs from package name
- plugin display name needs spaces or casing
- collection names need a legacy-compatible prefix
- interpreter env var must follow an org standard

## Recommended rule

Use:

- canonical target identity
- derived defaults everywhere
- explicit overrides only for exceptions

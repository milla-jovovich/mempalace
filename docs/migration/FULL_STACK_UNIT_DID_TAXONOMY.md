# Full-stack unit DID taxonomy

Your repo architecture defines a stable semantic layer taxonomy that every repo should conform to:

- `L0-infra`
- `L1-tools`
- `L1-mcp-servers`
- `L2-agents`
- `L2-workflows`
- `L3-observation`
- `L3-assembly`

## Modeling rule

These are not `@context` values.
They are stable **categories and URI partitions** beneath the repo root identity.

## Root identity

Use a repo root DID URL, preferably `did:webvh` for published repo identity.

Example root:

- `did:webvh:<scid>:github.com:Fleet-to-Force:mempalace#repo`

## Layered resource identifiers

Example partitioned resource identifiers:

- `did:webvh:<scid>:github.com:Fleet-to-Force:mempalace#L0-infra/runtime`
- `did:webvh:<scid>:github.com:Fleet-to-Force:mempalace#L1-tools/config-loader`
- `did:webvh:<scid>:github.com:Fleet-to-Force:mempalace#L1-mcp-servers/mempalace`
- `did:webvh:<scid>:github.com:Fleet-to-Force:mempalace#L2-agents/reviewer`
- `did:webvh:<scid>:github.com:Fleet-to-Force:mempalace#L2-workflows/conversion`
- `did:webvh:<scid>:github.com:Fleet-to-Force:mempalace#L3-observation/events`
- `did:webvh:<scid>:github.com:Fleet-to-Force:mempalace#L3-assembly/bundle`

## Semantic intent of each layer

### L0-infra
Identity, runtime substrate, environment assumptions, shared storage, transport, and trust anchors.

### L1-tools
Repo-local tooling, compilers, loaders, validators, generators, and support utilities.

### L1-mcp-servers
MCP server declarations, contracts, capabilities, and server-facing runtime manifests.

### L2-agents
Agent identities, roles, diaries, memory lanes, and agent capability attachments.

### L2-workflows
Operational workflows such as conversion, compile, verify, ingest, export, and deploy flows.

### L3-observation
Events, telemetry, traces, status, diagnostics, and observational outputs.

### L3-assembly
Compiled bundles, generated manifests, release artifacts, and graph-derived outputs.

## Practical rule

Every repo resource should be addressable as a URI or DID URL under one of those layers.
That gives you:

- stable semantic addressing
- deterministic classification
- better AI navigation
- better graph compilation
- easier cross-repo orchestration

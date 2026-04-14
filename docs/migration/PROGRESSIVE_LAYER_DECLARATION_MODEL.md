# Progressive layer declaration model

The full-stack unit must **always progress** from lower layers to higher layers.

That means:

- lower layers declare primitives and constraints
- higher layers are declared only through what lower layers make possible
- build and projection always flow upward from `L0` to `L3`

## Invariant

A higher layer must never become the hidden source of truth for a lower layer.

Instead:

- `L0-infra` declares identity, substrate, trust, storage, environment, transport, and root contracts
- `L1-tools` and `L1-mcp-servers` are declared from `L0`
- `L2-agents` and `L2-workflows` are declared from `L0 + L1`
- `L3-observation` and `L3-assembly` are declared from `L0 + L1 + L2`

## Dependency staircase

### L0-infra
Owns:

- repo root identity
- root DID namespace
- runtime substrate contracts
- storage contracts
- environment contracts
- collection contracts
- root toggle policy contracts

### L1-tools
May only declare:

- tools that can run on L0 substrate
- validators, compilers, loaders, generators, and adapters justified by L0 contracts

### L1-mcp-servers
May only declare:

- MCP servers whose interfaces, identity, and runtime assumptions are supported by L0
- server capabilities projected from the kernel and exposed through runtime contracts

### L2-agents
May only declare:

- agents whose memory lanes, capabilities, and runtime dependencies are already available from L0 and L1

### L2-workflows
May only declare:

- workflows that compose existing tools, MCP servers, agents, and substrate contracts

### L3-observation
May only declare:

- observation resources for runtime elements already declared below
- events, traces, diagnostics, and telemetry bindings for L0-L2 resources

### L3-assembly
May only declare:

- compiled bundles, generated manifests, releases, and higher-order products assembled from already declared lower-layer resources

## Practical rule

When authoring the semantic kernel:

1. declare `L0`
2. derive `L1`
3. derive `L2`
4. derive `L3`

Never author `L3` as if `L0-L2` are optional.

## Projection rule

Each higher layer is a projection over lower layers:

- `L1 = project(L0)`
- `L2 = project(L0, L1)`
- `L3 = project(L0, L1, L2)`

## Why this matters

This gives you a full-stack unit that is:

- self-contained
- universally applicable
- deterministic
- composable across repos
- easier to validate
- easier to assemble into larger systems

## Recommended implementation model

- semantic kernel stores all declarations
- compiler enforces progressive dependency ordering
- projections are emitted per layer
- runtime loads the projected products, not hand-maintained parallel truths

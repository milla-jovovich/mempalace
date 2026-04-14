# Graph-native full-stack unit kernel

The stronger architecture is not a semantic sidecar.
It is a **graph-native kernel** for every repo.

## The mistake to avoid

Do not keep treating:

- Python files
- plugin manifests
- hook configs
- capability declarations
- workflow definitions
- agent identities
- observation channels
- assembly artifacts

as independent sources of truth.

That leaves the repo fragmented.

## The stronger model

Treat the repo as a **full-stack unit graph**.
Everything operational is a projection of one semantic kernel.

## Kernel layers

### 1. Identity plane
Root `did:webvh` identity and DID URL namespace.

### 2. Semantic plane
Named graphs partitioned by your universal layer taxonomy:

- `L0-infra`
- `L1-tools`
- `L1-mcp-servers`
- `L2-agents`
- `L2-workflows`
- `L3-observation`
- `L3-assembly`

### 3. Shape plane
Validation of graph structure and required contracts.
Use SHACL shapes for semantic validity.

### 4. Projection plane
Generate operational views from the graph:

- Python runtime config
- plugin manifests
- hook configs
- CLI surfaces
- MCP server manifests
- workflow manifests
- agent registries
- observation channel maps
- assembly bundles

### 5. Runtime plane
Python becomes a kernel adapter and projection loader.

### 6. Observation plane
Telemetry, events, traces, and diagnostics are graph-addressable resources, not loose logs.

### 7. Assembly plane
Higher-order products are assembled from linked full-stack units, not ad hoc file merges.

## Named graph principle

Do not collapse everything into a flat graph.
Use named graphs or graph partitions so each layer can be compiled, validated, observed, and assembled independently.

## What this buys you

- one semantic source of truth
- deterministic generation of operational surfaces
- cross-repo composability
- clearer AI navigation and reasoning
- better policy and toggle governance
- easier multi-target projection
- more reliable assembly of larger systems from units

## What Python should become

Python should be:

- graph loader
- graph compiler
- projection generator
- runtime adapter
- validator bridge
- observer bridge

Not the place where repo truth is scattered.

## Toggles should become policy objects

Do not model toggles as simple booleans only.
Model them as policy-bearing resources:

- enabled state
- environment scope
- dependencies
- rollout state
- lifecycle state
- authority/provenance

## Capabilities should become contracts

A capability should carry:

- identity
- interface contract
n- dependencies
- projections it feeds
- observation hooks
- assembly role

## Agents and workflows should be first-class graph nodes

Agents and workflows should not be buried in docs or Python literals.
They should be typed resources with:

- identity
- role
- inputs
- outputs
- dependencies
- memory lanes
- observation bindings
- assembly bindings

## Strongest practical outcome

A repo becomes a **semantic unit** whose runtime surfaces are generated from a graph kernel.
That is the right architecture for your full-stack unit model.

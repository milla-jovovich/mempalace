# DID + LD architecture for repo identity and runtime semantics

For your use case, the strongest architecture is to make Python the **runtime adapter layer** and move repo identity, capability description, toggles, and domain structure into a semantic control plane.

## Core correction

The instinct is right, but the placement is slightly off:

- `@id` should identify the repo and sub-resources
- `@context` should define vocabulary and term mappings
- categories like configs, capabilities, domain-managers, and toggles should be represented as **typed nodes** or **named graphs**, not as the `@context` itself

## Recommended model

### Identity

Use one repo DID as the root identity.

Preferred methods:

- `did:web` for published repo identities
- `did:key` or `did:peer` for local/private/offline identities

Use DID URLs and fragments beneath that root:

- `<repo-did>#repo`
- `<repo-did>#config/default`
- `<repo-did>#capability/search`
- `<repo-did>#domain-manager/runtime`
- `<repo-did>#toggle/aaak`

## Hot vs cold split

### Hot authoring

Use YAML authoring for:

- human readability
- AI editing
- comments
- anchors and merges
- lower cognitive friction

This is best treated as **YAML-authored LD**, then compiled.

### Cold runtime

Use JSON-LD for:

- machine resolution
- deterministic builds
- canonicalization
- framing and expansion
- signatures, hashes, cache keys, and downstream tooling

## Repo layout

```text
semantics/
├── README.md
├── contexts/
│   └── core.context.jsonld
├── hot/
│   └── repo.identity.yaml
└── cold/
    └── repo.bundle.example.jsonld
```

## Domain model

The repo DID binds typed resources such as:

- `RepoProfile`
- `RuntimeConfig`
- `Capability`
- `DomainManager`
- `Toggle`
- `CollectionProfile`
- `HookProfile`

## Runtime principle

Python files should no longer be the source of truth for configuration identity.
They should become:

- loaders
- validators
- compilers
- adapters
- registries

## Operational principle

1. author in hot YAML
2. compile to cold JSON-LD
3. validate structure and identity
4. generate a plan
5. let runtime consume the cold graph

## Why this is better for your needs

- better repo composability
- better AI and human authoring ergonomics
- better machine determinism
- better multi-target generation
- better semantic introspection
- easier domain-manager-driven categorization

## Important guardrail

Do **not** invent a bespoke DID method unless absolutely necessary.
Use an existing DID method and define your repo-specific identity model on top of it.
That preserves interoperability while still giving you a strong namespace.

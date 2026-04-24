# Semantic reconciler specification

## Purpose

MemPalace already has the pieces to project one semantic authority into runtime surfaces, but it does not yet have a branch-aware reconciler that can fold upstream upgrades into that authority automatically.

This reconciler closes that gap.

## Verified starting point

The current conversion kit already enforces these properties:

- hot LD authority projects into cold runtime artifacts and packaged registries
- runtime surfaces are generated from semantic authority rather than hand-edited everywhere
- projection drift is detected in CI

That existing behavior is already present in:

- `scripts/regen_spine.sh`
- `tools/mempalace_execution_kit/project_mempalace_integrations.py`
- `tools/mempalace_execution_kit/frame_runtime_registry_from_binding_graph.py`
- `mempalace/integration_profile.py`
- `mempalace/operation_registry.py`

## Problem this reconciler solves

Git merge treats every file as a flat text artifact.

Your architecture does not.

Your architecture distinguishes:

- hot authority
- cold projection
- packaged runtime views
- atomic runtime code
- hooks and manifests
- docs and examples

So upstream fold-in should happen by policy:

1. resolve authoritative semantic sources first
2. regenerate all derived surfaces from that resolved authority
3. only escalate true atomic conflicts for review

## Design goals

- branch-aware, not file-only
- deterministic and reviewable
- supports internal fold-in within one repo
- supports external fold-in between different repos or repo templates
- policy-driven, not hard-coded to MemPalace only
- dry-run first
- emits a machine-readable reconciliation report
- preserves your LD/full-stack authority model

## Core model

### Input refs

The reconciler compares:

- `base_ref`
- `incoming_ref`
- optional `ancestor_ref`

### Reconciliation classes

Each path is classified into one of these classes:

1. `semantic_authority`
   - hot YAML-LD / JSON-LD authority
   - source-of-truth files
   - prefer policy resolution, then regenerate derived artifacts

2. `derived_projection`
   - cold projections
   - packaged runtime JSON views
   - plugin manifests and hook manifests generated from semantic authority
   - never hand-merge; always regenerate after authority resolution

3. `atomic_runtime`
   - Python code and shell scripts that embody behavior
   - attempt structured merge by policy
   - escalate to manual review if both refs changed the same path class and no safe policy exists

4. `supporting_surface`
   - docs, examples, website, benchmarks, static assets
   - safe union or incoming preference depending on policy

5. `foreign_or_unknown`
   - paths outside known policy scopes
   - report and require explicit rule

## Policy engine

A reconciler policy file defines:

- repo identity
- layer taxonomy
- path-class mappings
- class precedence
- per-class default actions
- generators to run after authority resolution
- verification commands

### Default action matrix

- `semantic_authority`
  - three-way semantic merge if possible
  - otherwise prefer `base_ref` for repo-specific authority, or `incoming_ref` for external template uplift if explicitly allowed

- `derived_projection`
  - discard both edited versions
  - regenerate from resolved semantic authority

- `atomic_runtime`
  - use explicit per-path strategy
  - examples:
    - `prefer_incoming`
    - `prefer_base`
    - `manual`
    - `patch_overlay`

- `supporting_surface`
  - prefer incoming unless excluded

## Internal mode

Internal mode means folding one branch into another inside the same repo.

Examples:

- `develop` into `build/conversion-kit`
- release sync branches

Internal mode rules:

- treat current repo semantic authority as authoritative unless incoming also changes hot authority
- if incoming changes atomic runtime files that are projection consumers, accept incoming only after runtime verification passes
- always rerun projection generation and drift verification after reconciliation

## External mode

External mode means applying the same reconciler model to another repo or many repos.

Examples:

- template repo to product repo
- source product to many target repos
- conversion foundry batch application

External mode rules:

- the policy file provides target identity derivation and path maps
- semantic authority may be transformed through a compiler before regeneration
- repo-specific overrides stay in a target overlay file, not ad hoc edits

## Verification stages

### 1. semantic verification

- required authority files exist
- canonical runtime-registry node identity is coherent
- no derived file is treated as source authority

### 2. projection verification

- regenerate all derived projections
- assert zero drift after generation

### 3. runtime verification

- run runtime validation scripts
- verify packaged and cold runtime views agree

### 4. merge-risk verification

- report unresolved atomic conflicts
- report unknown paths with no policy

## Output artifacts

The reconciler emits:

- `reconciliation-report.json`
- `reconciliation-plan.md`
- optional `manual-conflicts.json`

## MemPalace-specific default generators

After semantic authority resolution, run:

1. `scripts/regen_spine.sh`
2. `scripts/check_projection_drift.sh`
3. `scripts/validate_runtime.sh`

## MemPalace-specific authority set

Authoritative semantic files:

- `semantics/hot/**/*.yamlld`
- `semantics/hot/**/*.yaml`
- `semantics/cold/mempalace.binding.graph.jsonld`
- `semantics/contexts/**/*.jsonld`
- `semantics/frames/**/*.jsonld`
- `semantics/shapes/**/*.ttl`

Derived files:

- `semantics/cold/*.projected.json`
- `semantics/cold/*.projected.jsonld`
- `mempalace/runtime_profile.json`
- `mempalace/cli_registry.json`
- `mempalace/mcp_tool_registry.json`
- `.claude-plugin/.mcp.json`
- `.claude-plugin/plugin.json`
- `.claude-plugin/hooks/hooks.json`
- `.codex-plugin/plugin.json`
- `.codex-plugin/hooks.json`

## Safety rule

The reconciler must never silently accept edits to derived artifacts when their semantic authority differs.

It must regenerate.

## Strongest outcome

The repo gains a reusable semantic merge layer that turns upstream fold-in from a text-conflict exercise into a policy-driven authority reconciliation workflow.

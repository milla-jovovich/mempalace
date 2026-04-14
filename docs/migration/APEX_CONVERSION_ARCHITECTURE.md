# Apex conversion architecture

This is the strongest practical model for turning MemPalace into a reusable conversion foundry for many target repos.

## Core idea

Do not treat a target as a pile of repeated names.
Treat a target as a **canonical product identity** that is compiled into:

- package identity
- command identity
- hidden-dir identity
- module-entry identity
- plugin identity
- collection identity
- interpreter identity
- replacement plan

## System layers

### 1. Identity layer
One source identity and one target identity.

### 2. Compiler layer
Deterministically derives all downstream naming from the target identity.

### 3. Plan layer
Emits a dry-run plan showing exactly what will change.

### 4. Apply layer
Rewrites package, imports, docs, hooks, manifests, and collection names.

### 5. Verify layer
Scans for stale source literals.

### 6. Batch layer
Applies the same source to many targets and repo paths.

## Design rules

- one canonical target identity
- derived defaults everywhere
- overrides only for exceptions
- plan before apply
- verify after apply
- batch targets through a manifest, not ad hoc edits

## Why this is optimal

- no repeated target naming
- no drift between package, command, plugin, and hidden dir
- same system works for one repo or fifty
- deterministic and reviewable
- simple enough to stay useful

## Operational workflow

### Single target

1. Write one target identity file
2. Compile it
3. Review the plan
4. Apply it to a repo
5. Verify
6. Run lint and tests

### Many targets

1. Keep one shared source identity
2. Add many targets in a batch manifest
3. Compile plans for all targets
4. Apply each target to its mapped repo path
5. Verify each target
6. Run lint and tests per repo

## Repo-native principle

The repo should contain the conversion machinery itself:

- docs
- schema
- compiler
- rewriter
- verifier
- batch apply tools

That turns the repo from a one-off migration artifact into a reusable internal product.

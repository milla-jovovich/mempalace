# Semantics control plane

This directory is the beginning of a semantic control plane for the repo.

## Purpose

Move repo identity and declarative runtime metadata out of ad hoc Python constants and into a model that is:

- human writable
- AI writable
- machine readable
- compilable into deterministic runtime artifacts

## Structure

- `contexts/` — vocabulary and term mappings
- `hot/` — author-friendly source documents
- `cold/` — compiled machine-oriented artifacts

## Contract

- hot docs are the authoring layer
- cold docs are the runtime layer
- Python should consume cold docs, not hand-maintained scattered constants

## Current scope

The initial semantic model covers:

- repo identity
- runtime configuration
- capabilities
- domain managers
- toggles
- collection profiles
- hook profiles

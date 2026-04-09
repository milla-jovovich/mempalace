---
title: "MemPalace"
category: "Tool"
status: "active"
version: "3.0.0"
summary: "High-fidelity AI memory palace with fused lexical-semantic retrieval."
description: "MemPalace is a local-first long-term memory layer for AI agents. It implements a hybrid retrieval protocol combining ChromaDB (vector) and SQLite FTS5 (lexical) with Reciprocal Rank Fusion (RRF) to ensure perfect recall of technical symbols, exact identifiers, and code snippets alongside conceptual 'vibe' search. Built for high-entropy technical environments."
tags: ["AI", "Memory", "RAG", "KnowledgeGraph", "Python", "Local-First", "Search"]
source_url: "https://github.com/Perseusxrltd/mempalace"
collaboration_open: true
skills_needed: ["Python", "SQLite", "Information Retrieval", "ChromaDB"]
help_wanted: "Seeking maintainers for GraphRAG contextual expansion and CRDT-based cross-machine sync."
---

# MemPalace: Give your AI a long-term memory.

MemPalace acts as a persistent, structured, and auditable brain for autonomous agents. It moves beyond standard "context window" limitations by providing a local-first jurisdiction where AI memories are filed into organized "Rooms" and "Wings".

## Key Characteristics
- **Hybrid Retrieval Protocol:** Fuses Semantic (ChromaDB) and Lexical (SQLite FTS5) results using RRF. Verified +60% improvement in technical recall.
- **Local-First Jurisdiction:** No cloud dependencies, no subscriptions. Your memory stays on your machine.
- **Agent Operating Contract (SKILL):** Standardized protocol for agents to read, write, and verify memories verbatim.
- **Knowledge Graph Integration:** Relational entity-predicate-object triples with temporal validity.

## Why it matters
In complex development environments, AI agents often suffer from "The Vector Blur"—failing to retrieve exact file paths, hashes, or function names. MemPalace solves this by anchoring conceptual search to hard lexical evidence.

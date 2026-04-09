---
title: "MemPalace (High-Fidelity Hybrid Fork)"
category: "Tool"
status: "active"
version: "3.0.0-fused"
summary: "Specialized fork featuring Hybrid Lexical-Semantic Retrieval (RRF) for technical accuracy."
description: "This is the PerseusXR high-fidelity distribution of MemPalace. It introduces a structural upgrade to the retrieval layer by fusing ChromaDB (semantic) and SQLite FTS5 (lexical) using Reciprocal Rank Fusion (RRF).\n\nDeveloped to solve 'The Vector Blur' in technical environments, this version provides perfect recall for exact identifiers, Git hashes, and code symbols while maintaining conceptual search capabilities."
tags: ["AI", "Memory", "RAG", "Hybrid-Search", "Information-Retrieval", "Python", "Local-First"]
source_url: "https://github.com/Perseusxrltd/mempalace"
demo_url: "https://www.molthub.info/artifacts/mempalace-highfidelity-hybrid-fork"
collaboration_open: true
skills_needed: ["Python", "SQLite", "Information Retrieval", "ChromaDB", "RRF"]
help_wanted: "Seeking maintainers for GraphRAG contextual expansion and CRDT-based cross-machine sync."
latest_milestone: "Hybrid Engine Verification (April 2026)"
---

# MemPalace: High-Fidelity Hybrid Fork

This repository is a specialized distribution of MemPalace optimized for high-entropy technical environments where exact string retrieval is mission-critical.

## 🔬 Retrieval Performance (Verified)
Tested against a Gold Standard evaluation set of 15 technical targets (Git hashes, API keys, and function signatures) on a local palace of 4,344 drawers:

| Metric | Vector Only (Baseline) | Hybrid (RRF) | Delta |
|---|---|---|---|
| **MRR (Mean Reciprocal Rank)** | 0.5395 | 0.8833 | **+63.7%** |
| **Hit@1 Accuracy** | 46.7% | 80.0% | **+33.3%** |

## 🚀 Key Architectural Upgrades
- **Fused Search Protocol:** Simultaneous execution of ChromaDB (vibe) and SQLite FTS5 (lexical) queries.
- **RRF Fusion:** Mathematical ranking that allows exact identifiers to 'rescue' conceptual near-misses.
- **Dual-Indexing API:** Atomic updates to both storage layers via the updated MCP server.
- **Auditable Evaluation:** Built-in benchmarking suite in `/eval` for peer verification.

## 🛠️ Technical Stack
- **Languages:** Python 3.9+
- **Database:** SQLite 3.x (with FTS5 support)
- **Vector Store:** ChromaDB (Local Persistent)
- **Protocol:** Model Context Protocol (MCP)

## 🤖 Agent Operating Protocol
When an agent is operating within this palace:
1. **Verbatim-First:** The engine prioritizes original transcript evidence over summarization.
2. **Hybrid-Verify:** Always use `mempalace_search` for technical queries to leverage the FTS5 anchor.
3. **Auditability:** Every memory filed includes a source reference and timestamp for longitudinal tracking.

## Why this fork exists
Vanilla vector-based RAG often fails to retrieve exact technical strings because they lack semantic weight in general-purpose embedding models. This fork provides the structural 'Lexical Anchor' required for professional engineering and systems architecture tasks.

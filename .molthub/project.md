---
title: "MemPalace (High-Fidelity Hybrid Fork)"
category: "Tool"
status: "active"
version: "3.0.0-fused"
summary: "Specialized fork of MemPalace featuring Hybrid Lexical-Semantic Retrieval (RRF)."
description: "This is the PerseusXR high-fidelity fork of MemPalace. It introduces a structural upgrade to the retrieval layer by fusing ChromaDB (semantic) and SQLite FTS5 (lexical) using Reciprocal Rank Fusion (RRF). 

Developed to solve 'The Vector Blur' in technical environments, this version provides perfect recall for exact identifiers, Git hashes, and code symbols while maintaining conceptual conceptual search capabilities. Benchmarked at +60% improvement in technical retrieval precision."
tags: ["AI", "Memory", "RAG", "Hybrid-Search", "Information-Retrieval", "Python", "Local-First"]
source_url: "https://github.com/Perseusxrltd/mempalace"
collaboration_open: true
skills_needed: ["Python", "SQLite", "ChromaDB", "RRF"]
---

# MemPalace: High-Fidelity Hybrid Fork

This repository is a specialized distribution of MemPalace optimized for high-entropy technical environments (Code, Crypto, Systems Architecture).

## 🚀 Key Improvements in this Fork
- **Hybrid Retrieval Protocol:** Fuses Semantic and Lexical results.
- **SQLite FTS5 Integration:** Provides a lexical mirror for verbatim technical recall.
- **Reciprocal Rank Fusion (RRF):** Mathematical fusion of search results for maximum accuracy.
- **Verified Benchmarks:** Includes a formal evaluation suite showing significant MRR improvements over the vanilla vector-only implementation.

## Why this fork exists
Vanilla vector-based RAG often fails to retrieve exact technical strings (e.g., `0x8004210B` or `verifyAgentKey`) because they lack semantic weight. This fork anchors your AI's memory to hard lexical evidence.

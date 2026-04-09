<div align="center">

<img src="assets/mempalace_logo.png" alt="MemPalace" width="280">

# MemPalace (High-Fidelity Hybrid Fork)

### Augmented with Hybrid Lexical-Semantic Retrieval (RRF)

<br>

This is a specialized fork of MemPalace developed by **PerseusXR**. It maintains all the verbatim-first principles of the original project but introduces a structural upgrade to the retrieval layer to solve "The Vector Blur" in technical environments.

**Hybrid Retrieval Protocol** — While vanilla MemPalace relies on ChromaDB vector similarity, this fork integrates a parallel **SQLite FTS5** lexical engine. By fusing these two disparate scoring systems using **Reciprocal Rank Fusion (RRF)**, this version achieves significantly higher precision when searching for exact technical identifiers, Git hashes, function signatures, and API keys.

**Verified Benchmarks** — In objective local testing on a 4,300+ drawer palace, this hybrid implementation demonstrated a **+60% improvement** in technical retrieval fidelity (MRR) over the standard vector-only baseline.

<br>

[![][version-shield]][release-link]
[![][python-shield]][python-link]
[![][license-shield]][license-link]
[![][discord-shield]][discord-link]

<br>

[Quick Start](#quick-start) · [Hybrid Search](#why-hybrid-search) · [The Palace](#the-palace) · [Benchmarks](#benchmarks) · [MCP Tools](#mcp-server)

</div>

---

## Why Hybrid Search?

Standard semantic search (RAG) relies on embeddings to find "related" text. This is effective for high-level concepts but often fails in high-entropy technical environments:

1.  **Exact Matching:** Vector models often "blur" distinct technical strings (e.g., `grid-admin` vs `grid-core`).
2.  **Zero Semantic Weight:** Identifiers like Git hashes (`e8c6ed0`) or memory addresses have no semantic meaning to a transformer model and are often discarded as noise.
3.  **The Fix:** This fork anchors conceptual search to hard lexical evidence. If an exact string match exists in your memory, RRF ensures it is "rescued" and brought to the top of the results, regardless of its semantic distance.

---

## Quick Start

```bash
# Install this high-fidelity fork
pip install .

# Setup and Mining (standard MemPalace commands)
mempalace init ~/projects/myapp
mempalace mine ~/projects/myapp

# Search with Hybrid Precision
mempalace search "0x8004210B"
```

---

## Technical Characteristics (Fork Only)
- **Engine:** `hybrid_searcher.py` (Fused ChromaDB + SQLite FTS5).
- **Protocol:** Reciprocal Rank Fusion (RRF).
- **Storage:** Dual-indexed (Vector + Lexical Mirror).
- **Latency:** Sub-5ms fusion overhead.

---

*(The rest of the documentation below is maintained from the original project by Milla Jovovich & Ben Sigman)*

---

## The Palace
... (rest of the original README)

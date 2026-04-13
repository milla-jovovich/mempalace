---
layout: home

hero:
  name: MemPalace
  text: Give your AI a memory.
  tagline: "96.6% recall on LongMemEval in raw mode. Local-first, open source, and usable without an API key."
  image:
    src: /mempalace_logo.png
    alt: MemPalace
  actions:
    - theme: brand
      text: Get Started
      link: /guide/getting-started
    - theme: alt
      text: Architecture →
      link: /concepts/the-palace
    - theme: alt
      text: GitHub ↗
      link: https://github.com/MemPalace/mempalace

features:
  - icon:
      src: /icons/file-text.svg
      alt: Verbatim Storage
    title: Verbatim Storage
    details: Store source text directly instead of extracting facts up front. The raw benchmark result comes from retrieving verbatim content.
  - icon:
      src: /icons/building-2.svg
      alt: Palace Structure
    title: Palace Structure
    details: Wings and rooms give retrieval useful structure. In the project benchmarks, narrowing search scope outperformed flat search.
  - icon:
      src: /icons/search.svg
      alt: Semantic Search
    title: Semantic Search
    details: ChromaDB-powered vector search lets the model retrieve past discussions by topic, project, or room.
  - icon:
      src: /icons/git-merge.svg
      alt: Knowledge Graph
    title: Knowledge Graph
    details: Temporal entity-relationship triples in SQLite. Facts can be added, queried, and invalidated over time.
  - icon:
      src: /icons/wrench.svg
      alt: 19 MCP Tools
    title: 19 MCP Tools
    details: MCP tools expose search, filing, knowledge graph, graph navigation, and diary operations to compatible clients.
  - icon:
      src: /icons/shield-check.svg
      alt: Zero Cloud
    title: Zero Cloud
    details: Core storage and retrieval run locally on ChromaDB and SQLite. Optional reranking features can add an API dependency.
---

<style>
:root {
  --vp-home-hero-name-color: transparent;
  --vp-home-hero-name-background: linear-gradient(
    135deg,
    #4f46e5 0%,
    #06b6d4 50%,
    #8b5cf6 100%
  );
}
</style>

<div style="max-width: 688px; margin: 0 auto; padding: 48px 24px 0;">

## Verbatim Retrieval First

MemPalace starts from a simple premise: **store the source text and retrieve it well**. The benchmarked raw mode does not require an LLM extraction step.

| System | LongMemEval R@5 | API Required | Cost |
|--------|----------------|--------------|------|
| **MemPalace (hybrid)** | **100%** | Optional | Free |
| Supermemory ASMR | ~99% | Yes | — |
| **MemPalace (raw)** | **96.6%** | **None** | **Free** |
| Mastra | 94.87% | Yes | API costs |
| Mem0 | ~85% | Yes | $19–249/mo |

The raw 96.6% LongMemEval result is the baseline story: strong recall without requiring an API key or an LLM in the retrieval pipeline.

<div style="text-align: center; padding-top: 16px;">
  <a href="./reference/benchmarks" style="color: var(--vp-c-brand-1); font-weight: 500;">Full benchmark results →</a>
</div>

</div>

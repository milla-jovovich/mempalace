---
layout: home

hero:
  name: MemPalace
  text: Give your AI a memory.
  tagline: "Local-first AI memory. Verbatim storage, pluggable backend, 96.6% R@5 raw on LongMemEval — zero API calls."
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
    details: Vector search over verbatim content lets the model retrieve past discussions by topic, project, or room. Backend is pluggable.
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
    details: Core storage and retrieval run locally. Optional reranking features can add an API dependency but are not required for the benchmark path.
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

MemPalace stores source text and retrieves it with semantic search. The benchmarked raw mode does not require an LLM at any stage — no extraction, no rerank, no summarisation.

**LongMemEval retrieval recall (500 questions):**

| Mode | R@5 | LLM required |
|---|---|---|
| Raw (semantic search over verbatim text) | **96.6%** | None |
| Hybrid v4, held-out 450q | **98.4%** | None |

The raw 96.6% reproduces on any machine with the committed dataset: result JSONLs, the `seed=42` train/held-out split, and the `--mode raw` / `--held-out` runners are all in the `benchmarks/` directory of the repo.

We deliberately do not publish a side-by-side comparison against other memory systems on this page. Retrieval recall (R@5) and end-to-end QA accuracy are different metrics and are not comparable; where MemPalace can be fairly compared on the same metric, we link to the other project's published source.

<div style="text-align: center; padding-top: 16px;">
  <a href="./reference/benchmarks" style="color: var(--vp-c-brand-1); font-weight: 500;">Full benchmark methodology →</a>
</div>

</div>

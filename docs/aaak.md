---
layout: docs
title: AAAK Dialect
description: An experimental lossy abbreviation dialect for AI agents. Packs repeated entities into fewer tokens at scale. No decoder required.
eyebrow: Core Concepts
heading: AAAK Dialect (Experimental)
subtitle: A lossy abbreviation dialect for packing repeated entities into fewer tokens at scale. Not meant to be read by humans — meant to be read by your AI, fast.
prev:
  href: /palace
  label: The Palace
next:
  href: /knowledge-graph
  label: Knowledge Graph
toc:
  - { id: what,        label: What is AAAK }
  - { id: comparison,  label: English vs AAAK }
  - { id: works-with,  label: What it works with }
  - { id: how-learned, label: How your AI learns it }
---

## What is AAAK {#what}

AAAK is a **lossy** abbreviation dialect designed for AI agents. It packs
repeated entities into fewer tokens at scale — entity codes, sentence
truncation, and structured shorthand. Not meant to be read by humans — meant
to be read by your AI, fast.

- **Lossy compression** — trades fidelity for token density at scale
- **No decoder required** — it's just structured text with a universal grammar
- **No fine-tuning required** — any text-reading model can parse it immediately
- **Experimental** — on LongMemEval, AAAK scores **84.2% R@5** vs raw mode's **96.6%** (a 12.4-point regression)

> **Important:** The 96.6% headline benchmark is from **raw verbatim mode**, not AAAK. AAAK is a separate compression layer that trades recall fidelity for token density. We're iterating on it. See the [honest status note]({{ site.github_url }}#a-note-from-milla--ben--april-7-2026) in the README.
{: .callout .warning}

## English vs AAAK {#comparison}

<div class="feature-grid" markdown="1">

<div markdown="1">

#### English (~1000 tokens)

```text
Priya manages the Driftwood team:
Kai (backend, 3 years), Soren (frontend),
Maya (infrastructure), and Leo (junior,
started last month). They're building a
SaaS analytics platform. Current sprint:
auth migration to Clerk. Kai recommended
Clerk over Auth0 based on pricing and DX.
```

</div>

<div markdown="1">

#### AAAK (~120 tokens)

```text
TEAM: PRI(lead) | KAI(backend,3yr)
  SOR(frontend) MAY(infra) LEO(junior,new)
PROJ: DRIFTWOOD(saas.analytics)
SPRINT: auth.migration→clerk
DECISION: KAI.rec:clerk>auth0(pricing+dx) ★★★★
```

</div>

</div>

Fewer tokens at the cost of some fidelity. AAAK is designed for **repeated
entities at scale** — the small example above doesn't fully demonstrate the
compression benefit. At scale (hundreds of rooms, recurring entity names),
the savings become significant. Because AAAK is just structured text, your AI
reads it as fast as any other text.

## What it works with {#works-with}

AAAK works with **any model that reads text**:

- **Claude** (Opus, Sonnet, Haiku, any version)
- **GPT** (GPT-4, GPT-4o, o1, GPT-5)
- **Gemini** (1.5, 2.0, 2.5)
- **Llama** (any version — 2, 3, 3.1, 4)
- **Mistral** (7B, Mixtral, Large)
- Any other text-in / text-out LLM

Because there's no decoder, no fine-tuning, and no cloud API required, you can
run AAAK against a local Llama model and your **entire memory stack stays
offline**. ChromaDB on your machine, Llama on your machine, AAAK for
compression, zero cloud calls.

> This is why MemPalace works as a **local-first** memory system. Every other serious memory system assumes you're calling a cloud LLM to manage memory. AAAK lets you skip that entirely.
{: .callout .success}

## How your AI learns it {#how-learned}

Your AI learns AAAK automatically from the MCP server's `mempalace_status`
response on first tool call. No manual setup. No prompt engineering. No
fine-tuning.

The bootstrap payload includes:

1. The AAAK grammar reference (what the symbols mean)
2. The Palace Protocol (how to file and retrieve memories)
3. Your current critical facts (L1 layer)

Because AAAK is essentially English with a very truncated syntax, the AI
understands how to use it in seconds. It reads it, it writes it, and it never
asks you to explain.

### Where AAAK shows up

- **Wake-up context** — `mempalace wake-up` returns L0 + L1 in AAAK by default
- **Agent diaries** — [specialist agents]({{ '/agents' | relative_url }}) write their entries in AAAK
- **Search result compression** — large result sets can be returned in AAAK for efficiency
- **Knowledge graph exports** — entity timelines compress beautifully

You can inspect the dialect spec directly via the MCP tool
`mempalace_get_aaak_spec` or by running `mempalace wake-up --explain`.

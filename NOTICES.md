# Notices

## Fake MemPalace websites — April 11, 2026

Community members ([#267](https://github.com/milla-jovovich/mempalace/issues/267), [#326](https://github.com/milla-jovovich/mempalace/issues/326), [#506](https://github.com/milla-jovovich/mempalace/issues/506)) have reported fake MemPalace websites, including ones distributing malware.

**MemPalace has no website.** The only official distribution channels are:

- **GitHub**: [github.com/milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace)
- **PyPI**: [pypi.org/project/mempalace](https://pypi.org/project/mempalace/)

Anything else claiming to be an official MemPalace site is fraudulent.

---

## A note from Milla & Ben — April 7, 2026

The community caught real problems in this README within hours of launch. Here's what we got wrong and what we're doing about it.

### What we got wrong

- **The AAAK token example was incorrect.** We used a rough heuristic (`len(text)//3`) for token counts instead of an actual tokenizer. Real counts via OpenAI's tokenizer: the English example is 66 tokens, the AAAK example is 73. AAAK does not save tokens at small scales — it's designed for repeated entities at scale, and the README example was a bad demonstration of that.

- **"30x lossless compression" was overstated.** AAAK is a lossy abbreviation system (entity codes, sentence truncation). Independent benchmarks show AAAK mode scores **84.2% R@5 vs raw mode's 96.6%** on LongMemEval — a 12.4 point regression. The honest framing: AAAK trades fidelity for token density, and **the 96.6% headline number is from raw mode, not AAAK**.

- **"+34% palace boost" was misleading.** That number compares unfiltered search to wing+room metadata filtering. Metadata filtering is a standard ChromaDB feature, not a novel retrieval mechanism.

- **"Contradiction detection"** exists as a separate utility (`fact_checker.py`) but is not currently wired into the knowledge graph operations as previously implied.

- **"100% with Haiku rerank"** is real (we have the result files) but the rerank pipeline is not yet in the public benchmark scripts.

### What's still true and reproducible

- **96.6% R@5 on LongMemEval in raw mode** — 500 questions, zero API calls, independently reproduced ([#39](https://github.com/milla-jovovich/mempalace/issues/39)).
- Local, free, no subscription, no cloud, no data leaving your machine.
- The palace architecture (wings, rooms, tunnels) provides real retrieval improvements through metadata filtering.

### What we're doing

1. Rewriting the AAAK example with real tokenizer counts
2. Adding `mode raw / aaak / rooms` clearly to benchmark documentation
3. Wiring `fact_checker.py` into KG operations
4. Pinning ChromaDB to a tested range ([#100](https://github.com/milla-jovovich/mempalace/issues/100)), fixing the shell injection in hooks ([#110](https://github.com/milla-jovovich/mempalace/issues/110)), and addressing the macOS ARM64 segfault ([#74](https://github.com/milla-jovovich/mempalace/issues/74))

Thank you to everyone who filed issues and PRs in the first 48 hours. Special thanks to [@panuhorsmalahti](https://github.com/milla-jovovich/mempalace/issues/43), [@lhl](https://github.com/milla-jovovich/mempalace/issues/27), [@gizmax](https://github.com/milla-jovovich/mempalace/issues/39).

— *Milla Jovovich & Ben Sigman*

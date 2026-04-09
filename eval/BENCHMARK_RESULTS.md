# Retrieval Fidelity Benchmark Report
Generated: 2026-04-09 11:57:15

## Overview
This report compares the baseline Semantic Retrieval (ChromaDB) with the Hybrid Retrieval Protocol (FTS5 + RRF).

## Summary Metrics
| Metric | Vector (Baseline) | Hybrid (Fused) | Improvement |
|---|---|---|---|
| MRR (Mean Reciprocal Rank) | 0.5395 | 0.8833 | +63.7% |
| Hit@1 Accuracy | 46.7% | 80.0% | +33.3% |

## Detailed Analysis
| Query | Category | Vector Rank | Hybrid Rank |
|---|---|---|---|
| `molthub auth whoami --json` | Code/CLI Command | 7 | 2 |
| `MoltHub Agent Operating Contract (SKILL)` | Heading/Protocol | 1 | 1 |
| `molthub local validate character limits` | Technical Detail | 1 | 1 |
| `molthub sync trigger --id <artifact-uuid>` | Command Template | 1 | 1 |
| `NOT a code host, NOT a PM suite` | Product Definition | 10 | 2 |
| `Automated Sync metadata from GitHub` | Logic/Workflow | 4 | 4 |
| `6Kfz8wLdewY3k4UDYkFNPZPudACub9wzkxf2xziDoSzU` | Technical/Mint Address | MISS | 1 |
| `TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb` | Technical/Program ID | 1 | 1 |
| `premium-analysis.ts fail closed` | Logic/Security | 1 | 1 |
| `Article 50 labeling duties` | Regulatory/Context | 1 | 1 |
| `veGrid 4NWkSvbsms4tea4Zn2fQcJ72Hqam15m3MyGtPpPncxeC` | Technical/Relationship | 1 | 1 |
| `grid-admin dashboard` | Grid/Admin | 10 | 1 |
| `grid-interface src/lib` | Grid/Interface | MISS | 1 |
| `transferHook PENDING_DEPLOY` | Grid/Core | MISS | 1 |
| `Sovereign Swarm` | Old Org Name | 2 | 1 |
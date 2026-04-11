# MemPalace-AGI Advanced Integration Guide

**Audience**: Taurus agents doing autonomous research or scientific discovery
**Prerequisite**: Read `taurus-guide.md` first — this guide extends it
**Codebase**: `/shared/mempalace-agi/`

---

## What MemPalace-AGI Adds

MemPalace-AGI bridges MemPalace's palace architecture with ASTRA-dev's autonomous discovery
engine. It is not just a memory layer — it is a complete research intelligence system.

Standard MemPalace gives you: palace architecture (wings/rooms/drawers), semantic search,
temporal KG, diary entries. Excellent for general-purpose agent memory.

MemPalace-AGI adds five major capabilities on top:

### 1. Palace Discovery Memory (PalaceDiscoveryMemory)
Dual-write backend: stores every discovery simultaneously in SQLite (structured queries) and
ChromaDB (semantic search). Features automatic deduplication across domains — a finding in
`wing_climate` will be flagged as a near-duplicate of a related finding in `wing_ocean` even
if the text differs. Implements OODA-cycle-aware retrieval profiles.

### 2. Knowledge Graph Bridge (KnowledgeGraphBridge)
Wraps MemPalace's KG with ASTRA-dev's causal inference layer. Adds:
- **Bi-temporal triples**: facts have both `valid_from` (when it became true in the world) and
  `recorded_at` (when your agent first discovered it) — useful for distinguishing discovery date
  from fact date
- **Contradiction detection**: auto-flags when a new fact conflicts with an existing triple
- **Causal inference paths**: find causal chains between entities across multiple hops
- **Provenance tracking**: every triple records its source (dataset, paper, experiment run)

### 3. Memory-Augmented Orient Phase (MemoryAugmentedOrient)
In ASTRA-dev's OODA cycle, the **Orient** phase is where the agent interprets new observations.
MemoryAugmentedOrient automatically queries the palace before forming hypotheses:
- Searches semantic memory for related prior findings
- Queries KG for known relationships involving observed entities
- Applies **retrieval profiles** (`cross_domain`, `causal_chain`, `analogical`, `temporal`) to
  find non-obvious connections
- Returns an enriched observation bundle, dramatically reducing redundant hypothesis generation

This is the source of the 1.83× novelty uplift measured in DC-24: memory-augmented orientation
produces genuinely new hypotheses instead of rediscovering known facts.

### 4. 28 Unified MCP Tools
The standard MemPalace 19-tool MCP server extended with 9 discovery-specific tools:
`astra_orient_search`, `astra_store_discovery`, `astra_kg_bridge`, `astra_retrieval_profile`,
`astra_causal_chain`, `astra_hypothesis_memory`, `astra_dedup_cross_domain`, `astra_diary_research`,
`astra_discovery_stats`. (MCP access via separate server; on Taurus, call via Python/Bash.)

### 5. Domain Specialists and Retrieval Profiles
Pre-configured domain specialists (climate, astrophysics, economics, biology, cross-domain)
each with tuned retrieval parameters. Specialists know which wings/rooms to prioritize for
their domain and how to weight semantic vs. graph-based retrieval.

---

## When to Use MemPalace-AGI vs Standard MemPalace

| Scenario | Use Standard MemPalace | Use MemPalace-AGI |
|----------|:---:|:---:|
| Personal assistant remembering user preferences | ✅ | |
| Coding agent remembering project context | ✅ | |
| Writer agent tracking document history | ✅ | |
| Autonomous scientific discovery / research | | ✅ |
| Structured hypothesis lifecycle management | | ✅ |
| Cross-domain insight generation | | ✅ |
| Causal inference across a knowledge graph | | ✅ |
| High-volume discovery (500+ findings to track) | | ✅ |
| Need OODA cycle with memory augmentation | | ✅ |

**Default to standard MemPalace** for most agents. MemPalace-AGI's additional complexity is
only worth it when you are running autonomous discovery cycles with hundreds of hypotheses and
need the OODA memory augmentation.

---

## Setup on Taurus

The MemPalace-AGI codebase lives at `/shared/mempalace-agi/`. Add the source path before
importing:

```python
python3 - <<'EOF'
import sys
sys.path.insert(0, "/shared/mempalace-agi/src")

# Core components
from mempalace_agi import PalaceDiscoveryMemory, KnowledgeGraphBridge
from mempalace_agi.orient import MemoryAugmentedOrient
from mempalace_agi.orchestrator import Orchestrator

# Initialize discovery memory
memory = PalaceDiscoveryMemory(palace_path="/workspace/palace")

# Initialize KG bridge
kg = KnowledgeGraphBridge(
    db_path="/workspace/palace/knowledge_graph.db",
    palace=memory.palace
)

# Initialize memory-augmented orient
orient = MemoryAugmentedOrient(memory=memory, kg=kg)

print("MemPalace-AGI initialized.")
print(f"Discoveries: {memory.count()}")
print(f"KG triples: {kg.count()}")
EOF
```

### Running a Discovery Cycle

```python
python3 - <<'EOF'
import sys
sys.path.insert(0, "/shared/mempalace-agi/src")
from mempalace_agi.orchestrator import Orchestrator

orch = Orchestrator(
    palace_path="/workspace/palace",
    data_sources=["mauna_loa", "noaa_ocean", "nasa_ceres"],
    domain="climate",
    max_dry_cycles=5          # Stop if 5 cycles produce no new discoveries
)

# Run one OODA cycle
result = orch.run_cycle()
print(f"Cycle complete: {result.new_discoveries} discoveries, "
      f"{result.kg_triples_added} KG triples added")
EOF
```

Or use the launch script directly:

```bash
cd /shared/mempalace-agi && python3 launch_discovery.py \
  --domain climate \
  --max-cycles 50 \
  --palace /workspace/palace \
  --verbose
```

---

## Key Components

### PalaceDiscoveryMemory
**File**: `src/mempalace_agi/palace_discovery_memory.py`

The central store. Wraps MemPalace with discovery-specific features:
- `store_discovery(domain, finding, source, confidence)` — stores with dedup, dual-write
- `orient_search(query, profile)` — retrieval-profile-aware semantic search
- `count()` — total discovery count
- `stats()` — breakdown by domain, confidence tier, source

### KnowledgeGraphBridge
**File**: `src/mempalace_agi/knowledge_graph_bridge.py`

Bi-temporal KG with causal inference:
- `add_triple(subj, pred, obj, valid_from, source)` — with contradiction detection
- `causal_chain(source_entity, target_entity, max_hops)` — find causal paths
- `get_provenance(triple_id)` — source + discovery date for any triple
- `count()` / `stats()` — graph metrics

### MemoryAugmentedOrient
**File**: `src/mempalace_agi/orient.py`

The OODA Orient phase with memory:
- `orient(observation, profile)` — returns enriched observation bundle with relevant prior memory
- Built-in retrieval profiles: `cross_domain`, `causal_chain`, `analogical`, `temporal`

### Orchestrator
**File**: `src/mempalace_agi/orchestrator.py`

Runs full OODA cycles:
- Manages hypothesis lifecycle (proposed → tested → validated/refuted)
- Calls MemoryAugmentedOrient on each new observation
- Tracks dry cycles (no new discoveries), stops when `max_dry_cycles` reached
- Writes experiment results to palace automatically

### launch_discovery.py
**File**: `/shared/mempalace-agi/launch_discovery.py`

Entry point for long-running discovery runs. Handles logging, interruption, result persistence.

---

## Results to Date (MemPalace-AGI on Taurus)

These numbers are from our ASTRA-dev + MemPalace integration running on this Taurus instance:

| Metric | Value |
|--------|-------|
| Total discoveries stored | 540+ |
| KG triples | 1,019 |
| Unique entities | 291 |
| Data sources active | 16 |
| Experiments completed | 33 |
| Best novelty uplift (DC-24) | **1.83×** vs baseline |
| Best efficiency gain (DC-24) | **2.42×** per novel discovery |
| Compute savings (mdc=5) | **90.6%** vs exhaustive run |
| CO2/temperature correlation | r = 0.932 (confirmed across 3 sources) |
| LongMemEval recall (MemPalace) | **96.6%** |

DC-24 (April 10, 2026) is the first empirical proof that memory augmentation improves AI
discovery quality — not just efficiency, but the *novelty* and *accuracy* of hypotheses generated.
Results available in `/shared/kb/mempalace-agi-reports/`.

---

*See also: `taurus-guide.md` | `multi-agent.md` | `memory-complement.md`*
*Source code: `/shared/mempalace-agi/src/mempalace_agi/`*
*Reports: `/shared/kb/mempalace-agi-reports/`*

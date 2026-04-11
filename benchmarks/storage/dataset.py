"""Deterministic synthetic dataset generator for the storage benchmark.

We do NOT use a real embedding model. The storage layer doesn't care
whether vectors encode real semantics — what matters for a storage
benchmark is the shape, dtype, distribution, and access pattern. Using
synthetic vectors:

  - removes sentence-transformers as a dependency of the benchmark harness
  - makes dataset generation O(seconds) even at 1M rows
  - guarantees bit-identical inputs across runs and across adapters
  - isolates storage perf from embedding perf (the explicit goal)

Vectors are drawn from a standard normal distribution and L2-normalized,
which matches the distribution of MiniLM-style sentence embeddings
closely enough that nothing in the storage layer behaves differently.

The palace structure (wings, rooms, source files) is modeled faithfully
so wing/room filtering benchmarks reflect real palace access patterns.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


VECTOR_DIM = 384


SCALE_CONFIGS: dict[str, dict[str, int]] = {
    "small":  {"drawers":   1_000, "wings":  3, "rooms_per_wing":  5, "queries": 100},
    "medium": {"drawers":  10_000, "wings":  8, "rooms_per_wing": 12, "queries": 200},
    "large":  {"drawers":  50_000, "wings": 15, "rooms_per_wing": 20, "queries": 200},
    "stress": {"drawers": 100_000, "wings": 25, "rooms_per_wing": 30, "queries": 200},
    "huge":   {"drawers": 1_000_000, "wings": 50, "rooms_per_wing": 40, "queries": 200},
}


@dataclass(frozen=True)
class Drawer:
    id: str
    vector: np.ndarray  # unused — vectors are kept in a batched array for speed
    wing: str
    room: str
    source_file: str
    text: str


@dataclass(frozen=True)
class BenchDataset:
    """A fully-materialized dataset ready to hand to any adapter."""

    ids: list[str]
    vectors: np.ndarray  # (N, 384) float32, L2-normalized
    metadatas: list[dict[str, Any]]
    texts: list[str]
    query_vectors: np.ndarray  # (Q, 384) float32
    query_wheres: list[dict[str, Any] | None]
    # Ground-truth top-k per query, computed once via exact brute-force for
    # the correctness gate. Index is the row in `vectors`.
    ground_truth_top_k: np.ndarray  # (Q, K) int64

    @property
    def n(self) -> int:
        return len(self.ids)

    @property
    def q(self) -> int:
        return self.query_vectors.shape[0]


# ── generator ─────────────────────────────────────────────────────────


def generate(
    scale: str,
    *,
    seed: int = 1337,
    gt_k: int = 10,
    cache_dir: Path | None = None,
    compute_ground_truth: bool = True,
) -> BenchDataset:
    """Produce a deterministic dataset for a given scale.

    If ``cache_dir`` is provided, the generated arrays are memoized there
    so the (slow) ground-truth brute-force only runs once per (scale, seed).
    If ``compute_ground_truth`` is False, the returned dataset has an empty
    ``ground_truth_top_k`` — use this for timing-only runs at scales where
    the full (Q × N) score matrix wouldn't fit in RAM.
    """
    if scale not in SCALE_CONFIGS:
        raise ValueError(f"unknown scale {scale!r}; choose from {list(SCALE_CONFIGS)}")
    cfg = SCALE_CONFIGS[scale]

    if cache_dir is not None and compute_ground_truth:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{scale}_seed{seed}_k{gt_k}.npz"
        if cache_file.exists():
            return _load_from_cache(cache_file)

    n = cfg["drawers"]
    n_wings = cfg["wings"]
    n_rooms_per_wing = cfg["rooms_per_wing"]
    n_queries = cfg["queries"]

    rng = np.random.default_rng(seed)

    # Wings and rooms: deterministic names, not reused from the mempalace
    # benchmark vocabulary so there's no name collision with the existing
    # suite running from the same working directory.
    wings = [f"wing_{i:03d}" for i in range(n_wings)]
    rooms_by_wing = {
        w: [f"room_{w}_{j:02d}" for j in range(n_rooms_per_wing)] for w in wings
    }

    # Metadata: uniform distribution across (wing, room) × files. We also
    # model source files — a typical palace has ~10-50 drawers per source
    # file, so we assign one source file per ~20 drawers.
    ids: list[str] = []
    metadatas: list[dict[str, Any]] = []
    texts: list[str] = []
    drawers_per_file = 20
    file_counter = 0
    for i in range(n):
        wing = wings[i % n_wings]
        rooms = rooms_by_wing[wing]
        room = rooms[(i // n_wings) % n_rooms_per_wing]
        if i % drawers_per_file == 0:
            file_counter += 1
        source_file = f"/synth/{wing}/{room}/file_{file_counter:06d}.txt"
        ids.append(f"d_{i:08d}")
        metadatas.append(
            {
                "wing": wing,
                "room": room,
                "source_file": source_file,
                "chunk_index": i % drawers_per_file,
            }
        )
        # Synthetic text: ~300 chars, realistic-ish size for a drawer.
        texts.append(
            f"synthetic_drawer_{i:08d} wing={wing} room={room} "
            f"lorem ipsum dolor sit amet consectetur adipiscing elit sed do "
            f"eiusmod tempor incididunt ut labore et dolore magna aliqua "
            f"ut enim ad minim veniam quis nostrud exercitation ullamco "
            f"laboris nisi ut aliquip ex ea commodo consequat duis aute "
            f"irure dolor in reprehenderit in voluptate velit esse cillum "
            f"dolore eu fugiat nulla pariatur excepteur sint occaecat "
            f"cupidatat non proident sunt in culpa qui officia deserunt"
        )

    vectors = _unit_normal(rng, n, VECTOR_DIM)

    # Query set: mix of pure vectors + wing-filtered + wing+room-filtered.
    query_vectors = _unit_normal(rng, n_queries, VECTOR_DIM)
    query_wheres: list[dict[str, Any] | None] = []
    for i in range(n_queries):
        slot = i % 3
        if slot == 0:
            query_wheres.append(None)
        elif slot == 1:
            query_wheres.append({"wing": wings[i % n_wings]})
        else:
            wing = wings[i % n_wings]
            query_wheres.append(
                {"wing": wing, "room": rooms_by_wing[wing][i % n_rooms_per_wing]}
            )

    # Ground truth: exact top-k per query. At 1M × 200 queries this is a
    # (200, 1M) score matrix = 800 MB, which is why it's optional.
    if compute_ground_truth:
        ground_truth_top_k = _brute_force_topk(
            vectors, query_vectors, query_wheres, metadatas, gt_k
        )
    else:
        ground_truth_top_k = np.full((n_queries, gt_k), -1, dtype=np.int64)

    ds = BenchDataset(
        ids=ids,
        vectors=vectors,
        metadatas=metadatas,
        texts=texts,
        query_vectors=query_vectors,
        query_wheres=query_wheres,
        ground_truth_top_k=ground_truth_top_k,
    )

    if cache_dir is not None and compute_ground_truth:
        _save_to_cache(cache_file, ds)

    return ds


# ── helpers ───────────────────────────────────────────────────────────


def _unit_normal(rng: np.random.Generator, n: int, d: int) -> np.ndarray:
    """Draw N unit-norm vectors in R^d, dtype float32, c-contiguous."""
    v = rng.standard_normal((n, d), dtype=np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    v /= norms
    return np.ascontiguousarray(v)


def _brute_force_topk(
    vectors: np.ndarray,
    query_vectors: np.ndarray,
    query_wheres: list[dict[str, Any] | None],
    metadatas: list[dict[str, Any]],
    k: int,
) -> np.ndarray:
    """Compute exact top-k rows per query with the same filter semantics the
    adapters see, so the ground truth matches what a correct adapter returns.

    This is the ONLY place in the benchmark where we do a full N-by-Q dot
    product. It runs once per dataset and is cached.
    """
    q_count = query_vectors.shape[0]
    result = np.full((q_count, k), -1, dtype=np.int64)
    scores_full = query_vectors @ vectors.T  # (Q, N)

    # Pre-index rows by wing and (wing, room) so the filter apply is cheap.
    wing_rows: dict[str, np.ndarray] = {}
    wr_rows: dict[tuple[str, str], np.ndarray] = {}
    wings = [m["wing"] for m in metadatas]
    rooms = [m["room"] for m in metadatas]
    unique_wings = sorted(set(wings))
    for w in unique_wings:
        wing_rows[w] = np.array(
            [i for i, mw in enumerate(wings) if mw == w], dtype=np.int64
        )
    seen: set[tuple[str, str]] = set()
    for w, r in zip(wings, rooms):
        seen.add((w, r))
    for w, r in seen:
        wr_rows[(w, r)] = np.array(
            [i for i, (mw, mr) in enumerate(zip(wings, rooms)) if mw == w and mr == r],
            dtype=np.int64,
        )

    for qi in range(q_count):
        where = query_wheres[qi]
        if where is None:
            candidates = np.arange(len(metadatas), dtype=np.int64)
        elif "room" in where:
            candidates = wr_rows.get((where["wing"], where["room"]), np.empty(0, np.int64))
        else:
            candidates = wing_rows.get(where["wing"], np.empty(0, np.int64))

        if candidates.size == 0:
            continue
        row_scores = scores_full[qi, candidates]
        k_local = min(k, candidates.size)
        part = np.argpartition(-row_scores, k_local - 1)[:k_local]
        order = part[np.argsort(-row_scores[part])]
        result[qi, :k_local] = candidates[order]

    return result


# ── cache I/O ─────────────────────────────────────────────────────────


def _save_to_cache(path: Path, ds: BenchDataset) -> None:
    # metadatas/texts/wheres are serialized as object arrays. npz handles
    # this natively; not the fastest but fine for the O(seconds) warm-up.
    import pickle

    extras_path = path.with_suffix(".pkl")
    np.savez(
        path,
        vectors=ds.vectors,
        query_vectors=ds.query_vectors,
        ground_truth_top_k=ds.ground_truth_top_k,
    )
    with extras_path.open("wb") as f:
        pickle.dump(
            {
                "ids": ds.ids,
                "metadatas": ds.metadatas,
                "texts": ds.texts,
                "query_wheres": ds.query_wheres,
            },
            f,
        )


def _load_from_cache(path: Path) -> BenchDataset:
    import pickle

    extras_path = path.with_suffix(".pkl")
    with np.load(path) as npz:
        vectors = npz["vectors"]
        query_vectors = npz["query_vectors"]
        ground_truth_top_k = npz["ground_truth_top_k"]
    with extras_path.open("rb") as f:
        extras = pickle.load(f)
    return BenchDataset(
        ids=extras["ids"],
        vectors=vectors,
        metadatas=extras["metadatas"],
        texts=extras["texts"],
        query_vectors=query_vectors,
        query_wheres=extras["query_wheres"],
        ground_truth_top_k=ground_truth_top_k,
    )

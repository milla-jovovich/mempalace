"""
PalaceStore — bespoke storage layer for the MemPalace model.

Design bet: at mempalace scale, per-wing flat brute-force cosine beats HNSW on
both recall (it's exact by construction) and robustness (no graph rebuild, no
sparse-file bloat, no ef_construction resize cascade). The palace hierarchy
becomes structural: wing filtering is shard selection, not a post-filter.

Layout on disk:

    <root>/
      meta.sqlite          -- WAL mode, metadata + text + row pointers
      vectors/
        <wing>.vec         -- append-only fixed-stride float32 (DIM*4 B/row)

The query path:

    1. Resolve shards from `where.wing` (or fan out across all shards).
    2. For each shard: mmap'd (N, DIM) matrix, compute dot product with the
       query vector (BLAS mat-vec), argpartition top-k_over per shard.
    3. Merge candidates globally, join with SQLite for text + metadata, apply
       `where.room` as a cheap post-filter on the already-small candidate set.

Vectors must be L2-normalized before `upsert`. Cosine similarity then reduces
to the dot product, which is all the query path computes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np


VECTOR_DIM = 384
VECTOR_DTYPE = np.float32
BYTES_PER_VECTOR = VECTOR_DIM * 4  # 1536 bytes


# ── public result type ────────────────────────────────────────────────


@dataclass(frozen=True)
class QueryResult:
    id: str
    score: float
    text: str
    wing: str
    room: str
    metadata: dict


# ── vector shard ──────────────────────────────────────────────────────


class VectorShard:
    """Append-only fixed-stride float32 file, mmap'd for reads.

    Row `i` lives at byte offset `i * BYTES_PER_VECTOR`. The file grows only
    through `append()`; deletes are soft (tombstones live in SQLite).

    The row count is cached and kept in sync by ``append()`` so the query
    hot path does not issue a ``stat()`` syscall per shard per query.

    The score computation for this shard is ``np.matmul(mat, q, out=buf)``
    which dispatches to OpenBLAS sgemv. See store.query() for where that
    gets called.
    """

    __slots__ = ("path", "_mmap", "_num_rows")
    dtype_label = "float32"

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()
        self._mmap: np.memmap | None = None
        self._num_rows: int = self.path.stat().st_size // BYTES_PER_VECTOR

    def append(self, vectors: np.ndarray) -> int:
        """Append an (N, DIM) float32 array. Returns the first row index."""
        if vectors.size == 0:
            return self._num_rows
        if vectors.dtype != VECTOR_DTYPE:
            raise TypeError(f"expected {VECTOR_DTYPE}, got {vectors.dtype}")
        if vectors.ndim != 2 or vectors.shape[1] != VECTOR_DIM:
            raise ValueError(f"expected (N, {VECTOR_DIM}), got {vectors.shape}")
        if not vectors.flags.c_contiguous:
            vectors = np.ascontiguousarray(vectors)

        first_row = self._num_rows
        with self.path.open("ab") as f:
            f.write(vectors.tobytes(order="C"))
        self._num_rows = first_row + len(vectors)
        self._invalidate_mmap()
        return first_row

    def num_rows(self) -> int:
        return self._num_rows

    def as_matrix(self) -> np.ndarray:
        """Zero-copy (N, DIM) view of the whole shard. Empty array if size=0."""
        n = self._num_rows
        if n == 0:
            return np.empty((0, VECTOR_DIM), dtype=VECTOR_DTYPE)
        if self._mmap is None or self._mmap.shape[0] != n:
            # Drop the old mapping before creating a new one so the file can
            # grow without aliasing an obsolete window.
            self._mmap = None
            self._mmap = np.memmap(self.path, dtype=VECTOR_DTYPE, mode="r", shape=(n, VECTOR_DIM))
        return self._mmap

    def _invalidate_mmap(self) -> None:
        self._mmap = None

    def touch(self) -> None:
        """Force all shard pages into the OS page cache.

        We issue a single ``sum()`` over the mmap'd array which walks every
        page once. After this call the cost of the first real query is the
        same as the cost of a warm-cache query — no mmap first-touch tail.

        This is a cheap alternative to ``mlock`` that works without root or
        raised ``ulimit -l``. Pages can still be evicted under memory
        pressure; use ``mlock()`` if you need a hard guarantee.
        """
        if self._num_rows == 0:
            return
        mat = self.as_matrix()
        if mat.size == 0:
            return
        # Faster than ``.sum()``: a single read through the buffer with no
        # arithmetic. np.any() short-circuits but still pages everything in
        # if every element is zero — which never happens for real vectors.
        _ = mat.sum(dtype=np.float32)

    def mlock(self) -> bool:
        """Lock all shard pages into RAM via POSIX ``mlock()``.

        Returns True on success, False if the call failed (typically
        ``EAGAIN``/``ENOMEM`` from a low ``ulimit -l``). Failure is not
        raised — the caller keeps warm pages even if it can't pin them.
        """
        if self._num_rows == 0:
            return True
        mat = self.as_matrix()
        if mat.size == 0:
            return True
        return _mlock_array(mat)

    def disk_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except FileNotFoundError:
            return 0

    def compute_scores(self, query_vector: np.ndarray, out: np.ndarray) -> None:
        """Write cosine scores for this shard into ``out`` (shape (num_rows,))."""
        mat = self.as_matrix()
        if mat.shape[0] == 0:
            return
        # BLAS sgemv via np.matmul(out=). The out= form is the hot path —
        # plain ``mat @ q`` is ~100x slower because it allocates an output
        # buffer every call.
        np.matmul(mat, query_vector, out=out)


# ── int8 quantized shard ──────────────────────────────────────────────


class VectorShardI8:
    """Per-row scalar-quantized int8 shard.

    Layout: two parallel files per wing —
        vectors/{wing}.i8    N × 384 int8 (388 bytes/row in total with .scl)
        vectors/{wing}.scl   N × float32 (the per-row scale)

    On ingest, each f32 vector is quantized to int8 in ``[-127, 127]`` with
    a scale equal to ``max(|v|) / 127``. The cosine score recovered by the
    query path is::

        scores[i] = scales[i] * sum_j(mat_i8[i, j] * q_f32[j])

    The first multiply (int8 × f32) auto-promotes via numpy — there is no
    BLAS int8 path in pure numpy, so the dot product runs ~5x slower than
    the f32 shard at the same scale. In exchange, on-disk size and RAM
    footprint drop by ~4x. This is a real tradeoff, not a speed win.
    """

    __slots__ = ("vec_path", "scl_path", "_i8_mmap", "_scl_mmap", "_num_rows")
    dtype_label = "int8"

    BYTES_PER_VECTOR = VECTOR_DIM  # 384 int8 bytes per row
    SCALE_BYTES = 4

    def __init__(self, vec_path: Path, scl_path: Path):
        self.vec_path = vec_path
        self.scl_path = scl_path
        self.vec_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.vec_path.exists():
            self.vec_path.touch()
        if not self.scl_path.exists():
            self.scl_path.touch()
        vec_rows = self.vec_path.stat().st_size // self.BYTES_PER_VECTOR
        scl_rows = self.scl_path.stat().st_size // self.SCALE_BYTES
        if vec_rows != scl_rows:
            raise RuntimeError(
                f"int8 shard rows mismatch: {vec_rows} vectors vs {scl_rows} scales "
                f"in {self.vec_path.parent}. Crash during ingest?"
            )
        self._num_rows = vec_rows
        self._i8_mmap: np.memmap | None = None
        self._scl_mmap: np.memmap | None = None

    def num_rows(self) -> int:
        return self._num_rows

    def append(self, vectors_f32: np.ndarray) -> int:
        """Quantize an (N, 384) f32 array and append. Returns first row index."""
        if vectors_f32.size == 0:
            return self._num_rows
        if vectors_f32.dtype != VECTOR_DTYPE:
            raise TypeError(f"expected {VECTOR_DTYPE}, got {vectors_f32.dtype}")
        if vectors_f32.ndim != 2 or vectors_f32.shape[1] != VECTOR_DIM:
            raise ValueError(f"expected (N, {VECTOR_DIM}), got {vectors_f32.shape}")
        if not vectors_f32.flags.c_contiguous:
            vectors_f32 = np.ascontiguousarray(vectors_f32)

        # Per-row max-abs → scale. Zero rows get a 1.0 sentinel so the
        # divide is safe; they dequantize to all zeros which scores 0.
        abs_max = np.max(np.abs(vectors_f32), axis=1)
        abs_max = np.maximum(abs_max, 1e-10).astype(np.float32)
        inv_scale = (127.0 / abs_max).astype(np.float32)
        q = np.round(vectors_f32 * inv_scale[:, None]).astype(np.int8)
        scales = (abs_max / 127.0).astype(np.float32)

        first_row = self._num_rows
        with self.vec_path.open("ab") as f:
            f.write(q.tobytes(order="C"))
        with self.scl_path.open("ab") as f:
            f.write(scales.tobytes(order="C"))
        self._num_rows = first_row + len(vectors_f32)
        self._invalidate_mmap()
        return first_row

    def as_matrix_i8(self) -> np.ndarray:
        """(N, DIM) int8 mmap view of the quantized shard."""
        n = self._num_rows
        if n == 0:
            return np.empty((0, VECTOR_DIM), dtype=np.int8)
        if self._i8_mmap is None or self._i8_mmap.shape[0] != n:
            self._i8_mmap = None
            self._i8_mmap = np.memmap(self.vec_path, dtype=np.int8, mode="r", shape=(n, VECTOR_DIM))
        return self._i8_mmap

    def scales(self) -> np.ndarray:
        """(N,) float32 mmap view of per-row scales."""
        n = self._num_rows
        if n == 0:
            return np.empty(0, dtype=np.float32)
        if self._scl_mmap is None or self._scl_mmap.shape[0] != n:
            self._scl_mmap = None
            self._scl_mmap = np.memmap(self.scl_path, dtype=np.float32, mode="r", shape=(n,))
        return self._scl_mmap

    def _invalidate_mmap(self) -> None:
        self._i8_mmap = None
        self._scl_mmap = None

    def touch(self) -> None:
        n = self._num_rows
        if n == 0:
            return
        _ = self.as_matrix_i8().sum(dtype=np.int64)
        _ = self.scales().sum()

    def mlock(self) -> bool:
        if self._num_rows == 0:
            return True
        mat = self.as_matrix_i8()
        scl = self.scales()
        if mat.size == 0:
            return True
        return _mlock_array(mat) and _mlock_array(scl)

    def disk_bytes(self) -> int:
        total = 0
        for p in (self.vec_path, self.scl_path):
            try:
                total += p.stat().st_size
            except FileNotFoundError:
                pass
        return total

    def compute_scores(self, query_vector: np.ndarray, out: np.ndarray) -> None:
        """Dequantized cosine scores for this shard.

        We rely on numpy's auto-promotion for ``int8 @ f32``. There is no
        BLAS int8 path, so this runs 4-5x slower than the f32 shard — the
        cost we pay for 4x smaller disk + RAM.
        """
        n = self._num_rows
        if n == 0:
            return
        mat = self.as_matrix_i8()
        raw = mat @ query_vector  # auto-promote int8 → f32, (n,)
        # Apply per-row scale and write into caller's buffer.
        np.multiply(raw, self.scales(), out=out)


# ── ctypes mlock shared helper ────────────────────────────────────────


def _mlock_array(arr: np.ndarray) -> bool:
    """POSIX ``mlock`` over a numpy array's buffer. Soft-fails on ulimit."""
    try:
        import ctypes
        import ctypes.util

        libc_name = ctypes.util.find_library("c") or "libc.so.6"
        libc = ctypes.CDLL(libc_name, use_errno=True)
        libc.mlock.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        libc.mlock.restype = ctypes.c_int
        addr = arr.ctypes.data_as(ctypes.c_void_p)
        return libc.mlock(addr, ctypes.c_size_t(arr.nbytes)) == 0
    except Exception:
        return False


# ── the store ─────────────────────────────────────────────────────────


_FILTERABLE_COLS = frozenset({"id", "wing", "room", "source_file", "chunk_index"})


# Below this shard count, parallel dispatch overhead (thread pool submit +
# futures bookkeeping) exceeds the savings. Picked empirically — each
# submit is ~50-100µs on ThreadPoolExecutor, and typical per-shard compute
# at small scale is ~30-80µs, so we need at least a handful of shards
# before the parallel version nets out ahead.
_PARALLEL_MIN_SHARDS = 4


class _NoopContextManager:
    """Fallback when threadpoolctl isn't available. Zero overhead."""

    __slots__ = ()

    def __enter__(self) -> "_NoopContextManager":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


_NOOP_CM_INSTANCE = _NoopContextManager()


def _noop_cm() -> _NoopContextManager:
    return _NOOP_CM_INSTANCE


class PalaceStore:
    """Sharded-by-wing vector store with SQLite metadata.

    Not thread-safe for concurrent writers; a single internal lock serializes
    writes so a caller can safely share one instance across threads.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        dtype: str = "float32",
        parallel_query: bool = False,
        max_workers: int | None = None,
        blas_threads: int | None = 1,
    ):
        if dtype not in ("float32", "int8"):
            raise ValueError(f"dtype must be 'float32' or 'int8', not {dtype!r}")
        self.root = Path(path)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "vectors").mkdir(exist_ok=True)
        self._db_path = self.root / "meta.sqlite"
        self._dtype = dtype
        self._lock = threading.Lock()
        self._conn = self._open_connection()
        self._init_schema()
        self._shards: dict[str, "VectorShard | VectorShardI8"] = {}
        # Per-wing bool array: mask[i]=True if shard row i is referenced by a
        # live drawer. Orphaned rows (upsert-replaced, or delete()'d) get
        # masked to False so the query path can exclude them *before*
        # argpartition, which is both faster and correct regardless of how
        # many orphans pile up between compactions.
        self._live_masks: dict[str, np.ndarray] = {}
        # Per-wing int32 array: shard_room_ids[i] is the room-id assigned to
        # shard row i. Room is a first-class primary filter in the palace
        # hierarchy (not arbitrary metadata), so we index it structurally:
        # a room-filtered query masks non-matching rows via a single-int
        # numpy comparison. Previously this was a ``<U128`` unicode array;
        # profiling showed string comparison was 100-150µs/query at 100k
        # rows, which dropped to ~2µs with int32 equality.
        self._shard_room_ids: dict[str, np.ndarray] = {}
        # Persisted room name <-> id map, backed by the room_ids sqlite
        # table. Loaded once on open; extended on ingest via
        # ``_get_or_create_room_id``. The ids are per-store, stable across
        # reopens, and never recycled.
        self._room_name_to_id: dict[str, int] = {}
        self._room_id_to_name: dict[int, str] = {}
        # BLAS thread scoping: set to 1 for the life of the store because
        # OpenBLAS's per-sgemv thread spawn/sync overhead dominates compute
        # at our typical shard sizes (~4000 rows × 384 dims). Empirically,
        # at 100k drawers / 25 wings, running each sgemv on a single BLAS
        # thread is ~3.4x faster than letting OpenBLAS use all cores.
        #
        # We enter the threadpoolctl limiter ONCE at construction (not
        # per-query) because threadpool_limits has ~20 µs context manager
        # enter/exit overhead — large relative to small-scale query time.
        # Restored on close(). Users with unusual workloads (very large
        # wings where BLAS multi-threading actually helps) can disable by
        # passing blas_threads=None; embedded users who want to control
        # BLAS thread count at a higher level should also pass None.
        self._blas_threads = blas_threads
        self._blas_limiter: Any = None
        self._install_blas_limit()
        # Optional shard-level parallelism for unfiltered queries. numpy's
        # BLAS matmul releases the GIL, so a ThreadPoolExecutor can fan
        # out shard scoring across cores. On top of the blas_threads=1
        # win, this adds another ~2x at 100k+ for unfiltered queries by
        # running multiple shards' sgemv calls in parallel on separate
        # cores (BLAS-1-per-thread avoids nested-parallelism contention).
        self._parallel_query = parallel_query
        self._max_workers = max_workers
        self._executor: Any = None  # lazy ThreadPoolExecutor
        self._threadpool_limits: Any = None  # lazy threadpoolctl import
        self._threadpool_warned = False  # one-shot missing-threadpoolctl warning
        self._load_shards()
        self._load_room_id_map()
        self._rebuild_shard_indexes()

    # ── lifecycle ─────────────────────────────────────────────────────

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._db_path,
            isolation_level=None,  # autocommit; we manage transactions explicitly
            check_same_thread=False,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-65536")  # 64 MiB page cache
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS drawers (
                id           TEXT PRIMARY KEY,
                wing         TEXT NOT NULL,
                room         TEXT NOT NULL,
                source_file  TEXT,
                chunk_index  INTEGER,
                shard_row    INTEGER NOT NULL,
                text         TEXT NOT NULL,
                extra_json   TEXT,
                deleted      INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_drawers_wing_room
                ON drawers(wing, room) WHERE deleted = 0;
            CREATE INDEX IF NOT EXISTS idx_drawers_source
                ON drawers(source_file) WHERE deleted = 0;
            CREATE INDEX IF NOT EXISTS idx_drawers_shardrow
                ON drawers(wing, shard_row);

            -- Room name → stable integer id map for the int-equality
            -- room filter on the query hot path. Ids start at 1 so 0 can
            -- be used as a sentinel "unknown room" in the shard_room_ids
            -- arrays without colliding with a real room.
            CREATE TABLE IF NOT EXISTS room_ids (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                name  TEXT UNIQUE NOT NULL
            );
            """
        )

    def _load_shards(self) -> None:
        """Discover existing shard files so queries work without a prior upsert."""
        vec_dir = self.root / "vectors"
        if self._dtype == "float32":
            for vec_path in vec_dir.glob("*.vec"):
                wing = vec_path.stem
                self._shards[wing] = VectorShard(vec_path)
        else:
            for vec_path in vec_dir.glob("*.i8"):
                wing = vec_path.stem
                scl_path = vec_dir / f"{wing}.scl"
                self._shards[wing] = VectorShardI8(vec_path, scl_path)

    def _load_room_id_map(self) -> None:
        """Populate the room name <-> id dicts from the ``room_ids`` table.

        Also backfills ids for any rooms found in the drawers table that
        don't yet have one (the migration path from the old string-based
        label format — opens an existing store and lazily assigns ids).
        """
        self._room_name_to_id.clear()
        self._room_id_to_name.clear()
        for r in self._conn.execute("SELECT id, name FROM room_ids").fetchall():
            self._room_name_to_id[r["name"]] = r["id"]
            self._room_id_to_name[r["id"]] = r["name"]

        # Backfill any rooms that exist in drawers but aren't yet in
        # room_ids. This is the only time the room_ids table gets written
        # outside of ingest, and it only fires once per opened store if
        # migrating from the pre-int-id format.
        missing = self._conn.execute(
            "SELECT DISTINCT room FROM drawers "
            "WHERE deleted = 0 AND room NOT IN (SELECT name FROM room_ids)"
        ).fetchall()
        for r in missing:
            name = r["room"] or ""
            if name not in self._room_name_to_id:
                self._get_or_create_room_id(name)

    def _get_or_create_room_id(self, name: str) -> int:
        """Return the stable int id for a room name, allocating on first use.

        The lookup is an O(1) dict hit for rooms we've seen before. For
        new rooms we do one sqlite INSERT and cache both directions.
        Callers must hold the write lock when a new id may be created.
        """
        existing = self._room_name_to_id.get(name)
        if existing is not None:
            return existing
        cur = self._conn.execute("INSERT INTO room_ids (name) VALUES (?)", (name,))
        room_id = int(cur.lastrowid)
        self._room_name_to_id[name] = room_id
        self._room_id_to_name[room_id] = name
        return room_id

    def _rebuild_shard_indexes(self) -> None:
        """Reconstruct live masks and shard room-id arrays from SQLite.

        A shard row is "live" iff there exists a drawer row pointing to it
        with deleted=0. Orphaned rows (never referenced, tombstoned, or
        replaced) are dead. The shard_room_ids array holds the int room-id
        for every row the shard file contains; dead rows may hold stale
        ids but the live mask filters them out before any comparison.
        """
        self._live_masks.clear()
        self._shard_room_ids.clear()
        for wing, shard in self._shards.items():
            n = shard.num_rows()
            self._live_masks[wing] = np.zeros(n, dtype=bool)
            # 0 is the sentinel "unknown room" id — AUTOINCREMENT starts at 1
            self._shard_room_ids[wing] = np.zeros(n, dtype=np.int32)
        rows = self._conn.execute(
            "SELECT wing, shard_row, room FROM drawers WHERE deleted = 0"
        ).fetchall()
        for r in rows:
            wing = r["wing"]
            idx = r["shard_row"]
            mask = self._live_masks.get(wing)
            room_ids = self._shard_room_ids.get(wing)
            if mask is None or room_ids is None:
                continue
            if 0 <= idx < len(mask):
                mask[idx] = True
                room_ids[idx] = self._get_or_create_room_id(r["room"] or "")

    def _extend_shard_indexes(self, wing: str, rooms: list[str]) -> None:
        """Grow live mask + shard room-id array for freshly appended rows.

        Caller must hold the write lock (``_get_or_create_room_id`` may
        insert into sqlite).
        """
        n_new = len(rooms)
        if n_new <= 0:
            return
        mask = self._live_masks.get(wing)
        if mask is None:
            self._live_masks[wing] = np.ones(n_new, dtype=bool)
        else:
            new_mask = np.empty(len(mask) + n_new, dtype=bool)
            new_mask[: len(mask)] = mask
            new_mask[len(mask) :] = True
            self._live_masks[wing] = new_mask

        new_ids = np.fromiter(
            (self._get_or_create_room_id(r) for r in rooms),
            dtype=np.int32,
            count=n_new,
        )
        existing_ids = self._shard_room_ids.get(wing)
        if existing_ids is None:
            self._shard_room_ids[wing] = new_ids
        else:
            self._shard_room_ids[wing] = np.concatenate([existing_ids, new_ids])

    def _orphan_rows(self, rows: Iterable[tuple[str, int]]) -> None:
        """Flip (wing, shard_row) pairs to dead in the live masks.

        The shard_room_ids entries are left in place; the live mask is
        what the query path consults to filter out dead rows, so stale
        ids are harmless.
        """
        for wing, row in rows:
            mask = self._live_masks.get(wing)
            if mask is not None and 0 <= row < len(mask):
                mask[row] = False

    def close(self) -> None:
        self._shards.clear()
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass
            self._executor = None
        # Restore BLAS thread count to whatever it was before the store
        # installed its limit. Safe to call on a None limiter (the
        # no-threadpoolctl path).
        if self._blas_limiter is not None:
            try:
                self._blas_limiter.__exit__(None, None, None)
            except Exception:
                pass
            self._blas_limiter = None
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> "PalaceStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── shard lookup ──────────────────────────────────────────────────

    def _shard_for(self, wing: str) -> "VectorShard | VectorShardI8":
        shard = self._shards.get(wing)
        if shard is None:
            name = _safe_name(wing)
            if self._dtype == "float32":
                shard = VectorShard(self.root / "vectors" / f"{name}.vec")
            else:
                shard = VectorShardI8(
                    self.root / "vectors" / f"{name}.i8",
                    self.root / "vectors" / f"{name}.scl",
                )
            self._shards[wing] = shard
        return shard

    def _active_wings(self) -> list[str]:
        rows = self._conn.execute("SELECT DISTINCT wing FROM drawers WHERE deleted = 0").fetchall()
        return [r["wing"] for r in rows]

    # ── write path ────────────────────────────────────────────────────

    def upsert(
        self,
        ids: list[str],
        vectors: np.ndarray,
        metadatas: list[dict[str, Any]],
        texts: list[str],
    ) -> None:
        """Insert or replace drawers in a single transaction.

        Vectors are appended to their wing's shard in bulk (one append per
        wing), and the metadata rows are inserted via `executemany`.
        """
        n = len(ids)
        if n == 0:
            return
        if not (len(metadatas) == len(texts) == vectors.shape[0] == n):
            raise ValueError("ids/vectors/metadatas/texts length mismatch")
        if vectors.dtype != VECTOR_DTYPE:
            raise TypeError(f"vectors must be {VECTOR_DTYPE}")
        if vectors.ndim != 2 or vectors.shape[1] != VECTOR_DIM:
            raise ValueError(f"vectors must be (N, {VECTOR_DIM})")

        # Group row indices by wing so each shard gets one append() call.
        by_wing: dict[str, list[int]] = {}
        for i, meta in enumerate(metadatas):
            wing = meta.get("wing")
            if not wing:
                raise ValueError(f"metadata[{i}] missing 'wing'")
            by_wing.setdefault(wing, []).append(i)

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                # Upsert semantics: find any existing live rows with these
                # ids, mark their shard rows dead in the live masks, then
                # tombstone them in SQL. The vector data stays on disk
                # (append-only) but never matches a future query.
                # Batched to stay well under SQLITE_MAX_VARIABLE_NUMBER
                # (default 32766); individual mempalace upserts are tiny
                # but bulk-ingest tools can easily exceed the limit.
                _STALE_CHUNK = 500
                stale_rows: list[sqlite3.Row] = []
                for start in range(0, n, _STALE_CHUNK):
                    chunk_ids = ids[start : start + _STALE_CHUNK]
                    placeholders = ",".join("?" * len(chunk_ids))
                    stale_rows.extend(
                        self._conn.execute(
                            f"SELECT wing, shard_row FROM drawers "
                            f"WHERE id IN ({placeholders}) AND deleted = 0",
                            chunk_ids,
                        ).fetchall()
                    )
                self._orphan_rows((r["wing"], r["shard_row"]) for r in stale_rows)
                self._conn.executemany(
                    "UPDATE drawers SET deleted = 1 WHERE id = ?",
                    [(i,) for i in ids],
                )

                insert_rows: list[tuple] = []
                for wing, indices in by_wing.items():
                    shard = self._shard_for(wing)
                    wing_vecs = np.ascontiguousarray(vectors[indices])
                    first_row = shard.append(wing_vecs)
                    rooms_for_block = [metadatas[orig_i].get("room", "") for orig_i in indices]
                    self._extend_shard_indexes(wing, rooms_for_block)

                    for local_i, orig_i in enumerate(indices):
                        meta = metadatas[orig_i]
                        extras = {
                            k: v
                            for k, v in meta.items()
                            if k not in ("wing", "room", "source_file", "chunk_index")
                        }
                        insert_rows.append(
                            (
                                ids[orig_i],
                                wing,
                                meta.get("room", ""),
                                meta.get("source_file"),
                                meta.get("chunk_index"),
                                first_row + local_i,
                                texts[orig_i],
                                json.dumps(extras, separators=(",", ":")) if extras else None,
                            )
                        )

                self._conn.executemany(
                    """
                    INSERT OR REPLACE INTO drawers
                        (id, wing, room, source_file, chunk_index,
                         shard_row, text, extra_json, deleted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    insert_rows,
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    # ── query path ────────────────────────────────────────────────────

    def query(
        self,
        query_vector: np.ndarray,
        k: int,
        where: dict[str, Any] | None = None,
    ) -> list[QueryResult]:
        """Top-k cosine-similarity search. Exact; no ANN approximation.

        `where` may contain `wing` and/or `room`. Query vector must be
        L2-normalized (same as stored vectors).
        """
        if query_vector.dtype != VECTOR_DTYPE:
            query_vector = query_vector.astype(VECTOR_DTYPE, copy=False)
        if query_vector.shape != (VECTOR_DIM,):
            raise ValueError(f"query_vector must be shape ({VECTOR_DIM},)")
        if k <= 0:
            return []

        where = where or {}
        wing_filter = where.get("wing")
        room_filter = where.get("room")

        if wing_filter is not None:
            wings = [wing_filter] if wing_filter in self._shards else []
        else:
            wings = list(self._shards.keys())

        if not wings:
            return []

        # Translate room filter string to its stable int id once. If the
        # room was never ingested, no row can match — short-circuit.
        room_filter_id: int | None = None
        if room_filter is not None:
            room_filter_id = self._room_name_to_id.get(room_filter)
            if room_filter_id is None:
                return []

        # Dispatch shard scoring. The BLAS thread limit is already active
        # from store construction (see _install_blas_limit), so every
        # sgemv inside _score_shard runs single-threaded. That means:
        #   (a) per-shard sgemv avoids OpenBLAS's thread spawn overhead,
        #       the biggest single win at mempalace shard sizes (3-4×)
        #   (b) when parallel_query=True, our ThreadPoolExecutor can fan
        #       out shards across workers without nested parallelism
        #       (each BLAS call uses one thread, our pool owns the rest)
        candidates: list[tuple[float, str, int]] = []
        if self._parallel_query and len(wings) >= _PARALLEL_MIN_SHARDS:
            executor = self._get_executor()
            futures = [
                executor.submit(
                    self._score_shard,
                    wing,
                    query_vector,
                    room_filter_id,
                    k,
                )
                for wing in wings
            ]
            for fut in futures:
                candidates.extend(fut.result())
        else:
            for wing in wings:
                candidates.extend(self._score_shard(wing, query_vector, room_filter_id, k))

        if not candidates:
            return []

        candidates.sort(key=lambda t: -t[0])
        candidates = candidates[:k]

        # Single SQL round-trip to hydrate the candidate rows with text and
        # metadata. Room/live filtering has already been applied on the
        # in-memory mask side, so the SQL is a plain join.
        keys = [(w, r) for _, w, r in candidates]
        rows = self._lookup_candidates(keys)
        row_by_key = {(r["wing"], r["shard_row"]): r for r in rows}

        results: list[QueryResult] = []
        for score, wing, row in candidates:
            r = row_by_key.get((wing, row))
            if r is None:
                # Only possible if SQLite and the in-memory index disagree,
                # which would indicate a real bug — log it and move on.
                continue
            results.append(
                QueryResult(
                    id=r["id"],
                    score=score,
                    text=r["text"],
                    wing=r["wing"],
                    room=r["room"],
                    metadata=json.loads(r["extra_json"]) if r["extra_json"] else {},
                )
            )
        return results

    def _score_shard(
        self,
        wing: str,
        query_vector: np.ndarray,
        room_filter_id: int | None,
        k: int,
    ) -> list[tuple[float, str, int]]:
        """Compute the top-k candidates for a single shard.

        Thread-safe: allocates its own ``scores`` buffer and reads the
        live mask and room-id array as numpy views — no shared mutable
        state. The caller merges the returned lists after all shards
        have been scored.

        Returns a list of ``(score, wing, shard_row)`` tuples, already
        filtered and ordered. Length is at most ``k`` and may be zero.
        """
        shard = self._shards[wing]
        n_rows = shard.num_rows()
        if n_rows == 0:
            return []

        # Per-query allocation is cheaper than a shared cached buffer
        # under parallelism (no lock, no aliasing hazard). ~1-2µs and
        # doesn't register in the profile versus the BLAS compute.
        scores = np.empty(n_rows, dtype=VECTOR_DTYPE)
        shard.compute_scores(query_vector, scores)

        live = self._live_masks.get(wing)
        if live is None or len(live) < n_rows:
            # Defensive: shard grew without an index rebuild.
            alive = np.zeros(n_rows, dtype=bool)
            if live is not None:
                alive[: len(live)] = live
        else:
            alive = live[:n_rows]

        if room_filter_id is not None:
            room_ids = self._shard_room_ids.get(wing)
            if room_ids is None or len(room_ids) < n_rows:
                room_ok = np.zeros(n_rows, dtype=bool)
                if room_ids is not None:
                    room_ok[: len(room_ids)] = room_ids == room_filter_id
            else:
                # Integer equality over (n_rows,) int32 — this is the
                # single optimization that drops wing_room query time
                # from ~100-150µs (string comparison) to ~2-3µs.
                room_ok = room_ids[:n_rows] == room_filter_id
            alive = alive & room_ok

        np.putmask(scores, ~alive, np.float32(-np.inf))

        n_alive = int(np.count_nonzero(alive))
        if n_alive == 0:
            return []

        k_local = min(k, n_alive)
        if k_local < n_rows:
            part = np.argpartition(-scores, k_local - 1)[:k_local]
            order = part[np.argsort(-scores[part])]
        else:
            order = np.argsort(-scores)[:k_local]

        out: list[tuple[float, str, int]] = []
        for row in order:
            s = float(scores[row])
            if s == float("-inf"):
                continue
            out.append((s, wing, int(row)))
        return out

    def _get_executor(self):
        """Lazy-create the thread pool on first parallel-eligible query.

        Default ``max_workers`` is capped at 8 because shard-level matmul
        is memory-bandwidth bound, not compute-bound — beyond ~6 threads
        the memory controller saturates and more workers just add
        contention and scheduling overhead. An empirical sweep on a
        24-core machine showed a ~3× win at ``max_workers=6-8`` and
        regression to near-sequential at ``max_workers=24``. Callers
        with unusual hardware (small laptop, many-socket NUMA) can
        still override via the constructor.
        """
        if self._executor is None:
            from concurrent.futures import ThreadPoolExecutor
            import os

            workers = self._max_workers
            if workers is None:
                workers = min(8, max(2, (os.cpu_count() or 2)))
            self._executor = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="palace_store_query",
            )
        return self._executor

    def _install_blas_limit(self) -> None:
        """Enter a threadpoolctl BLAS limit eagerly, once per store.

        threadpool_limits() is both a constructor AND a context manager
        that takes effect on __enter__ — called directly, it applies the
        limit immediately and stores the previous value on the object
        itself. We hold the reference in self._blas_limiter so the
        limit stays active until close() calls __exit__ to restore.

        If threadpoolctl isn't installed, we emit a one-shot warning
        and continue with default BLAS threading (measurably slower on
        multi-core machines, but functional).
        """
        if self._blas_threads is None:
            return
        try:
            from threadpoolctl import threadpool_limits
        except ImportError:
            if not self._threadpool_warned:
                import warnings

                warnings.warn(
                    "palace_store: threadpoolctl is not installed. "
                    "Query latency on multi-core machines will be up "
                    "to 3-4x slower because OpenBLAS runs each sgemv "
                    "on all cores and its thread-spawn overhead "
                    "dominates compute at typical shard sizes. "
                    "Install with: pip install 'mempalace[palace-parallel]' "
                    "or pip install threadpoolctl. Pass "
                    "blas_threads=None to silence this warning.",
                    RuntimeWarning,
                    stacklevel=3,
                )
                self._threadpool_warned = True
            return
        # threadpool_limits() applies the limit on construction; the
        # returned object is a CM whose __exit__ restores the prior
        # state. Keeping it alive keeps the limit active.
        self._blas_limiter = threadpool_limits(limits=self._blas_threads, user_api="blas")

    def _lookup_candidates(self, keys: list[tuple[str, int]]) -> list[sqlite3.Row]:
        if not keys:
            return []
        values_sql = ",".join("(?, ?)" for _ in keys)
        params: list[Any] = []
        for wing, row in keys:
            params.append(wing)
            params.append(row)
        sql = (
            f"WITH keys(k_wing, k_row) AS (VALUES {values_sql}) "
            "SELECT d.id, d.wing, d.room, d.shard_row, d.text, d.extra_json "
            "FROM drawers d "
            "JOIN keys ON d.wing = keys.k_wing AND d.shard_row = keys.k_row "
            "WHERE d.deleted = 0"
        )
        return self._conn.execute(sql, params).fetchall()

    # ── metadata ops ──────────────────────────────────────────────────

    def get(
        self,
        where: dict[str, Any] | None = None,
        *,
        ids: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """Fetch drawers by metadata filter and/or id list.

        Three modes:
          - ``ids=[...]`` — direct id lookup, order preserved per SQLite's
            ``IN`` expansion (used for Chroma's ``get(ids=...)``)
          - ``where={...}`` — metadata filter scan
          - Both None — full scan with limit/offset (used for paginated
            exports in mempalace's status/layers paths)
        """
        if ids is not None:
            if len(ids) == 0:
                return []
            placeholders = ",".join("?" * len(ids))
            sql = (
                "SELECT id, wing, room, source_file, chunk_index, text, extra_json "
                f"FROM drawers WHERE deleted = 0 AND id IN ({placeholders})"
            )
            params: list[Any] = list(ids)
        elif where:
            sql, params = self._build_where_sql(
                "SELECT id, wing, room, source_file, chunk_index, text, extra_json " "FROM drawers",
                where,
            )
        else:
            sql = (
                "SELECT id, wing, room, source_file, chunk_index, text, extra_json "
                "FROM drawers WHERE deleted = 0"
            )
            params = []

        sql += " ORDER BY id"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([int(limit), int(offset)])

        rows = self._conn.execute(sql, params).fetchall()
        return [
            {
                "id": r["id"],
                "wing": r["wing"],
                "room": r["room"],
                "source_file": r["source_file"],
                "chunk_index": r["chunk_index"],
                "text": r["text"],
                "metadata": json.loads(r["extra_json"]) if r["extra_json"] else {},
            }
            for r in rows
        ]

    def delete(
        self,
        where: dict[str, Any] | None = None,
        *,
        ids: list[str] | None = None,
    ) -> int:
        """Soft-delete by metadata filter and/or id list.

        At least one of ``where`` or ``ids`` must be provided.
        Returns the count of rows affected.
        """
        if ids is None and not where:
            raise ValueError("delete() requires where= or ids=")

        if ids is not None:
            if len(ids) == 0:
                return 0
            placeholders = ",".join("?" * len(ids))
            select_sql = (
                "SELECT wing, shard_row FROM drawers "
                f"WHERE deleted = 0 AND id IN ({placeholders})"
            )
            update_sql = (
                "UPDATE drawers SET deleted = 1 " f"WHERE deleted = 0 AND id IN ({placeholders})"
            )
            params: list[Any] = list(ids)
        else:
            select_sql, params = self._build_where_sql("SELECT wing, shard_row FROM drawers", where)
            update_sql, _ = self._build_where_sql("UPDATE drawers SET deleted = 1", where)

        with self._lock:
            affected = self._conn.execute(select_sql, params).fetchall()
            if not affected:
                return 0
            self._orphan_rows((r["wing"], r["shard_row"]) for r in affected)
            cur = self._conn.execute(update_sql, params)
            return cur.rowcount

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM drawers WHERE deleted = 0").fetchone()[0]

    def truncate(self) -> None:
        """Wipe every drawer and every shard file in one shot.

        Used by ``EphemeralClient`` (in the compat shim) to reset the store
        between benchmark questions. Leaves the sqlite file + schema in
        place; only the rows and vector files are deleted. The store
        remains usable immediately.
        """
        with self._lock:
            self._conn.execute("DELETE FROM drawers")
            for shard in self._shards.values():
                if isinstance(shard, VectorShardI8):
                    for p in (shard.vec_path, shard.scl_path):
                        try:
                            p.unlink()
                        except FileNotFoundError:
                            pass
                        p.touch()
                    shard._num_rows = 0
                    shard._invalidate_mmap()
                else:
                    try:
                        shard.path.unlink()
                    except FileNotFoundError:
                        pass
                    shard.path.touch()
                    shard._num_rows = 0
                    shard._invalidate_mmap()
            self._shards.clear()
            self._live_masks.clear()
            self._shard_room_ids.clear()
            # Note: the room_ids table is intentionally NOT wiped — ids
            # stay stable across truncations so ephemeral-client cycles
            # don't explode the id space on long benchmark runs.

    def count_by_wing(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT wing, COUNT(*) AS n FROM drawers WHERE deleted = 0 GROUP BY wing"
        ).fetchall()
        return {r["wing"]: r["n"] for r in rows}

    def warm_pages(self, *, mlock: bool = False) -> dict[str, bool]:
        """Warm every shard's mmap'd pages into the OS page cache.

        If ``mlock=True``, also pin them with POSIX ``mlock()`` so they
        cannot be evicted under memory pressure. Returns a dict
        ``{wing: mlock_ok}`` — all shards are warmed unconditionally; the
        ``mlock`` column is only meaningful if the flag was True.
        """
        result: dict[str, bool] = {}
        for wing, shard in self._shards.items():
            if mlock:
                result[wing] = shard.mlock()
            else:
                shard.touch()
                result[wing] = True
        return result

    def disk_bytes(self) -> dict[str, int]:
        """Return a breakdown of on-disk bytes for cost analysis."""
        vec_total = sum(shard.disk_bytes() for shard in self._shards.values())
        meta_total = 0
        for name in ("meta.sqlite", "meta.sqlite-wal", "meta.sqlite-shm"):
            p = self.root / name
            if p.exists():
                meta_total += p.stat().st_size
        return {"vectors": vec_total, "meta": meta_total, "total": vec_total + meta_total}

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _build_where_sql(prefix: str, where: dict[str, Any]) -> tuple[str, list[Any]]:
        clauses = ["deleted = 0"]
        params: list[Any] = []
        for k, v in where.items():
            if k not in _FILTERABLE_COLS:
                raise ValueError(f"cannot filter on {k!r}; allowed: {sorted(_FILTERABLE_COLS)}")
            clauses.append(f"{k} = ?")
            params.append(v)
        return f"{prefix} WHERE {' AND '.join(clauses)}", params


# ── utilities ─────────────────────────────────────────────────────────


def _safe_name(wing: str) -> str:
    """Sanitize a wing name for use as a filename component."""
    if not wing:
        raise ValueError("wing name cannot be empty")
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in wing)


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """Return a C-contiguous float32 copy with each row L2-normalized.

    Rows with zero norm are left as zero (they'll score 0 against every query).
    """
    v = np.ascontiguousarray(vectors, dtype=VECTOR_DTYPE)
    if v.ndim == 1:
        norm = float(np.linalg.norm(v))
        return v / norm if norm > 0 else v
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return v / norms


__all__ = [
    "VECTOR_DIM",
    "VECTOR_DTYPE",
    "BYTES_PER_VECTOR",
    "QueryResult",
    "PalaceStore",
    "VectorShard",
    "l2_normalize",
]

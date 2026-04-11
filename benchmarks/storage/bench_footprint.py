"""Footprint benchmark: on-disk size breakdown + cold-start time.

Cold-start is the time from "new Python process spawns" to "first query
returns", measured externally via subprocess. This is the number that
matters for mempalace's MCP server, which re-instantiates the client on
every call.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .dataset import BenchDataset
from .interface import StoreAdapter


@dataclass
class FootprintResult:
    adapter: str
    n_drawers: int
    disk_bytes: int
    disk_bytes_per_drawer: float
    cold_start_ms: float
    cold_start_query_ms: float


_COLD_START_SCRIPT = r"""
import json
import sys
import time

t0 = time.perf_counter_ns()
adapter_name, store_path, q_path = sys.argv[1], sys.argv[2], sys.argv[3]

import numpy as np
q = np.load(q_path)

if adapter_name == "palace":
    from benchmarks.storage.adapters.palace import PalaceAdapter
    a = PalaceAdapter(store_path)
elif adapter_name == "palace_par":
    from benchmarks.storage.adapters.palace import PalaceAdapter
    a = PalaceAdapter(store_path, parallel_query=True)
elif adapter_name == "palace_i8":
    from benchmarks.storage.adapters.palace_i8 import PalaceI8Adapter
    a = PalaceI8Adapter(store_path)
elif adapter_name == "chroma":
    from benchmarks.storage.adapters.chroma import ChromaAdapter
    a = ChromaAdapter(store_path)
else:
    raise SystemExit(f"unknown adapter: {adapter_name}")

t1 = time.perf_counter_ns()
a.query(q, k=10, where=None)
t2 = time.perf_counter_ns()

print(json.dumps({
    "open_ns": t1 - t0,
    "first_query_ns": t2 - t1,
}))
"""


def run(
    adapter: StoreAdapter,
    store_path: Path,
    dataset: BenchDataset,
) -> FootprintResult:
    disk = adapter.disk_bytes()
    per_drawer = disk / dataset.n if dataset.n else 0.0

    # Write the probe query vector to a temp file so the subprocess can
    # load it without regenerating the whole dataset.
    import numpy as np

    q_path = store_path.parent / f"{adapter.name}_cold_q.npy"
    np.save(q_path, dataset.query_vectors[0])

    cmd = [
        sys.executable,
        "-c",
        _COLD_START_SCRIPT,
        adapter.name,
        str(store_path),
        str(q_path),
    ]

    # Warm up the import graph once so the measured run doesn't pay for
    # linker / bytecode cache warmup.
    subprocess.run(cmd, capture_output=True, check=False)

    # Real measurement
    t0 = time.perf_counter_ns()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    wall_ns = time.perf_counter_ns() - t0
    if proc.returncode != 0:
        raise RuntimeError(
            f"cold-start probe failed ({adapter.name}):\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    try:
        parsed: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        raise RuntimeError(
            f"cold-start probe output unparseable ({adapter.name}):\n{proc.stdout}"
        )

    open_ns = parsed["open_ns"]
    first_query_ns = parsed["first_query_ns"]

    return FootprintResult(
        adapter=adapter.name,
        n_drawers=dataset.n,
        disk_bytes=disk,
        disk_bytes_per_drawer=round(per_drawer, 2),
        # Include subprocess wall-clock as the honest "cold start" number —
        # it captures Python import cost, which is the dominant factor on
        # a fresh interpreter and the thing mempalace's MCP server pays on
        # every call.
        cold_start_ms=round(wall_ns / 1e6, 2),
        cold_start_query_ms=round((open_ns + first_query_ns) / 1e6, 2),
    )

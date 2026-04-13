"""Shared Chroma runtime helpers for local MemPalace workloads.

These helpers intentionally solve a narrow problem: local Chroma 0.6.x runs are
currently noisy because its PostHog telemetry hook is incompatible with the
installed `posthog` package version in this environment. Every `create/add/query`
call emits a warning even when we ask Chroma to disable anonymized telemetry.

MemPalace benchmarks and local tooling care about deterministic retrieval and
clean timing output, not telemetry. We therefore hard-disable the product
telemetry capture hook before constructing clients. This does not change vector
math, collection metadata, or retrieval semantics.
"""

from __future__ import annotations

import chromadb
import chromadb.telemetry.product.posthog as chroma_posthog
from chromadb.config import Settings


def _noop_capture(*_args, **_kwargs) -> None:
    """Swallow Chroma product telemetry calls in local/offline runs."""

    return None


def make_settings() -> Settings:
    """Return local-safe Chroma settings for MemPalace-managed clients.

    We leave HNSW knobs at Chroma's defaults on purpose. Chroma already derives
    `hnsw:num_threads` from the host CPU count, and benchmark corpora like
    LongMemEval stay below the default in-memory `hnsw:batch_size`, so forcing
    extra tuning here would just be cargo cult.
    """

    chroma_posthog.posthog.disabled = True
    chroma_posthog.posthog.capture = _noop_capture
    return Settings(anonymized_telemetry=False)


def make_ephemeral_client():
    """Create an in-memory Chroma client with MemPalace's local-safe settings."""

    return chromadb.EphemeralClient(settings=make_settings())


def make_persistent_client(path: str):
    """Create a persistent Chroma client with MemPalace's local-safe settings."""

    return chromadb.PersistentClient(path=path, settings=make_settings())

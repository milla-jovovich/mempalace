"""Standalone benchmark harness for storage layer candidates.

This harness does not depend on mempalace internals. It measures pure
storage performance — ingest throughput, query latency, memory usage,
disk footprint — by exercising a `StoreAdapter` interface that any
candidate (PalaceStore, ChromaDB, ...) can implement.

See benchmarks/storage/README.md for usage.
"""

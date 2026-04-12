"""
sync_server.py — HTTP sync server for multi-device MemPalace replication.

Run with:  mempalace serve --host 0.0.0.0 --port 7433

Endpoints:
    GET  /health       — server health check
    GET  /sync/status  — version vector + record count
    POST /sync/push    — receive records from a client
    POST /sync/pull    — send records the client hasn't seen
"""

import logging
import os

from .config import MempalaceConfig
from .sync import SyncEngine, ChangeSet, SyncRecord
from .sync_meta import NodeIdentity

logger = logging.getLogger("mempalace.sync_server")

# ── Lazy globals (initialised on first request) ───────────────────────────────

_engine = None
_config = None


def _get_engine() -> SyncEngine:
    global _engine, _config
    if _engine is None:
        _config = MempalaceConfig()
        palace_path = _config.palace_path

        from .palace import get_collection
        from .backends import detect_backend

        if detect_backend(palace_path) == "chroma":
            raise RuntimeError(
                f"Palace at {palace_path} uses ChromaDB. "
                "Sync requires LanceDB. Run: mempalace migrate"
            )

        col = get_collection(palace_path, backend="lance")

        identity = NodeIdentity()
        vv_path = os.path.join(palace_path, "version_vector.json")

        _engine = SyncEngine(col, identity=identity, vv_path=vv_path)
        logger.info(
            "Sync engine initialised — node=%s palace=%s",
            identity.node_id,
            palace_path,
        )
    return _engine


# ── FastAPI app ───────────────────────────────────────────────────────────────


def create_app():
    """Create the FastAPI application."""
    try:
        from fastapi import FastAPI, Request
    except ImportError:
        raise ImportError(
            "fastapi is required for the sync server. Install with: pip install 'mempalace[server]'"
        )

    app = FastAPI(title="MemPalace Sync Server", version="1.0.0")

    # ── Endpoints ─────────────────────────────────────────────────────

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "mempalace-sync"}

    @app.get("/sync/status")
    def sync_status():
        engine = _get_engine()
        col = engine._col
        return {
            "node_id": engine._identity.node_id,
            "version_vector": engine.version_vector,
            "total_drawers": col.count(),
        }

    @app.post("/sync/push")
    async def sync_push(request: Request):  # noqa: F811
        body = await request.json()
        engine = _get_engine()
        cs = ChangeSet(
            source_node=body.get("source_node", ""),
            records=[SyncRecord.from_dict(r) for r in body.get("records", [])],
        )
        result = engine.apply_changes(cs)
        return {
            "accepted": result.accepted,
            "rejected_conflicts": result.rejected_conflicts,
            "errors": result.errors,
        }

    @app.post("/sync/pull")
    async def sync_pull(request: Request):  # noqa: F811
        body = await request.json()
        engine = _get_engine()
        cs = engine.get_changes_since(body.get("version_vector", {}))
        return {
            "source_node": cs.source_node,
            "records": [r.to_dict() for r in cs.records],
        }

    return app

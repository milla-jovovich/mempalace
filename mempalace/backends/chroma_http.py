"""ChromaDB HTTP-mode backend (RFC 001 backend implementation).

Used when MemPalace pods are deployed against an external ChromaDB server
(``chromadb run`` or a managed ChromaDB) instead of an embedded
``PersistentClient``. Selected when ``MEMPALACE_BACKEND=chroma_http`` or
when ``MEMPALACE_CHROMA_URL``/``MEMPALACE_CHROMA_HOST`` is set.

Configuration env vars (all optional; the constructor also accepts each
as a keyword for tests):

* ``MEMPALACE_CHROMA_URL`` — full URL e.g. ``https://chroma.svc:8000`` or
  ``http://localhost:8000``. Preferred form. Overrides host/port/ssl.
* ``MEMPALACE_CHROMA_HOST`` — hostname. Falls back to ``localhost``.
* ``MEMPALACE_CHROMA_PORT`` — port. Falls back to ``8000``.
* ``MEMPALACE_CHROMA_SSL`` — ``true``/``false``. Default ``false``.
* ``MEMPALACE_CHROMA_AUTH_TOKEN`` — bearer token sent in ``Authorization``.
* ``MEMPALACE_CHROMA_AUTH_HEADER`` — header name (default ``Authorization``)
  used to ship the token. Useful for proxies that prefer ``X-Api-Key``.
* ``MEMPALACE_CHROMA_TENANT`` — chroma tenant for multi-tenant servers.
* ``MEMPALACE_CHROMA_DATABASE`` — chroma database (logical namespace).

Why we need this on top of the local :class:`ChromaBackend`:

* Drawer storage moves from a per-pod PVC to a shared chromadb server,
  which is the prerequisite for stateless mempalace pods.
* Pods don't touch ChromaDB's internal sqlite, HNSW segment files, or
  ``index_metadata.pickle`` — those operations (segment quarantine,
  HNSW rebuild from sqlite, ``max_seq_id`` repair) are server-side
  responsibilities once we go remote.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import chromadb

from .base import BaseBackend, HealthStatus, PalaceNotFoundError, PalaceRef
from .chroma import ChromaCollection, _pin_hnsw_threads, _HNSW_BLOAT_GUARD

logger = logging.getLogger(__name__)


_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "y"})


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _resolve_connection() -> dict:
    """Read chromadb HTTP connection params from env vars.

    Returns a dict of keys consumed by :class:`HttpChromaBackend`. Values
    fall back to chromadb defaults: localhost:8000 over plain HTTP.
    """
    url = os.environ.get("MEMPALACE_CHROMA_URL", "").strip() or None
    host = os.environ.get("MEMPALACE_CHROMA_HOST", "").strip() or None
    port = os.environ.get("MEMPALACE_CHROMA_PORT", "").strip() or None
    ssl = _env_bool("MEMPALACE_CHROMA_SSL", default=False)
    token = os.environ.get("MEMPALACE_CHROMA_AUTH_TOKEN", "").strip() or None
    auth_header = (
        os.environ.get("MEMPALACE_CHROMA_AUTH_HEADER", "Authorization").strip()
        or "Authorization"
    )
    tenant = os.environ.get("MEMPALACE_CHROMA_TENANT", "").strip() or None
    database = os.environ.get("MEMPALACE_CHROMA_DATABASE", "").strip() or None
    return {
        "url": url,
        "host": host,
        "port": int(port) if port else None,
        "ssl": ssl,
        "token": token,
        "auth_header": auth_header,
        "tenant": tenant,
        "database": database,
    }


def _split_url(url: str) -> tuple[str, int, bool]:
    """Parse ``http(s)://host:port`` into ``(host, port, ssl)``."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"invalid MEMPALACE_CHROMA_URL: {url!r}")
    ssl = parsed.scheme.lower() == "https"
    host = parsed.hostname
    port = parsed.port or (443 if ssl else 8000)
    return host, port, ssl


def _detect_env_configured() -> bool:
    """Return True if any HTTP-mode env var is set."""
    return any(
        os.environ.get(name, "").strip()
        for name in (
            "MEMPALACE_CHROMA_URL",
            "MEMPALACE_CHROMA_HOST",
            "MEMPALACE_CHROMA_PORT",
        )
    )


class HttpChromaBackend(BaseBackend):
    """ChromaDB-over-HTTP backend.

    Stateless from the client's perspective — owns a single cached
    ``HttpClient`` per process. Different palaces share the same chromadb
    server but use distinct ``collection_name`` prefixes derived from the
    ``PalaceRef.namespace`` (defaulting to the ``PalaceRef.id``).
    """

    name = "chroma_http"
    capabilities = frozenset(
        {
            "supports_embeddings_in",
            "supports_embeddings_passthrough",
            "supports_embeddings_out",
            "supports_metadata_filters",
            "supports_contains_fast",
            "http_mode",
        }
    )

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        ssl: Optional[bool] = None,
        token: Optional[str] = None,
        auth_header: str = "Authorization",
        tenant: Optional[str] = None,
        database: Optional[str] = None,
    ) -> None:
        env = _resolve_connection()
        # Constructor args win over env so tests / explicit setups can override.
        self.url = url if url is not None else env["url"]
        self.host = host if host is not None else env["host"]
        self.port = port if port is not None else env["port"]
        self.ssl = ssl if ssl is not None else env["ssl"]
        self.token = token if token is not None else env["token"]
        self.auth_header = (
            auth_header
            if auth_header != "Authorization"
            else env["auth_header"]
        )
        self.tenant = tenant if tenant is not None else env["tenant"]
        self.database = database if database is not None else env["database"]
        self._client: Any = None
        self._closed = False

    # ── Internal helpers ─────────────────────────────────────────────────

    @staticmethod
    def _resolve_embedding_function():
        """Return the EF for the user's ``embedding_device`` setting.

        Same EF identity rule as the local backend (RFC 001 §6.2): the EF
        must be passed explicitly on every collection open, since chromadb
        does not persist the instance-level configuration.
        """
        try:
            from ..embedding import get_embedding_function

            return get_embedding_function()
        except Exception:
            logger.exception("Failed to build embedding function; using chromadb default")
            return None

    def _get_client(self):
        """Build (and cache) a ``chromadb.HttpClient`` from configured params."""
        if self._closed:
            raise RuntimeError("HttpChromaBackend is closed")
        if self._client is not None:
            return self._client

        host, port, ssl = self._split_resolved()

        kwargs: dict[str, Any] = {
            "host": host,
            "port": port,
            "ssl": ssl,
        }
        if self.token:
            kwargs["headers"] = {self.auth_header: f"Bearer {self.token}"}
        if self.tenant:
            kwargs["tenant"] = self.tenant
        if self.database:
            kwargs["database"] = self.database

        self._client = chromadb.HttpClient(**kwargs)
        return self._client

    def _split_resolved(self) -> tuple[str, int, bool]:
        if self.url:
            return _split_url(self.url)
        host = self.host or "localhost"
        port = self.port or 8000
        ssl = bool(self.ssl)
        return host, port, ssl

    @staticmethod
    def _qualify(palace_ref: PalaceRef, collection_name: str) -> str:
        """Prefix the collection name with the palace namespace.

        Multiple palaces can share one chromadb server. Without a prefix
        every palace would collide on ``mempalace_drawers`` /
        ``mempalace_closets``. ``PalaceRef.namespace`` wins; falls back
        to ``PalaceRef.id`` (the palace path or explicit id).
        """
        ns = palace_ref.namespace or palace_ref.id
        # Sanitize: ChromaDB collection names allow [a-zA-Z0-9._-] only.
        safe = "".join(
            ch if ch.isalnum() or ch in "._-" else "-" for ch in (ns or "default")
        )
        if not safe or not safe[0].isalnum():
            safe = f"p{safe}"
        return f"{safe}__{collection_name}"

    # ── BaseBackend surface ──────────────────────────────────────────────

    def get_collection(
        self,
        *args,
        **kwargs,
    ) -> ChromaCollection:
        """Obtain a collection from the remote chromadb server.

        Mirrors :meth:`ChromaBackend.get_collection` but speaks HTTP. The
        ``palace_ref.local_path`` is *advisory* (used as fallback for the
        namespace prefix); HTTP mode never touches the local filesystem.
        """
        # Reuse the local backend's argument normalizer for parity — the
        # function is pure and lives in chroma.py.
        from .chroma import _normalize_get_collection_args

        palace_ref, collection_name, create, options = _normalize_get_collection_args(
            args, kwargs
        )
        qualified = self._qualify(palace_ref, collection_name)

        client = self._get_client()
        hnsw_space = "cosine"
        if options and isinstance(options, dict):
            hnsw_space = options.get("hnsw_space", hnsw_space)

        ef = self._resolve_embedding_function()
        ef_kwargs = {"embedding_function": ef} if ef is not None else {}

        if create:
            try:
                # Same SIGSEGV-avoidance split as ChromaBackend (#1262):
                # don't pass metadata when the collection already exists.
                from chromadb.errors import NotFoundError as _ChromaNotFoundError

                collection = client.get_collection(qualified, **ef_kwargs)
            except _ChromaNotFoundError:
                collection = client.create_collection(
                    qualified,
                    metadata={
                        "hnsw:space": hnsw_space,
                        "hnsw:num_threads": 1,
                        **_HNSW_BLOAT_GUARD,
                    },
                    **ef_kwargs,
                )
        else:
            try:
                collection = client.get_collection(qualified, **ef_kwargs)
            except Exception as e:
                # Translate chromadb's NotFoundError into the stable spec error.
                from chromadb.errors import NotFoundError as _ChromaNotFoundError

                if isinstance(e, _ChromaNotFoundError):
                    raise PalaceNotFoundError(
                        f"collection {qualified!r} not found on remote chromadb"
                    ) from e
                raise
        _pin_hnsw_threads(collection)
        return ChromaCollection(collection)

    def close_palace(self, palace) -> None:
        """No-op for HTTP — there is no per-palace state to evict."""
        return None

    def close(self) -> None:
        self._client = None
        self._closed = True

    def health(self, palace: Optional[PalaceRef] = None) -> HealthStatus:
        """Probe the chromadb server. Returns unhealthy on connection errors."""
        if self._closed:
            return HealthStatus.unhealthy("backend closed")
        try:
            client = self._get_client()
            client.heartbeat()
        except Exception as e:
            return HealthStatus.unhealthy(f"chromadb HTTP heartbeat failed: {e}")
        return HealthStatus.healthy(
            f"connected to {self._split_resolved()[0]}:{self._split_resolved()[1]}"
        )

    @classmethod
    def detect(cls, path: str) -> bool:
        """Return True iff the env says we should be in HTTP mode.

        ``path`` is ignored — HTTP mode does not key on filesystem layout.
        Auto-detection here matters when callers pass through
        :func:`mempalace.backends.registry.resolve_backend_for_palace`
        without an explicit ``MEMPALACE_BACKEND`` env value.
        """
        return _detect_env_configured()

    # ── Helper for mcp_server / cli compatibility ────────────────────────

    @staticmethod
    def make_client():
        """Build a chromadb ``HttpClient`` from the current process env.

        Convenience for legacy callers (``mcp_server._get_client``,
        ``cli.py`` repair commands) that previously called
        ``ChromaBackend.make_client(palace_path)`` and need a drop-in
        replacement when running in HTTP mode.
        """
        backend = HttpChromaBackend()
        return backend._get_client()

    @staticmethod
    def backend_version() -> str:
        return chromadb.__version__

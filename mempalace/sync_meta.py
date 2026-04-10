"""
sync_meta.py — Node identity and sync metadata for multi-device replication.

Each MemPalace installation gets a unique node_id (generated once, persisted).
Every write operation gets a monotonically increasing sequence number and a
UTC timestamp.  These three fields enable the sync protocol (Phase 4) to
efficiently exchange only new/changed records between nodes.

Files:
    ~/.mempalace/node_id   — 12-char hex string, generated once
    ~/.mempalace/seq       — integer, incremented on every write

Metadata injected into every record:
    node_id:    str   — which machine wrote this record
    seq:        int   — monotonic counter on that machine
    updated_at: str   — ISO 8601 UTC wall clock time
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

try:
    import msvcrt
    _HAS_MSVCRT = True
except ImportError:
    _HAS_MSVCRT = False


class NodeIdentity:
    """Manages the node_id and sequence counter for this machine.

    Thread-safe sequence counter using file locking.
    """

    def __init__(self, config_dir: str = None):
        self._dir = Path(config_dir) if config_dir else Path(os.path.expanduser("~/.mempalace"))
        self._dir.mkdir(parents=True, exist_ok=True)
        self._node_id_file = self._dir / "node_id"
        self._seq_file = self._dir / "seq"
        self._node_id = None

    @property
    def node_id(self) -> str:
        """Return this machine's unique node_id.  Generated once, then persisted."""
        if self._node_id is not None:
            return self._node_id

        if self._node_id_file.exists():
            self._node_id = self._node_id_file.read_text().strip()
        else:
            self._node_id = uuid4().hex[:12]
            self._node_id_file.write_text(self._node_id)
            try:
                self._node_id_file.chmod(0o600)
            except (OSError, NotImplementedError):
                pass

        return self._node_id

    @staticmethod
    def _lock(fd):
        if _HAS_FCNTL:
            fcntl.flock(fd, fcntl.LOCK_EX)
        elif _HAS_MSVCRT:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 4096)

    @staticmethod
    def _unlock(fd):
        if _HAS_FCNTL:
            fcntl.flock(fd, fcntl.LOCK_UN)
        elif _HAS_MSVCRT:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 4096)

    def next_seq(self, count: int = 1) -> int:
        """Atomically increment and return the sequence counter.

        Args:
            count: How many sequence numbers to allocate (default 1).
                   Returns the *first* allocated number; caller uses
                   first..first+count-1.

        Uses file locking so concurrent processes on the same machine
        don't collide.
        """
        self._dir.mkdir(parents=True, exist_ok=True)

        # Open-or-create the seq file
        fd = os.open(str(self._seq_file), os.O_RDWR | os.O_CREAT)
        try:
            self._lock(fd)
            data = os.read(fd, 64)
            current = int(data.strip()) if data.strip() else 0
            first = current + 1
            new_val = current + count
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, str(new_val).encode())
        finally:
            self._unlock(fd)
            os.close(fd)

        return first

    def current_seq(self) -> int:
        """Read the current sequence counter without incrementing."""
        if not self._seq_file.exists():
            return 0
        try:
            return int(self._seq_file.read_text().strip())
        except (ValueError, OSError):
            return 0


def utcnow_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ── Module-level singleton ────────────────────────────────────────────────────

_identity: NodeIdentity | None = None


def get_identity(config_dir: str = None) -> NodeIdentity:
    """Get or create the module-level NodeIdentity singleton."""
    global _identity
    if _identity is None or config_dir is not None:
        _identity = NodeIdentity(config_dir)
    return _identity


def inject_sync_meta(metadatas: list[dict], identity: NodeIdentity = None) -> list[dict]:
    """Inject node_id, seq, and updated_at into a batch of metadata dicts.

    Each record in the batch gets a unique seq number.
    Returns new list (does not mutate originals).
    """
    if identity is None:
        identity = get_identity()

    now = utcnow_iso()
    first_seq = identity.next_seq(count=len(metadatas))

    result = []
    for i, meta in enumerate(metadatas):
        m = dict(meta)
        m["node_id"] = identity.node_id
        m["seq"] = first_seq + i
        m["updated_at"] = now
        result.append(m)

    return result

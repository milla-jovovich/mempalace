"""
sync_client.py — HTTP client for syncing with a remote MemPalace server.

Usage:
    from mempalace.sync_client import SyncClient
    client = SyncClient("http://homeserver:7433")
    client.sync(engine)           # push + pull
    client.is_reachable()         # health check
"""

from __future__ import annotations

import logging
from urllib.request import Request, urlopen
import json

from .sync import SyncEngine, ChangeSet

logger = logging.getLogger("mempalace.sync_client")


class SyncClient:
    """HTTP client that talks to a mempalace sync server."""

    def __init__(self, server_url: str, timeout: float = 30.0):
        self._url = server_url.rstrip("/")
        self._timeout = timeout

    def _request(self, method: str, path: str, body: dict = None) -> dict:
        """Make an HTTP request and return parsed JSON."""
        url = f"{self._url}{path}"
        data = json.dumps(body).encode("utf-8") if body else None
        headers = {"Content-Type": "application/json"} if data else {}
        req = Request(url, data=data, headers=headers, method=method)
        with urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def is_reachable(self) -> bool:
        """Check if the server is reachable."""
        try:
            r = self._request("GET", "/health")
            return r.get("status") == "ok"
        except Exception:
            return False

    def get_status(self) -> dict:
        """Get server's node_id, version_vector, and drawer count."""
        return self._request("GET", "/sync/status")

    def push(self, changeset: ChangeSet) -> dict:
        """Send a changeset to the server."""
        return self._request("POST", "/sync/push", changeset.to_dict())

    def pull(self, local_vv: dict[str, int]) -> ChangeSet:
        """Request records the local node hasn't seen."""
        resp = self._request("POST", "/sync/pull", {"version_vector": local_vv})
        return ChangeSet.from_dict(resp)

    def sync(self, engine: SyncEngine) -> dict:
        """Full bidirectional sync: push our changes, then pull theirs.

        Returns a summary dict.
        """
        # 1. Get server status
        status = self.get_status()
        server_vv = status["version_vector"]
        server_node = status["node_id"]

        logger.info(
            "Sync start — server=%s drawers=%d",
            server_node,
            status["total_drawers"],
        )

        # 2. Push: send records the server hasn't seen
        changeset = engine.get_changes_since(server_vv)
        push_result = {"sent": 0, "accepted": 0, "rejected": 0}
        if changeset.records:
            resp = self.push(changeset)
            push_result = {
                "sent": len(changeset.records),
                "accepted": resp.get("accepted", 0),
                "rejected": resp.get("rejected_conflicts", 0),
            }
            logger.info(
                "Push: sent=%d accepted=%d rejected=%d",
                push_result["sent"],
                push_result["accepted"],
                push_result["rejected"],
            )

        # 3. Pull: get records we haven't seen
        local_vv = engine.version_vector
        remote_changes = self.pull(local_vv)
        pull_result = {"received": 0, "accepted": 0, "rejected": 0}
        if remote_changes.records:
            merge = engine.apply_changes(remote_changes)
            pull_result = {
                "received": len(remote_changes.records),
                "accepted": merge.accepted,
                "rejected": merge.rejected_conflicts,
            }
            logger.info(
                "Pull: received=%d accepted=%d rejected=%d",
                pull_result["received"],
                pull_result["accepted"],
                pull_result["rejected"],
            )

        return {
            "server": server_node,
            "push": push_result,
            "pull": pull_result,
            "local_vv": engine.version_vector,
        }

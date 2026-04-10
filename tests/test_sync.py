"""Tests for sync engine, server, and client — multi-device replication."""

import json
import os

import pytest

from mempalace.db import open_collection
from mempalace.sync import SyncEngine, ChangeSet, SyncRecord, VersionVector
from mempalace.sync_meta import NodeIdentity


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_engine(tmp_path, name="node_a"):
    """Create a SyncEngine with its own palace, identity, and VV."""
    palace = str(tmp_path / name / "palace")
    config = str(tmp_path / name / "config")
    ni = NodeIdentity(config_dir=config)
    col = open_collection(palace, backend="lance", sync_identity=ni)
    vv_path = os.path.join(palace, "version_vector.json")
    return SyncEngine(col, identity=ni, vv_path=vv_path), col, ni


# ── VersionVector ─────────────────────────────────────────────────────────────


class TestVersionVector:
    def test_empty(self):
        vv = VersionVector()
        assert vv.get("any") == 0
        assert vv.to_dict() == {}

    def test_update_and_get(self):
        vv = VersionVector()
        vv.update("node_a", 5)
        assert vv.get("node_a") == 5

    def test_update_only_advances(self):
        vv = VersionVector()
        vv.update("node_a", 10)
        vv.update("node_a", 3)  # should not go backwards
        assert vv.get("node_a") == 10

    def test_persistence(self, tmp_path):
        path = str(tmp_path / "vv.json")
        vv1 = VersionVector(path=path)
        vv1.update("node_a", 42)

        vv2 = VersionVector(path=path)
        assert vv2.get("node_a") == 42

    def test_update_from_records(self):
        vv = VersionVector()
        records = [
            SyncRecord(id="r1", document="", metadata={"node_id": "a", "seq": 3}),
            SyncRecord(id="r2", document="", metadata={"node_id": "a", "seq": 7}),
            SyncRecord(id="r3", document="", metadata={"node_id": "b", "seq": 2}),
        ]
        vv.update_from_records(records)
        assert vv.get("a") == 7
        assert vv.get("b") == 2

    def test_from_dict(self):
        vv = VersionVector.from_dict({"x": 10, "y": 20})
        assert vv.get("x") == 10
        assert vv.get("y") == 20


# ── ChangeSet serialisation ───────────────────────────────────────────────────


class TestChangeSet:
    def test_round_trip(self):
        cs = ChangeSet(
            source_node="abc",
            records=[SyncRecord(id="r1", document="hello", metadata={"wing": "w"})],
        )
        d = cs.to_dict()
        cs2 = ChangeSet.from_dict(d)
        assert cs2.source_node == "abc"
        assert cs2.records[0].id == "r1"
        assert cs2.records[0].document == "hello"

    def test_with_embedding(self):
        cs = ChangeSet(
            source_node="x",
            records=[SyncRecord(id="r1", document="hi", metadata={}, embedding=[0.1, 0.2])],
        )
        d = cs.to_dict()
        cs2 = ChangeSet.from_dict(d)
        assert cs2.records[0].embedding == [0.1, 0.2]


# ── SyncEngine ────────────────────────────────────────────────────────────────


class TestSyncEngine:
    def test_get_changes_empty(self, tmp_path):
        engine, col, ni = _make_engine(tmp_path)
        cs = engine.get_changes_since({})
        assert len(cs.records) == 0

    def test_get_changes_returns_new_records(self, tmp_path):
        engine, col, ni = _make_engine(tmp_path)

        col.upsert(
            documents=["doc one", "doc two"],
            ids=["d1", "d2"],
            metadatas=[
                {"wing": "proj", "room": "a", "source_file": ""},
                {"wing": "proj", "room": "b", "source_file": ""},
            ],
        )

        cs = engine.get_changes_since({})
        assert len(cs.records) == 2
        assert cs.source_node == ni.node_id

    def test_get_changes_respects_remote_vv(self, tmp_path):
        engine, col, ni = _make_engine(tmp_path)

        col.upsert(
            documents=["first"],
            ids=["d1"],
            metadatas=[{"wing": "p", "room": "r", "source_file": ""}],
        )
        col.upsert(
            documents=["second"],
            ids=["d2"],
            metadatas=[{"wing": "p", "room": "r", "source_file": ""}],
        )

        # Remote has already seen seq 1
        cs = engine.get_changes_since({ni.node_id: 1})
        assert len(cs.records) == 1
        assert cs.records[0].id == "d2"

    def test_apply_new_records(self, tmp_path):
        engine, col, ni = _make_engine(tmp_path)

        cs = ChangeSet(
            source_node="remote_node",
            records=[
                SyncRecord(
                    id="remote_1",
                    document="hello from remote",
                    metadata={
                        "wing": "proj",
                        "room": "x",
                        "source_file": "",
                        "node_id": "remote_node",
                        "seq": 1,
                        "updated_at": "2026-04-10T10:00:00+00:00",
                    },
                ),
            ],
        )

        result = engine.apply_changes(cs)
        assert result.accepted == 1
        assert result.rejected_conflicts == 0

        # Record should exist
        r = col.get(ids=["remote_1"], include=["documents"])
        assert r["documents"][0] == "hello from remote"

    def test_conflict_last_writer_wins(self, tmp_path):
        engine, col, ni = _make_engine(tmp_path)

        # Write a local record with a known old timestamp (bypass sync injection)
        col.upsert(
            documents=["local version"],
            ids=["conflict_id"],
            metadatas=[
                {
                    "wing": "p",
                    "room": "r",
                    "source_file": "",
                    "node_id": ni.node_id,
                    "seq": 1,
                    "updated_at": "2020-01-01T00:00:00+00:00",
                }
            ],
            _raw=True,
        )

        # Remote has a NEWER version of the same ID
        cs = ChangeSet(
            source_node="remote",
            records=[
                SyncRecord(
                    id="conflict_id",
                    document="remote version WINS",
                    metadata={
                        "wing": "p",
                        "room": "r",
                        "source_file": "",
                        "node_id": "remote",
                        "seq": 5,
                        "updated_at": "2099-01-01T00:00:00+00:00",
                    },
                )
            ],
        )

        result = engine.apply_changes(cs)
        assert result.accepted == 1

        r = col.get(ids=["conflict_id"], include=["documents"])
        assert r["documents"][0] == "remote version WINS"

    def test_conflict_local_wins_when_newer(self, tmp_path):
        engine, col, ni = _make_engine(tmp_path)

        # Write a local record with a known future timestamp (bypass sync injection)
        col.upsert(
            documents=["local version WINS"],
            ids=["conflict_id"],
            metadatas=[
                {
                    "wing": "p",
                    "room": "r",
                    "source_file": "",
                    "node_id": ni.node_id,
                    "seq": 1,
                    "updated_at": "2099-01-01T00:00:00+00:00",
                }
            ],
            _raw=True,
        )

        # Remote has an OLDER version
        cs = ChangeSet(
            source_node="remote",
            records=[
                SyncRecord(
                    id="conflict_id",
                    document="remote version LOSES",
                    metadata={
                        "wing": "p",
                        "room": "r",
                        "source_file": "",
                        "node_id": "remote",
                        "seq": 5,
                        "updated_at": "2020-01-01T00:00:00+00:00",
                    },
                )
            ],
        )

        result = engine.apply_changes(cs)
        assert result.rejected_conflicts == 1

        r = col.get(ids=["conflict_id"], include=["documents"])
        assert r["documents"][0] == "local version WINS"

    def test_version_vector_advances_after_apply(self, tmp_path):
        engine, col, ni = _make_engine(tmp_path)

        cs = ChangeSet(
            source_node="remote",
            records=[
                SyncRecord(
                    id="r1",
                    document="a",
                    metadata={
                        "wing": "p",
                        "room": "r",
                        "source_file": "",
                        "node_id": "remote",
                        "seq": 10,
                        "updated_at": "2026-04-10T10:00:00+00:00",
                    },
                ),
                SyncRecord(
                    id="r2",
                    document="b",
                    metadata={
                        "wing": "p",
                        "room": "r",
                        "source_file": "",
                        "node_id": "remote",
                        "seq": 11,
                        "updated_at": "2026-04-10T10:00:00+00:00",
                    },
                ),
            ],
        )

        engine.apply_changes(cs)
        assert engine.version_vector.get("remote") == 11


# ── Full two-node simulation ─────────────────────────────────────────────────


class TestTwoNodeSync:
    """Simulate two nodes syncing without HTTP (direct engine calls)."""

    def test_bidirectional_sync(self, tmp_path):
        engine_a, col_a, ni_a = _make_engine(tmp_path, "node_a")
        engine_b, col_b, ni_b = _make_engine(tmp_path, "node_b")

        # Node A writes
        col_a.upsert(
            documents=["from node A"],
            ids=["a1"],
            metadatas=[{"wing": "proj", "room": "r", "source_file": ""}],
        )

        # Node B writes
        col_b.upsert(
            documents=["from node B"],
            ids=["b1"],
            metadatas=[{"wing": "proj", "room": "r", "source_file": ""}],
        )

        # Sync: A pushes to B
        cs_a = engine_a.get_changes_since(engine_b.version_vector)
        assert len(cs_a.records) == 1
        result = engine_b.apply_changes(cs_a)
        assert result.accepted == 1

        # Sync: B pushes to A
        cs_b = engine_b.get_changes_since(engine_a.version_vector)
        assert len(cs_b.records) == 1
        result = engine_a.apply_changes(cs_b)
        assert result.accepted == 1

        # Both nodes now have both records
        assert col_a.count() == 2
        assert col_b.count() == 2

        r_a = col_a.get(ids=["b1"], include=["documents"])
        assert r_a["documents"][0] == "from node B"

        r_b = col_b.get(ids=["a1"], include=["documents"])
        assert r_b["documents"][0] == "from node A"

    def test_second_sync_is_noop(self, tmp_path):
        """After a full sync, a second sync should transfer nothing."""
        engine_a, col_a, ni_a = _make_engine(tmp_path, "node_a")
        engine_b, col_b, ni_b = _make_engine(tmp_path, "node_b")

        col_a.upsert(
            documents=["doc A"],
            ids=["a1"],
            metadatas=[{"wing": "p", "room": "r", "source_file": ""}],
        )

        # First sync
        cs = engine_a.get_changes_since(engine_b.version_vector)
        engine_b.apply_changes(cs)

        # Second sync — should be empty
        cs2 = engine_a.get_changes_since(engine_b.version_vector)
        assert len(cs2.records) == 0


# ── FastAPI integration ───────────────────────────────────────────────────────


class TestSyncServer:
    """Test the HTTP sync server via FastAPI TestClient."""

    @pytest.fixture(autouse=True)
    def setup_server(self, tmp_path, monkeypatch):
        """Configure a fresh palace for the server."""
        palace = str(tmp_path / "server_palace")
        monkeypatch.setenv("MEMPALACE_PALACE_PATH", palace)

        config_dir = str(tmp_path / "server_config")
        os.makedirs(config_dir, exist_ok=True)
        with open(os.path.join(config_dir, "config.json"), "w") as f:
            json.dump({"palace_path": palace}, f)

        # Reset server globals
        import mempalace.sync_server as ss

        ss._engine = None
        ss._config = None
        monkeypatch.setattr(
            "mempalace.sync_server._get_engine",
            lambda: self._build_engine(tmp_path, palace),
        )

        from mempalace.sync_server import create_app

        self._app = create_app()
        self._palace = palace
        self._tmp = tmp_path

    def _build_engine(self, tmp_path, palace):
        ni = NodeIdentity(config_dir=str(tmp_path / "server_config"))
        col = open_collection(palace, backend="lance", sync_identity=ni)
        vv_path = os.path.join(palace, "version_vector.json")
        return SyncEngine(col, identity=ni, vv_path=vv_path)

    def _client(self):
        from fastapi.testclient import TestClient

        return TestClient(self._app)

    def test_health(self):
        r = self._client().get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_status_empty(self):
        r = self._client().get("/sync/status")
        assert r.status_code == 200
        data = r.json()
        assert "node_id" in data
        assert data["total_drawers"] == 0
        assert isinstance(data["version_vector"], dict)

    def test_push_and_pull(self):
        c = self._client()

        # Push records to server
        push_body = {
            "source_node": "laptop_node",
            "records": [
                {
                    "id": "lap_1",
                    "document": "laptop document one",
                    "metadata": {
                        "wing": "proj",
                        "room": "a",
                        "source_file": "",
                        "node_id": "laptop_node",
                        "seq": 1,
                        "updated_at": "2026-04-10T10:00:00+00:00",
                    },
                },
                {
                    "id": "lap_2",
                    "document": "laptop document two",
                    "metadata": {
                        "wing": "proj",
                        "room": "b",
                        "source_file": "",
                        "node_id": "laptop_node",
                        "seq": 2,
                        "updated_at": "2026-04-10T10:00:00+00:00",
                    },
                },
            ],
        }
        r = c.post("/sync/push", json=push_body)
        assert r.status_code == 200
        assert r.json()["accepted"] == 2

        # Pull — laptop asks for everything (empty VV)
        r2 = c.post("/sync/pull", json={"version_vector": {}})
        assert r2.status_code == 200
        data = r2.json()
        # Server should return the records it has from its own node
        # (records pushed by laptop are from "laptop_node", not server's node)
        assert isinstance(data["records"], list)

        # Status should show the records
        r3 = c.get("/sync/status")
        assert r3.json()["total_drawers"] == 2
        assert r3.json()["version_vector"].get("laptop_node") == 2

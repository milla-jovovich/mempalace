"""Tests for sync_meta — node identity, sequence counter, metadata injection."""

import threading


from mempalace.sync_meta import NodeIdentity, inject_sync_meta, utcnow_iso


# ── NodeIdentity ──────────────────────────────────────────────────────


class TestNodeIdentity:
    def test_node_id_generated_and_persisted(self, tmp_path):
        ni = NodeIdentity(config_dir=str(tmp_path))
        nid = ni.node_id
        assert len(nid) == 12
        assert nid.isalnum()

        # Second read returns same value
        assert ni.node_id == nid

        # New instance reads from file
        ni2 = NodeIdentity(config_dir=str(tmp_path))
        assert ni2.node_id == nid

    def test_node_id_file_created(self, tmp_path):
        ni = NodeIdentity(config_dir=str(tmp_path))
        _ = ni.node_id
        assert (tmp_path / "node_id").exists()

    def test_next_seq_starts_at_1(self, tmp_path):
        ni = NodeIdentity(config_dir=str(tmp_path))
        assert ni.next_seq() == 1
        assert ni.next_seq() == 2
        assert ni.next_seq() == 3

    def test_next_seq_batch_allocation(self, tmp_path):
        ni = NodeIdentity(config_dir=str(tmp_path))
        first = ni.next_seq(count=5)
        assert first == 1
        # Next call should start after the batch
        assert ni.next_seq() == 6

    def test_current_seq_without_writes(self, tmp_path):
        ni = NodeIdentity(config_dir=str(tmp_path))
        assert ni.current_seq() == 0

    def test_current_seq_after_writes(self, tmp_path):
        ni = NodeIdentity(config_dir=str(tmp_path))
        ni.next_seq(count=10)
        assert ni.current_seq() == 10

    def test_seq_persists_across_instances(self, tmp_path):
        ni1 = NodeIdentity(config_dir=str(tmp_path))
        ni1.next_seq(count=5)

        ni2 = NodeIdentity(config_dir=str(tmp_path))
        assert ni2.current_seq() == 5
        assert ni2.next_seq() == 6

    def test_seq_thread_safety(self, tmp_path):
        """Multiple threads incrementing the counter should not lose values."""
        ni = NodeIdentity(config_dir=str(tmp_path))
        results = []
        errors = []

        def worker():
            try:
                for _ in range(50):
                    results.append(ni.next_seq())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # 4 threads × 50 increments = 200 unique sequence numbers
        assert len(results) == 200
        assert len(set(results)) == 200  # all unique
        assert ni.current_seq() == 200


# ── inject_sync_meta ──────────────────────────────────────────────────


class TestInjectSyncMeta:
    def test_injects_fields(self, tmp_path):
        ni = NodeIdentity(config_dir=str(tmp_path))
        metas = [{"wing": "test", "room": "a"}, {"wing": "test", "room": "b"}]
        result = inject_sync_meta(metas, identity=ni)

        assert len(result) == 2
        for m in result:
            assert "node_id" in m
            assert "seq" in m
            assert "updated_at" in m
            assert m["node_id"] == ni.node_id

    def test_preserves_original_fields(self, tmp_path):
        ni = NodeIdentity(config_dir=str(tmp_path))
        metas = [{"wing": "proj", "room": "backend", "custom": "value"}]
        result = inject_sync_meta(metas, identity=ni)

        assert result[0]["wing"] == "proj"
        assert result[0]["room"] == "backend"
        assert result[0]["custom"] == "value"

    def test_does_not_mutate_originals(self, tmp_path):
        ni = NodeIdentity(config_dir=str(tmp_path))
        original = {"wing": "test"}
        metas = [original]
        result = inject_sync_meta(metas, identity=ni)

        assert "node_id" not in original  # original untouched
        assert "node_id" in result[0]

    def test_sequential_seq_numbers(self, tmp_path):
        ni = NodeIdentity(config_dir=str(tmp_path))
        metas = [{"wing": "a"}, {"wing": "b"}, {"wing": "c"}]
        result = inject_sync_meta(metas, identity=ni)

        seqs = [m["seq"] for m in result]
        assert seqs == [1, 2, 3]

    def test_subsequent_calls_continue_sequence(self, tmp_path):
        ni = NodeIdentity(config_dir=str(tmp_path))
        r1 = inject_sync_meta([{"x": 1}], identity=ni)
        r2 = inject_sync_meta([{"x": 2}], identity=ni)

        assert r1[0]["seq"] == 1
        assert r2[0]["seq"] == 2

    def test_updated_at_is_recent_utc(self, tmp_path):
        ni = NodeIdentity(config_dir=str(tmp_path))
        result = inject_sync_meta([{"wing": "test"}], identity=ni)

        ts = result[0]["updated_at"]
        assert "T" in ts
        assert "+" in ts or "Z" in ts  # has timezone info


# ── utcnow_iso ────────────────────────────────────────────────────────


def test_utcnow_iso_format():
    ts = utcnow_iso()
    assert "T" in ts
    # Should be parseable
    from datetime import datetime

    dt = datetime.fromisoformat(ts)
    assert dt.tzinfo is not None


# ── Integration: sync metadata flows through db.py ────────────────────


def test_sync_meta_in_lance_records(tmp_path):
    """Verify that upsert injects node_id/seq/updated_at into stored metadata."""
    from mempalace.palace import get_collection
    from mempalace.sync_meta import NodeIdentity

    ni = NodeIdentity(config_dir=str(tmp_path / "config"))
    col = get_collection(str(tmp_path / "palace"), backend="lance", sync_identity=ni)

    col.upsert(
        documents=["test document one", "test document two"],
        ids=["t1", "t2"],
        metadatas=[
            {"wing": "proj", "room": "tech", "source_file": "a.py"},
            {"wing": "proj", "room": "db", "source_file": "b.py"},
        ],
    )

    result = col.get(ids=["t1", "t2"], include=["metadatas"])
    for meta in result["metadatas"]:
        assert "node_id" in meta, "node_id missing from stored metadata"
        assert "seq" in meta, "seq missing from stored metadata"
        assert "updated_at" in meta, "updated_at missing from stored metadata"
        assert meta["node_id"] == ni.node_id

    # seq should be sequential
    seqs = sorted(m["seq"] for m in result["metadatas"])
    assert seqs == [1, 2]

    # Second upsert continues the sequence
    col.upsert(
        documents=["third"],
        ids=["t3"],
        metadatas=[{"wing": "proj", "room": "misc", "source_file": "c.py"}],
    )
    r2 = col.get(ids=["t3"], include=["metadatas"])
    assert r2["metadatas"][0]["seq"] == 3

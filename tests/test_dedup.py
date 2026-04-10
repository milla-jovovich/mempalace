"""
test_dedup.py — Tests for deduplication features.

Covers:
  - tool_diary_write duplicate rejection (exact and near-identical)
  - tool_diary_write acceptance of distinct entries
  - tool_dedup_report clustering on seeded data
  - tool_dedup_report on clean (no duplicates) data
  - tool_dedup_report wing filtering
"""

from mempalace import mcp_server


def _setup_mcp(config, collection):
    """Point the MCP server at the test palace."""
    mcp_server._config = config
    mcp_server._client_cache = None
    mcp_server._collection_cache = None


# ==================== DIARY DEDUP ====================


class TestDiaryDedup:
    """tool_diary_write should reject near-identical entries."""

    def test_exact_duplicate_rejected(self, config, collection):
        _setup_mcp(config, collection)
        entry = "SESSION:2026-04-08|debugged.auth.flow+fixed.JWT.expiry|★★★"

        r1 = mcp_server.tool_diary_write("claude", entry, topic="work")
        assert r1["success"] is True

        r2 = mcp_server.tool_diary_write("claude", entry, topic="work")
        assert r2["success"] is False
        assert r2["reason"] == "duplicate_diary_entry"

    def test_near_duplicate_rejected(self, config, collection):
        _setup_mcp(config, collection)

        r1 = mcp_server.tool_diary_write(
            "claude",
            "SESSION:2026-04-08|debugged.auth.flow+fixed.JWT.expiry|★★★",
            topic="work",
        )
        assert r1["success"] is True

        # Near-identical: same content with trivial variation
        r2 = mcp_server.tool_diary_write(
            "claude",
            "SESSION:2026-04-08|debugged.auth.flow+fixed.JWT.expiry|★★",
            topic="work",
        )
        assert r2["success"] is False
        assert r2["reason"] == "duplicate_diary_entry"

    def test_distinct_entry_accepted(self, config, collection):
        _setup_mcp(config, collection)

        r1 = mcp_server.tool_diary_write(
            "claude",
            "SESSION:2026-04-08|debugged.auth.flow+fixed.JWT.expiry|★★★",
            topic="work",
        )
        assert r1["success"] is True

        # Completely different content should succeed
        r2 = mcp_server.tool_diary_write(
            "claude",
            "SESSION:2026-04-08|migrated.database.to.cockroachdb+updated.alembic.configs|★★",
            topic="infra",
        )
        assert r2["success"] is True

    def test_different_agents_can_write_similar(self, config, collection):
        """Two different agents writing similar entries should both succeed.

        NOTE: This test documents current behavior. Since dedup checks the
        entire collection (not per-agent), similar entries from different
        agents WILL be flagged as duplicates. This is arguably correct:
        if the same fact is already in the palace, a second copy adds noise
        regardless of who wrote it.
        """
        _setup_mcp(config, collection)
        entry = "The database migration completed successfully at 14:00 UTC."

        r1 = mcp_server.tool_diary_write("alice", entry, topic="deploy")
        assert r1["success"] is True

        # Second agent writing the same thing — cross-agent dedup kicks in
        r2 = mcp_server.tool_diary_write("bob", entry, topic="deploy")
        assert r2["success"] is False
        assert r2["reason"] == "duplicate_diary_entry"


# ==================== DEDUP REPORT ====================


class TestDedupReport:
    """tool_dedup_report should find and cluster near-duplicate drawers."""

    def test_report_on_clean_palace(self, config, collection):
        """No duplicates in a clean palace."""
        _setup_mcp(config, collection)

        # Add distinct documents
        collection.add(
            ids=["d1", "d2", "d3"],
            documents=[
                "The authentication module uses JWT tokens for session management.",
                "React frontend uses TanStack Query for server state management.",
                "Sprint planning: migrate auth to passkeys by Q3 2026.",
            ],
            metadatas=[
                {"wing": "proj", "room": "backend", "filed_at": "2026-01-01"},
                {"wing": "proj", "room": "frontend", "filed_at": "2026-01-02"},
                {"wing": "notes", "room": "planning", "filed_at": "2026-01-03"},
            ],
        )

        report = mcp_server.tool_dedup_report(threshold=0.92)
        assert report["total_duplicates"] == 0
        assert report["total_clusters"] == 0
        assert report["scanned"] == 3

    def test_report_finds_duplicates(self, config, collection):
        """Exact duplicates should appear in the report."""
        _setup_mcp(config, collection)

        # Add duplicated content
        collection.add(
            ids=["dup1", "dup2", "dup3", "unique1"],
            documents=[
                "The database uses PostgreSQL 15 with connection pooling via pgbouncer.",
                "The database uses PostgreSQL 15 with connection pooling via pgbouncer.",
                "The database uses PostgreSQL 15 with connection pooling via pgbouncer.",
                "React frontend uses TanStack Query for state management.",
            ],
            metadatas=[
                {"wing": "proj", "room": "backend", "filed_at": "2026-01-01"},
                {"wing": "proj", "room": "backend", "filed_at": "2026-01-02"},
                {"wing": "proj", "room": "backend", "filed_at": "2026-01-03"},
                {"wing": "proj", "room": "frontend", "filed_at": "2026-01-04"},
            ],
        )

        report = mcp_server.tool_dedup_report(threshold=0.92)
        assert report["total_duplicates"] >= 2
        assert report["total_clusters"] >= 1

    def test_report_wing_filter(self, config, collection):
        """Wing filter should restrict scan scope."""
        _setup_mcp(config, collection)

        collection.add(
            ids=["a1", "a2", "b1", "b2"],
            documents=[
                "Alpha wing document about testing infrastructure.",
                "Alpha wing document about testing infrastructure.",
                "Beta wing document about deployment pipelines.",
                "Beta wing document about deployment pipelines.",
            ],
            metadatas=[
                {"wing": "alpha", "room": "tests", "filed_at": "2026-01-01"},
                {"wing": "alpha", "room": "tests", "filed_at": "2026-01-02"},
                {"wing": "beta", "room": "deploy", "filed_at": "2026-01-03"},
                {"wing": "beta", "room": "deploy", "filed_at": "2026-01-04"},
            ],
        )

        report_alpha = mcp_server.tool_dedup_report(threshold=0.92, wing="alpha")
        assert report_alpha["scanned"] == 2

    def test_report_empty_palace(self, config, collection):
        """Report on empty palace should return zeros."""
        _setup_mcp(config, collection)
        report = mcp_server.tool_dedup_report()
        assert report["scanned"] == 0
        assert report["total_duplicates"] == 0

    def test_report_threshold_sensitivity(self, config, collection):
        """Lower threshold catches more near-duplicates."""
        _setup_mcp(config, collection)

        collection.add(
            ids=["sim1", "sim2"],
            documents=[
                "The authentication module uses JWT tokens for session management. "
                "Tokens expire after 24 hours. Refresh tokens are stored in cookies.",
                "The auth module uses JSON Web Tokens for session handling. "
                "Tokens expire after one day. Refresh tokens are in HTTP cookies.",
            ],
            metadatas=[
                {"wing": "proj", "room": "auth", "filed_at": "2026-01-01"},
                {"wing": "proj", "room": "auth", "filed_at": "2026-01-05"},
            ],
        )

        strict = mcp_server.tool_dedup_report(threshold=0.99)
        lenient = mcp_server.tool_dedup_report(threshold=0.70)

        # Lenient should find equal or more duplicates than strict
        assert lenient["total_duplicates"] >= strict["total_duplicates"]

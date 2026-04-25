"""
test_searcher.py -- Tests for both search() (CLI) and search_memories() (API).

Uses the real ChromaDB fixtures from conftest.py for integration tests,
plus mock-based tests for error paths.
"""

from unittest.mock import MagicMock, patch

import pytest

from mempalace.searcher import SearchError, search, search_memories


# ── search_memories (API) ──────────────────────────────────────────────


class TestSearchMemories:
    def test_basic_search(self, palace_path, seeded_collection):
        result = search_memories("JWT authentication", palace_path)
        assert "results" in result
        assert len(result["results"]) > 0
        assert result["query"] == "JWT authentication"

    def test_wing_filter(self, palace_path, seeded_collection):
        result = search_memories("planning", palace_path, wing="notes")
        assert all(r["wing"] == "notes" for r in result["results"])

    def test_room_filter(self, palace_path, seeded_collection):
        result = search_memories("database", palace_path, room="backend")
        assert all(r["room"] == "backend" for r in result["results"])

    def test_wing_and_room_filter(self, palace_path, seeded_collection):
        result = search_memories("code", palace_path, wing="project", room="frontend")
        assert all(r["wing"] == "project" and r["room"] == "frontend" for r in result["results"])

    def test_n_results_limit(self, palace_path, seeded_collection):
        result = search_memories("code", palace_path, n_results=2)
        assert len(result["results"]) <= 2

    def test_no_palace_returns_error(self, tmp_path):
        result = search_memories("anything", str(tmp_path / "missing"))
        assert "error" in result

    def test_result_fields(self, palace_path, seeded_collection):
        result = search_memories("authentication", palace_path)
        hit = result["results"][0]
        assert "text" in hit
        assert "wing" in hit
        assert "room" in hit
        assert "source_file" in hit
        assert "similarity" in hit
        assert isinstance(hit["similarity"], float)
        assert "created_at" in hit

    def test_created_at_contains_filed_at(self, palace_path, seeded_collection):
        """created_at surfaces the filed_at metadata from the drawer."""
        result = search_memories("JWT authentication", palace_path)
        hit = result["results"][0]
        assert hit["created_at"] == "2026-01-01T00:00:00"

    def test_created_at_fallback_when_filed_at_missing(self):
        """created_at defaults to 'unknown' when filed_at is absent."""
        mock_col = MagicMock()
        mock_col.count.return_value = 1
        mock_col.query.return_value = {
            "ids": [["drawer_no_date"]],
            "documents": [["Some text without a date"]],
            "metadatas": [[{"wing": "project", "room": "backend", "source_file": "x.py"}]],
            "distances": [[0.1]],
        }

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("test", "/fake/path")
        hit = result["results"][0]
        assert hit["created_at"] == "unknown"

    def test_search_memories_query_error_degrades_to_warning(self):
        """When the vector query raises, search_memories should degrade rather
        than hard-fail: surface the error as a warning and continue with the
        sqlite fallback so callers still see what's reachable. This is the
        "all info + why we can't get the rest" contract — a silent hit-miss
        would be worse than a crash because it makes the palace look empty
        when the data is actually there."""
        mock_col = MagicMock()
        mock_col.count.return_value = 0
        mock_col.query.side_effect = RuntimeError("query failed")
        # col.get is also called (for the sqlite fallback and pool count);
        # return an empty pool so the fallback finds nothing to promote.
        mock_col.get.return_value = {"documents": [], "metadatas": [], "ids": []}

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("test", "/fake/path")
        assert "error" not in result
        assert "warnings" in result
        assert any("query failed" in w for w in result["warnings"])
        assert result["results"] == []

    def test_search_memories_filters_in_result(self, palace_path, seeded_collection):
        result = search_memories("test", palace_path, wing="project", room="backend")
        assert result["filters"]["wing"] == "project"
        assert result["filters"]["room"] == "backend"

    def test_search_memories_handles_none_metadata(self):
        """API path: `None` entries in the drawer results' metadatas list must
        fall back to the sentinel strings (wing/room 'unknown', source '?')
        rather than raising `AttributeError: 'NoneType' object has no
        attribute 'get'` while the rest of the result set renders."""
        mock_col = MagicMock()
        mock_col.count.return_value = 2
        mock_col.query.return_value = {
            "documents": [["first doc", "second doc"]],
            "metadatas": [[{"source_file": "a.md", "wing": "w", "room": "r"}, None]],
            "distances": [[0.1, 0.2]],
            "ids": [["d1", "d2"]],
        }

        def mock_get_collection(path, create=False):
            # First call: drawers. Second call: closets — raise so hybrid
            # degrades to pure drawer search (the catch block covers it).
            if not hasattr(mock_get_collection, "_called"):
                mock_get_collection._called = True
                return mock_col
            raise RuntimeError("no closets")

        with patch("mempalace.searcher.get_collection", side_effect=mock_get_collection):
            result = search_memories("anything", "/fake/path")
        assert "results" in result
        assert len(result["results"]) == 2
        # The None-metadata hit renders with sentinel values, not a crash.
        none_hit = result["results"][1]
        assert none_hit["text"] == "second doc"
        assert none_hit["wing"] == "unknown"
        assert none_hit["room"] == "unknown"

    def test_search_memories_fills_from_sqlite_when_vector_underdelivers(self):
        """If vector returns fewer than n_results but sqlite has more drawers
        matching the scope, BM25-rank the leftover pool and fill the gap.
        This is the kiyo failure mode: vector returned 0 hits while sqlite
        had 5,243 drawers in the requested wing. After this change, the
        sqlite pool is BM25-ranked and the top keyword matches fill in."""
        mock_col = MagicMock()
        mock_col.count.return_value = 4
        # Vector returns only 1 result
        mock_col.query.return_value = {
            "documents": [["vector hit about kiyo"]],
            "metadatas": [
                [{"wing": "kiyo-xhci-fix", "room": "kiyo_xhci_fix", "source_file": "a.sh"}]
            ],
            "distances": [[0.2]],
            "ids": [["d1"]],
        }
        # Sqlite pool has 3 more drawers matching the scope — two mention kiyo
        mock_col.get.return_value = {
            "ids": ["d1", "d2", "d3", "d4"],
            "documents": [
                "vector hit about kiyo",
                "another kiyo xhci fix write-up",
                "unrelated content no match terms",
                "more kiyo pro usb crash investigation",
            ],
            "metadatas": [
                {"wing": "kiyo-xhci-fix", "room": "kiyo_xhci_fix", "source_file": "a.sh"},
                {"wing": "kiyo-xhci-fix", "room": "kiyo_xhci_fix", "source_file": "b.md"},
                {"wing": "kiyo-xhci-fix", "room": "kiyo_xhci_fix", "source_file": "c.md"},
                {"wing": "kiyo-xhci-fix", "room": "kiyo_xhci_fix", "source_file": "d.log"},
            ],
        }

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("kiyo xhci", "/fake/path", wing="kiyo-xhci-fix", n_results=5)

        # Vector gave 1, sqlite fill promoted 2 more (the ones with "kiyo" or
        # "xhci" tokens); the unrelated drawer is skipped because BM25=0.
        assert len(result["results"]) >= 2
        vector_hits = [h for h in result["results"] if h.get("matched_via") == "drawer"]
        fallback_hits = [
            h for h in result["results"] if h.get("matched_via") == "sqlite_bm25_fallback"
        ]
        assert len(vector_hits) == 1
        assert len(fallback_hits) >= 1
        # Authoritative scope count reflects sqlite, not HNSW
        assert result["available_in_scope"] == 4
        # Warnings explain the top-up
        assert any("sqlite+BM25" in w for w in result["warnings"])


# ── BM25 internals: None / empty document safety ─────────────────────


class TestBM25NoneSafety:
    """Regression tests for the AttributeError observed in production when
    Chroma returned ``None`` documents inside a hybrid-rerank pass.

    Trace from the daemon log (2026-04-24 21:07:05):
        File "mempalace/searcher.py", line 81, in _bm25_scores
            tokenized = [_tokenize(d) for d in documents]
        File "mempalace/searcher.py", line 52, in _tokenize
            return _TOKEN_RE.findall(text.lower())
        AttributeError: 'NoneType' object has no attribute 'lower'
    """

    def test_tokenize_handles_none(self):
        from mempalace.searcher import _tokenize

        assert _tokenize(None) == []

    def test_tokenize_handles_empty_string(self):
        from mempalace.searcher import _tokenize

        assert _tokenize("") == []

    def test_bm25_scores_does_not_crash_on_none_documents(self):
        """A ``None`` mixed into the corpus must yield score 0.0 for that doc
        and finite scores for the rest, not raise AttributeError."""
        from mempalace.searcher import _bm25_scores

        scores = _bm25_scores(
            "postgres migration", ["postgres migration done", None, "kafka rebalance"]
        )
        assert len(scores) == 3
        assert scores[1] == 0.0
        assert scores[0] > 0.0


# ── checkpoint filter (kind= parameter) ─────────────────────────────────────


class TestCheckpointFilter:
    """Stop-hook auto-save checkpoints (topic='checkpoint' or 'auto-save',
    text starting with 'CHECKPOINT:') are session-summary noise that drown
    out actual user/agent content under vector similarity. Default search
    excludes them; opt-in via kind='checkpoint' or kind='all'.

    Defense in depth: both metadata-topic *and* text-prefix exclusion run,
    so legacy data with metadata=None or a missing topic field is still
    filtered out.
    """

    # ── unit: build_where_filter ──────────────────────────────────────
    #
    # NOTE: as of 2026-04-25 (commit fixing the chromadb 1.5.x filter-planner
    # bug, see _apply_kind_text_filter docstring), kind= is enforced
    # entirely in the post-filter, NOT in the where clause. The where
    # filter only carries wing/room. This avoids ChromaDB's "Error finding
    # id" failure mode when $nin/$in is combined with vector queries.

    def test_build_where_default_returns_empty(self):
        from mempalace.searcher import build_where_filter

        w = build_where_filter()
        assert w == {}

    def test_build_where_kind_checkpoint_returns_empty_where(self):
        """kind= no longer adds metadata clauses — filter is post-only."""
        from mempalace.searcher import build_where_filter

        w = build_where_filter(kind="checkpoint")
        assert w == {}

    def test_build_where_kind_all_returns_empty(self):
        from mempalace.searcher import build_where_filter

        w = build_where_filter(kind="all")
        assert w == {}

    def test_build_where_with_wing_returns_only_wing(self):
        """No more $and-with-topic; just the wing clause."""
        from mempalace.searcher import build_where_filter

        w = build_where_filter(wing="wing_x", kind="content")
        assert w == {"wing": "wing_x"}

    def test_build_where_with_wing_and_room(self):
        from mempalace.searcher import build_where_filter

        w = build_where_filter(wing="wing_x", room="room_y", kind="content")
        assert w == {"$and": [{"wing": "wing_x"}, {"room": "room_y"}]}

    def test_build_where_kind_invalid_raises(self):
        from mempalace.searcher import build_where_filter

        with pytest.raises(ValueError, match="kind must be"):
            build_where_filter(kind="bogus")

    # ── integration: search_memories post-filter coverage ─────────────
    #
    # As of 2026-04-25 (filter-planner bug fix): the kind= exclusion is
    # enforced ENTIRELY in the post-filter. The where-clause no longer
    # carries a topic clause. Both the topic metadata signal AND the
    # text-prefix signal must work in the post-filter.

    def test_search_memories_drops_checkpoint_by_topic_metadata(self):
        """Topic-tagged checkpoint without CHECKPOINT: text prefix —
        the post-filter must catch it via the topic field. (Previously
        this case was caught by the where-clause $nin filter; now it's
        the post-filter's responsibility since the where-clause was
        removed to avoid the chromadb 1.5.x filter-planner bug.)"""
        mock_col = MagicMock()
        mock_col.metadata = {"hnsw:space": "cosine"}
        mock_col.count.return_value = 2
        # Two drawers: one tagged topic=checkpoint but text doesn't have
        # the CHECKPOINT: prefix; one normal content drawer.
        mock_col.query.return_value = {
            "documents": [["a session checkpoint stored without prefix", "real content"]],
            "metadatas": [
                [
                    {"source_file": "a.md", "wing": "w", "room": "r", "topic": "checkpoint"},
                    {"source_file": "b.md", "wing": "w", "room": "r", "topic": "general"},
                ]
            ],
            "distances": [[0.3, 0.4]],
            "ids": [["d1", "d2"]],
        }
        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("query", "/fake/path")
        topics = [h.get("topic") for h in result["results"]]
        # The checkpoint-topic drawer is dropped via topic metadata,
        # even though its text doesn't have the CHECKPOINT: prefix.
        assert "checkpoint" not in topics
        assert "general" in topics

    def test_search_memories_default_drops_checkpoint_text_even_with_unknown_topic(self):
        """Legacy palace data may have ``CHECKPOINT:``-prefixed text but
        metadata={} or topic=None (pre-fix data, or callers that bypassed
        tool_diary_write). The post-filter catches both signals — topic
        metadata AND text prefix — so legacy untagged data is still
        dropped."""
        mock_col = MagicMock()
        mock_col.metadata = {"hnsw:space": "cosine"}
        mock_col.count.return_value = 2
        # Vector returns: one CHECKPOINT-shaped doc with no topic metadata,
        # one regular content doc.
        mock_col.query.return_value = {
            "documents": [["CHECKPOINT:2026-04-25|recent: noise here", "real content drawer"]],
            "metadatas": [
                [
                    {"source_file": "a.md", "wing": "w", "room": "r"},  # no topic field
                    {"source_file": "b.md", "wing": "w", "room": "r", "topic": "general"},
                ]
            ],
            "distances": [[0.3, 0.4]],
            "ids": [["d1", "d2"]],
        }
        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("query", "/fake/path")
        assert "results" in result
        texts = [h["text"] for h in result["results"]]
        # CHECKPOINT-prefixed drawer is dropped even though its metadata
        # didn't have topic=checkpoint to filter on at the where layer.
        assert all(not t.startswith("CHECKPOINT:") for t in texts)
        assert "real content drawer" in texts

    def test_search_memories_kind_checkpoint_includes_text_prefix_legacy(self):
        """Symmetric: kind='checkpoint' also picks up CHECKPOINT-shaped
        legacy data without topic metadata so audit/recovery callers get
        every checkpoint we can identify."""
        mock_col = MagicMock()
        mock_col.metadata = {"hnsw:space": "cosine"}
        mock_col.count.return_value = 2
        mock_col.query.return_value = {
            "documents": [["CHECKPOINT:2026-04-25|recent: legacy", "regular content"]],
            "metadatas": [
                [
                    {"source_file": "a.md", "wing": "w", "room": "r"},  # no topic
                    {"source_file": "b.md", "wing": "w", "room": "r", "topic": "general"},
                ]
            ],
            "distances": [[0.3, 0.4]],
            "ids": [["d1", "d2"]],
        }
        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("query", "/fake/path", kind="checkpoint")
        # The text-prefix legacy entry is included even though its
        # metadata had no topic field.
        assert any(h["text"].startswith("CHECKPOINT:") for h in result["results"])

    def test_search_memories_surfaces_topic_field_in_results(self):
        """Callers need to see ``topic`` in result dicts — both for
        debugging and so consumers (familiar.realm.watch's deterministic
        pipeline, RLM tools) can apply their own routing logic on it."""
        mock_col = MagicMock()
        mock_col.metadata = {"hnsw:space": "cosine"}
        mock_col.count.return_value = 1
        mock_col.query.return_value = {
            "documents": [["a thoughtful reflection"]],
            "metadatas": [
                [{"source_file": "a.md", "wing": "w", "room": "diary", "topic": "musings"}]
            ],
            "distances": [[0.2]],
            "ids": [["d1"]],
        }
        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            result = search_memories("query", "/fake/path")
        assert result["results"][0]["topic"] == "musings"


# ── search() (CLI print function) ─────────────────────────────────────


class TestSearchCLI:
    def test_search_prints_results(self, palace_path, seeded_collection, capsys):
        search("JWT authentication", palace_path)
        captured = capsys.readouterr()
        assert "JWT" in captured.out or "authentication" in captured.out

    def test_search_with_wing_filter(self, palace_path, seeded_collection, capsys):
        search("planning", palace_path, wing="notes")
        captured = capsys.readouterr()
        assert "Results for" in captured.out

    def test_search_with_room_filter(self, palace_path, seeded_collection, capsys):
        search("database", palace_path, room="backend")
        captured = capsys.readouterr()
        assert "Room:" in captured.out

    def test_search_with_wing_and_room(self, palace_path, seeded_collection, capsys):
        search("code", palace_path, wing="project", room="frontend")
        captured = capsys.readouterr()
        assert "Wing:" in captured.out
        assert "Room:" in captured.out

    def test_search_no_palace_raises(self, tmp_path):
        with pytest.raises(SearchError, match="No palace found"):
            search("anything", str(tmp_path / "missing"))

    def test_search_no_results(self, palace_path, collection, capsys):
        """Empty collection returns no results message."""
        # collection is empty (no seeded data)
        result = search("xyzzy_nonexistent_query", palace_path, n_results=1)
        captured = capsys.readouterr()
        # Either prints "No results" or returns None
        assert result is None or "No results" in captured.out

    def test_search_query_error_degrades_to_warning(self, capsys):
        """CLI search no longer raises when the vector query fails — it
        delegates to search_memories which degrades to a warning + sqlite
        fallback. The warning is printed so the user sees why the palace
        is returning fewer results than expected."""
        mock_col = MagicMock()
        mock_col.count.return_value = 0
        mock_col.query.side_effect = RuntimeError("boom")
        mock_col.get.return_value = {"documents": [], "metadatas": [], "ids": []}

        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            search("test", "/fake/path")
        captured = capsys.readouterr()
        assert "vector search unavailable" in captured.out
        assert "boom" in captured.out

    def test_search_n_results(self, palace_path, seeded_collection, capsys):
        search("code", palace_path, n_results=1)
        captured = capsys.readouterr()
        # Should have output with at least one result block
        assert "[1]" in captured.out

    def test_search_applies_bm25_hybrid_rerank(self, capsys):
        """CLI search must call the same hybrid rerank that the MCP path uses.

        Regression for a bug where the CLI only consulted ChromaDB cosine
        distance: a drawer whose body contained every query term still
        scored zero similarity if its embedding happened to be far from
        the query (e.g. the drawer was a shell-output fragment that
        embeds as "file tree noise"). Hybrid rerank fixes this by
        combining BM25 with cosine — lexical matches rise above pure
        vector noise.

        Simulates: three candidates, all with distance >= 1.0 (cosine = 0);
        candidate 2 contains every query term. After the fix, candidate 2
        should rank first and display a non-zero bm25 score.
        """
        mock_col = MagicMock()
        mock_col.metadata = {"hnsw:space": "cosine"}
        mock_col.count.return_value = 3
        mock_col.query.return_value = {
            "documents": [
                [
                    "unrelated directory listing -rw-rw-r-- file.txt",
                    "foo bar baz is a multi-word phrase",
                    "another unrelated chunk about colors",
                ]
            ],
            "metadatas": [
                [
                    {"source_file": "a.md", "wing": "w", "room": "r"},
                    {"source_file": "b.md", "wing": "w", "room": "r"},
                    {"source_file": "c.md", "wing": "w", "room": "r"},
                ]
            ],
            "distances": [[1.5, 1.5, 1.5]],
        }
        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            search("foo bar baz", "/fake/path")
        captured = capsys.readouterr()
        first_block, _, _ = captured.out.partition("[2]")
        # Lexical match must rank first
        assert (
            "b.md" in first_block
        ), f"expected lexical match 'b.md' at rank 1, got:\n{captured.out}"
        # Non-zero bm25 reported
        assert "bm25=" in first_block
        assert "bm25=0.0" not in first_block
        # Cosine still reported for transparency
        assert "cosine=" in first_block

    def test_search_warns_when_palace_uses_wrong_distance_metric(self, capsys):
        """Legacy palaces created without `hnsw:space=cosine` silently
        use L2, which breaks similarity interpretation. CLI must warn
        the user and point them at `mempalace repair` rather than
        pretending the `Match` scores are meaningful."""
        mock_col = MagicMock()
        mock_col.metadata = {}  # legacy: no hnsw:space set
        mock_col.count.return_value = 1
        mock_col.query.return_value = {
            "documents": [["some drawer content"]],
            "metadatas": [[{"source_file": "a.md", "wing": "w", "room": "r"}]],
            "distances": [[1.2]],
        }
        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            search("anything", "/fake/path")
        captured = capsys.readouterr()
        assert "mempalace repair" in captured.err
        assert "cosine" in captured.err.lower()

    def test_search_does_not_warn_when_palace_is_correctly_configured(self, capsys):
        mock_col = MagicMock()
        mock_col.metadata = {"hnsw:space": "cosine"}
        mock_col.count.return_value = 1
        mock_col.query.return_value = {
            "documents": [["some drawer content"]],
            "metadatas": [[{"source_file": "a.md", "wing": "w", "room": "r"}]],
            "distances": [[0.3]],
        }
        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            search("anything", "/fake/path")
        captured = capsys.readouterr()
        assert "mempalace repair" not in captured.err

    def test_search_handles_none_metadata_without_crash(self, capsys):
        """ChromaDB can return `None` entries in the metadatas list when a
        drawer has no metadata. The CLI print path must not crash on them
        mid-render — it used to raise `AttributeError: 'NoneType' object has
        no attribute 'get'` after printing earlier results."""
        mock_col = MagicMock()
        mock_col.count.return_value = 2
        mock_col.query.return_value = {
            "documents": [["first doc", "second doc"]],
            "metadatas": [[{"source_file": "a.md", "wing": "w", "room": "r"}, None]],
            "distances": [[0.1, 0.2]],
        }
        with patch("mempalace.searcher.get_collection", return_value=mock_col):
            search("anything", "/fake/path")
        captured = capsys.readouterr()
        assert "[1]" in captured.out
        assert "[2]" in captured.out
        # Second result renders with fallback '?' values instead of crashing
        assert "second doc" in captured.out

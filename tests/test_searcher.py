"""Tests for mempalace.searcher — search operations."""

import pytest

from mempalace.searcher import search, search_memories


class TestSearchMemories:
    @pytest.mark.integration
    def test_returns_results(self, palace_with_data):
        result = search_memories("GraphQL", palace_path=palace_with_data)
        assert "results" in result
        assert len(result["results"]) > 0

    @pytest.mark.integration
    def test_result_fields(self, palace_with_data):
        result = search_memories("chess", palace_path=palace_with_data)
        hit = result["results"][0]
        assert "text" in hit
        assert "wing" in hit
        assert "room" in hit
        assert "source_file" in hit
        assert "similarity" in hit

    @pytest.mark.integration
    def test_wing_filter(self, palace_with_data):
        result = search_memories("anything", palace_path=palace_with_data, wing="personal")
        for hit in result["results"]:
            assert hit["wing"] == "personal"

    @pytest.mark.integration
    def test_room_filter(self, palace_with_data):
        result = search_memories("anything", palace_path=palace_with_data, room="bugs")
        if result["results"]:
            assert result["results"][0]["room"] == "bugs"

    def test_no_palace_returns_error(self, tmp_path):
        result = search_memories("test", palace_path=str(tmp_path / "missing"))
        assert "error" in result

    @pytest.mark.integration
    def test_query_and_filters_in_response(self, palace_with_data):
        result = search_memories("test", palace_path=palace_with_data, wing="myapp", room="bugs")
        assert result["query"] == "test"
        assert result["filters"]["wing"] == "myapp"
        assert result["filters"]["room"] == "bugs"


class TestSearchCli:
    @pytest.mark.integration
    def test_prints_results(self, palace_with_data, capsys):
        search("GraphQL", palace_path=palace_with_data)
        out = capsys.readouterr().out
        assert "Results for:" in out
        assert "GraphQL" in out

    @pytest.mark.integration
    def test_no_results(self, palace_with_data, capsys):
        search("xyzzy_nonexistent_query_string_42", palace_path=palace_with_data)
        out = capsys.readouterr().out
        # Should still print something (either results or "no results")
        assert len(out) > 0

    def test_no_palace_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            search("test", palace_path=str(tmp_path / "nope"))

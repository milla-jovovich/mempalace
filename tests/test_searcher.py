from mempalace.searcher import search_memories


def test_search_returns_results(populated_palace):
    palace_path, _ = populated_palace
    result = search_memories("chess", palace_path)
    assert "results" in result
    assert len(result["results"]) > 0
    assert "Alice" in result["results"][0]["text"] or "chess" in result["results"][0]["text"]


def test_search_wing_filter(populated_palace):
    palace_path, _ = populated_palace
    result = search_memories("query", palace_path, wing="family")
    for hit in result["results"]:
        assert hit["wing"] == "family"


def test_search_room_filter(populated_palace):
    palace_path, _ = populated_palace
    result = search_memories("query", palace_path, room="backend")
    for hit in result["results"]:
        assert hit["room"] == "backend"


def test_search_wing_and_room_filter(populated_palace):
    palace_path, _ = populated_palace
    result = search_memories("query", palace_path, wing="code", room="backend")
    for hit in result["results"]:
        assert hit["wing"] == "code"
        assert hit["room"] == "backend"


def test_search_result_structure(populated_palace):
    palace_path, _ = populated_palace
    result = search_memories("chess", palace_path)
    hit = result["results"][0]
    assert "text" in hit
    assert "wing" in hit
    assert "room" in hit
    assert "source_file" in hit
    assert "similarity" in hit
    assert 0 <= hit["similarity"] <= 1


def test_search_missing_palace(tmp_dir):
    result = search_memories("query", str(tmp_dir / "nonexistent"))
    assert "error" in result


def test_search_n_results(populated_palace):
    palace_path, _ = populated_palace
    result = search_memories("anything", palace_path, n_results=2)
    assert len(result["results"]) <= 2

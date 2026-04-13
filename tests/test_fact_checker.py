"""Direct tests for contradiction detection logic and CLI entry points."""

import json
import sys

from mempalace.fact_checker import _build_parser, check_assertion, main


def test_check_assertion_clear(kg):
    result = check_assertion(kg, "Alice", "likes", "tea")

    assert result["status"] == "clear"
    assert result["conflicts"] == []


def test_check_assertion_duplicate(kg):
    kg.add_triple("Alice", "likes", "coffee")

    result = check_assertion(kg, "Alice", "likes", "coffee")

    assert result["status"] == "duplicate"
    assert result["matches"][0]["object"] == "coffee"


def test_check_assertion_warning_for_multi_value_relationship(kg):
    kg.add_triple("Alice", "likes", "coffee")

    result = check_assertion(kg, "Alice", "likes", "tea")

    assert result["status"] == "warning"
    assert result["conflicts"][0]["object"] == "coffee"


def test_check_assertion_conflict_for_single_value_relationship(kg):
    kg.add_triple("Alice", "works_at", "NewCo")

    result = check_assertion(kg, "Alice", "works_at", "OldCo")

    assert result["status"] == "conflict"
    assert result["conflicts"][0]["object"] == "NewCo"


def test_check_assertion_respects_as_of_filter(seeded_kg):
    result = check_assertion(seeded_kg, "Alice", "works_at", "Acme Corp", as_of="2024-06-01")

    assert result["status"] == "duplicate"
    assert result["matches"][0]["object"] == "Acme Corp"


def test_build_parser_accepts_optional_cli_flags():
    args = _build_parser().parse_args(
        ["Alice", "works at", "NewCo", "--as-of", "2024-06-01", "--kg", "/tmp/kg.sqlite3"]
    )

    assert args.subject == "Alice"
    assert args.predicate == "works at"
    assert args.object == "NewCo"
    assert args.as_of == "2024-06-01"
    assert args.kg == "/tmp/kg.sqlite3"


def test_fact_checker_main_prints_json_result(tmp_path, capsys, monkeypatch):
    from mempalace.knowledge_graph import KnowledgeGraph

    db_path = tmp_path / "kg.sqlite3"
    kg = KnowledgeGraph(db_path=str(db_path))
    kg.add_triple("Alice", "works_at", "NewCo")
    kg.close()

    # Exercise the in-process CLI entry point so coverage includes the parser
    # and print path, not only the subprocess smoke test.
    monkeypatch.setattr(
        sys,
        "argv",
        ["mempalace.fact_checker", "Alice", "works_at", "OldCo", "--kg", str(db_path)],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "conflict"
    assert payload["conflicts"][0]["object"] == "NewCo"

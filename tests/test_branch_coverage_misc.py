"""Focused branch coverage for CLI/bootstrap helpers and small fallback paths."""

import argparse
import json
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from mempalace import dedup, repair
from mempalace.agents import list_agents
from mempalace.cli import _write_project_entities, cmd_compress, cmd_migrate, cmd_repair
from mempalace.convo_miner import (
    MAX_FILE_SIZE,
    _chunk_by_exchange,
    chunk_exchanges,
    mine_convos,
    scan_convos,
)
from mempalace.dialect import Dialect
from mempalace.entity_detector import classify_entity, confirm_entities, score_entity
from mempalace.entity_registry import EntityRegistry
from mempalace.exporter import export_palace
from mempalace.general_extractor import _disambiguate, _is_code_line, extract_memories
from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.layers import Layer1, Layer2
from mempalace.miner import GitignoreMatcher, detect_room, is_force_included, process_file, scan_project
from mempalace.normalize import _try_claude_ai_json
from mempalace.onboarding import _generate_wing_config, bootstrap_from_entities, run_onboarding
from mempalace.palace_graph import build_graph
from mempalace.query_sanitizer import sanitize_query
from mempalace.room_detector_local import detect_rooms_local
from mempalace.spellcheck import _get_speller, _get_system_words
from mempalace.split_mega_files import main as split_mega_main


def test_write_project_entities_returns_none_for_empty_payload(tmp_path):
    assert _write_project_entities(tmp_path, {"people": [], "projects": []}) is None


def test_cmd_migrate_uses_default_palace_from_config():
    args = argparse.Namespace(palace=None, dry_run=True)
    with patch("mempalace.cli.MempalaceConfig") as mock_config, patch(
        "mempalace.migrate.migrate"
    ) as mock_migrate:
        mock_config.return_value.palace_path = "/fake/palace"
        cmd_migrate(args)

    mock_migrate.assert_called_once_with(palace_path="/fake/palace", dry_run=True)


def test_cmd_repair_delegates_to_repair_module():
    args = argparse.Namespace(palace="/tmp/palace", signals=False)
    with patch("mempalace.repair.rebuild_index") as mock_rebuild:
        cmd_repair(args)
    mock_rebuild.assert_called_once_with(palace_path="/tmp/palace")


def test_cmd_compress_auto_discovers_entities_json(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "entities.json").write_text("{}", encoding="utf-8")

    col = MagicMock()
    col.get.return_value = {
        "documents": ["Decision log about auth migration."],
        "metadatas": [{"wing": "project", "room": "backend"}],
        "ids": ["drawer_1"],
    }
    client = MagicMock()
    client.get_collection.return_value = col
    dialect = MagicMock()
    dialect.compress.return_value = "AAAK"
    dialect.compression_stats.return_value = {
        "original_chars": 32,
        "summary_chars": 4,
        "original_tokens_est": 8,
        "summary_tokens_est": 1,
        "size_ratio": 8.0,
    }

    args = argparse.Namespace(palace=str(tmp_path / "palace"), wing=None, dry_run=True, config=None)
    with patch("chromadb.PersistentClient", return_value=client), patch(
        "mempalace.dialect.Dialect.from_config", return_value=dialect
    ) as mock_from_config:
        cmd_compress(args)

    mock_from_config.assert_called_once_with("entities.json")


def test_cmd_compress_breaks_cleanly_if_later_batch_read_fails(tmp_path):
    docs = ["doc"] * 500
    metas = [{"wing": "project", "room": "backend"}] * 500
    ids = [f"drawer_{i}" for i in range(500)]

    col = MagicMock()
    col.get.side_effect = [
        {"documents": docs, "metadatas": metas, "ids": ids},
        RuntimeError("read failed"),
    ]
    comp_col = MagicMock()
    client = MagicMock()
    client.get_collection.return_value = col
    client.get_or_create_collection.return_value = comp_col
    dialect = MagicMock()
    dialect.compress.return_value = "AAAK"
    dialect.compression_stats.return_value = {
        "original_chars": 30,
        "summary_chars": 5,
        "original_tokens_est": 8,
        "summary_tokens_est": 1,
        "size_ratio": 6.0,
    }

    args = argparse.Namespace(palace=str(tmp_path / "palace"), wing=None, dry_run=False, config=None)
    with patch("chromadb.PersistentClient", return_value=client), patch(
        "mempalace.dialect.Dialect", return_value=dialect
    ):
        cmd_compress(args)

    assert comp_col.upsert.call_count == 500


def test_cmd_compress_exits_when_store_fails(tmp_path):
    col = MagicMock()
    col.get.return_value = {
        "documents": ["doc"],
        "metadatas": [{"wing": "project", "room": "backend"}],
        "ids": ["drawer_1"],
    }
    comp_col = MagicMock()
    comp_col.upsert.side_effect = RuntimeError("store failed")
    client = MagicMock()
    client.get_collection.return_value = col
    client.get_or_create_collection.return_value = comp_col
    dialect = MagicMock()
    dialect.compress.return_value = "AAAK"
    dialect.compression_stats.return_value = {
        "original_chars": 30,
        "summary_chars": 5,
        "original_tokens_est": 8,
        "summary_tokens_est": 1,
        "size_ratio": 6.0,
    }

    args = argparse.Namespace(palace=str(tmp_path / "palace"), wing=None, dry_run=False, config=None)
    with patch("chromadb.PersistentClient", return_value=client), patch(
        "mempalace.dialect.Dialect", return_value=dialect
    ):
        with pytest.raises(SystemExit) as exc:
            cmd_compress(args)

    assert exc.value.code == 1


def test_cmd_compress_exits_if_first_batch_read_fails(tmp_path):
    col = MagicMock()
    col.get.side_effect = RuntimeError("read failed")
    client = MagicMock()
    client.get_collection.return_value = col

    args = argparse.Namespace(palace=str(tmp_path / "palace"), wing=None, dry_run=False, config=None)
    with patch("chromadb.PersistentClient", return_value=client):
        with pytest.raises(SystemExit) as exc:
            cmd_compress(args)

    assert exc.value.code == 1


@pytest.mark.parametrize(
    ("people", "projects", "expected"),
    [
        ([{"name": "Alice", "context": "personal"}], [], "personal"),
        ([{"name": "Alice", "context": "work"}], [], "work"),
        (
            [{"name": "Alice", "context": "personal"}, {"name": "Bob", "context": "work"}],
            [],
            "combo",
        ),
        ([], ["MemPalace"], "work"),
    ],
)
def test_bootstrap_from_entities_infers_mode(people, projects, expected, tmp_path):
    result = bootstrap_from_entities(
        people,
        projects,
        config_dir=tmp_path / expected,
        install_default_agents=False,
    )
    assert result["mode"] == expected


def test_generate_wing_config_skips_blank_people_and_projects(tmp_path):
    path = _generate_wing_config(
        [{"name": "   ", "relationship": "friend", "context": "personal"}],
        ["", "MemPalace"],
        ["projects"],
        "work",
        config_dir=tmp_path,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "wing_mempalace" in payload["wings"]
    assert "wing_" not in payload["wings"]


def test_run_onboarding_auto_detect_adds_candidate_in_combo_mode(tmp_path):
    candidate = {"name": "Jordan", "confidence": 0.9, "signals": ["dialogue marker"]}

    with (
        patch("mempalace.onboarding._ask_mode", return_value="combo"),
        patch(
            "mempalace.onboarding._ask_people",
            return_value=([{"name": "Alice", "relationship": "friend", "context": "personal"}], {}),
        ),
        patch("mempalace.onboarding._ask_projects", return_value=[]),
        patch("mempalace.onboarding._ask_wings", return_value=["family", "work"]),
        patch("mempalace.onboarding._yn", side_effect=[True, True]),
        patch("mempalace.onboarding._ask", return_value=str(tmp_path)),
        patch("mempalace.onboarding._auto_detect", return_value=[candidate]),
        patch("mempalace.onboarding.bootstrap_from_entities", return_value={"created_agents": []}),
        patch("builtins.input", side_effect=["p", "coworker", "w"]),
    ):
        registry = run_onboarding(directory=str(tmp_path), config_dir=tmp_path)

    assert "Jordan" in registry.people


def test_repair_and_dedup_get_palace_path_fall_back_when_config_import_fails():
    broken_config = types.ModuleType("mempalace.config")

    with patch.dict(sys.modules, {"mempalace.config": broken_config}):
        assert ".mempalace" in repair._get_palace_path()
        assert ".mempalace" in dedup._get_palace_path()


def test_dedup_get_palace_path_from_config_and_empty_batch_break():
    with patch("mempalace.config.MempalaceConfig") as mock_config:
        mock_config.return_value.palace_path = "/configured/palace"
        assert dedup._get_palace_path() == "/configured/palace"

    col = MagicMock()
    col.count.return_value = 10
    col.get.return_value = {"ids": [], "metadatas": []}
    assert dedup.get_source_groups(col) == {}


def test_paginate_ids_breaks_when_both_pagination_paths_fail():
    col = MagicMock()
    col.get.side_effect = [RuntimeError("offset"), RuntimeError("fallback")]
    assert repair._paginate_ids(col) == []


def test_scan_palace_marks_missing_batch_ids_as_bad(tmp_path):
    col = MagicMock()
    col.count.return_value = 2

    def fake_get(**kwargs):
        if "ids" not in kwargs:
            return {"ids": ["good", "missing"]}
        return {"ids": ["good"], "documents": ["doc"]}

    col.get.side_effect = fake_get
    client = MagicMock()
    client.get_collection.return_value = col

    with patch("mempalace.repair.chromadb.PersistentClient", return_value=client):
        good, bad = repair.scan_palace(palace_path=str(tmp_path))

    assert "good" in good
    assert "missing" in bad


def test_prune_corrupt_counts_individual_delete_failures(tmp_path):
    bad_file = tmp_path / "corrupt_ids.txt"
    bad_file.write_text("bad1\nbad2\n", encoding="utf-8")

    col = MagicMock()
    col.count.side_effect = [10, 10]
    col.delete.side_effect = [RuntimeError("batch"), RuntimeError("one"), RuntimeError("two")]
    client = MagicMock()
    client.get_collection.return_value = col

    with patch("mempalace.repair.chromadb.PersistentClient", return_value=client):
        repair.prune_corrupt(palace_path=str(tmp_path), confirm=True)

    assert col.delete.call_count == 3


def test_repair_marks_single_id_as_bad_when_fallback_fetch_returns_empty(tmp_path):
    col = MagicMock()
    col.count.return_value = 1

    def fake_get(**kwargs):
        if "ids" not in kwargs:
            return {"ids": ["missing"]}
        raise RuntimeError("batch failed")

    col.get.side_effect = [
        {"ids": ["missing"]},
        RuntimeError("batch failed"),
        {"ids": []},
    ]
    client = MagicMock()
    client.get_collection.return_value = col

    with patch("mempalace.repair.chromadb.PersistentClient", return_value=client):
        good, bad = repair.scan_palace(palace_path=str(tmp_path))

    assert good == set()
    assert bad == {"missing"}


def test_rebuild_index_breaks_on_empty_batch_and_still_recreates_collection(tmp_path):
    palace_path = tmp_path / "palace"
    palace_path.mkdir()

    col = MagicMock()
    col.count.return_value = 2
    col.get.return_value = {"ids": [], "documents": [], "metadatas": []}
    client = MagicMock()
    client.get_collection.return_value = col

    with patch("mempalace.repair.chromadb.PersistentClient", return_value=client):
        repair.rebuild_index(palace_path=str(palace_path))

    client.delete_collection.assert_called_once_with("mempalace_drawers")


def test_chunk_exchanges_skips_non_prompt_preamble():
    chunks = chunk_exchanges("metadata line\n> User question\nAssistant answer\n")
    assert len(chunks) == 1


def test_chunk_exchanges_returns_empty_for_non_dialogue_input():
    assert chunk_exchanges("metadata only\nstill metadata\n") == []


def test_chunk_by_exchange_advances_past_non_quote_lines():
    chunks = _chunk_by_exchange(["metadata", "> User question", "Assistant answer"])
    assert chunks[0]["content"].startswith("> User question")


def test_scan_convos_skips_oversized_files(monkeypatch, tmp_path):
    convo = tmp_path / "chat.txt"
    convo.write_text("hello", encoding="utf-8")

    original_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        if self == convo:
            return SimpleNamespace(st_size=MAX_FILE_SIZE + 1, st_mode=0)
        return original_stat(self, *args, **kwargs)

    with patch.object(Path, "stat", fake_stat):
        files = scan_convos(str(tmp_path))

    assert files == []


def test_mine_convos_dry_run_exchange_mode_tracks_room_counts(tmp_path, capsys):
    convo = tmp_path / "chat.txt"
    convo.write_text("placeholder", encoding="utf-8")

    with (
        patch("mempalace.convo_miner.scan_convos", return_value=[convo]),
        patch(
            "mempalace.convo_miner.normalize",
            return_value="> User asks a longer question about auth migration.\n"
            + ("Assistant replies with enough detail to exceed the minimum size. " * 2),
        ),
        patch(
            "mempalace.convo_miner.chunk_exchanges",
            return_value=[{"content": "chunk", "chunk_index": 0}],
        ),
        patch("mempalace.convo_miner.detect_convo_room", return_value="technical"),
    ):
        mine_convos(str(tmp_path), str(tmp_path / "palace"), dry_run=True, extract_mode="exchange")

    assert "[DRY RUN]" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("memory_type", "text", "scores", "expected"),
    [
        (
            "problem",
            "We fixed it and I feel happy about the outcome.",
            {"emotional": 1},
            "emotional",
        ),
        (
            "problem",
            "This felt great and we shipped the fix successfully.",
            {"milestone": 1},
            "milestone",
        ),
    ],
)
def test_general_extractor_disambiguates_positive_problem_cases(
    memory_type, text, scores, expected
):
    assert _disambiguate(memory_type, text, scores) == expected


def test_general_extractor_flags_low_alpha_lines_as_code():
    assert _is_code_line("1234 //// ==== 5678") is True


def test_extract_memories_hits_medium_and_large_length_bonuses():
    medium = "We decided to migrate the auth service next sprint. " + ("A" * 220)
    large = "We decided to migrate the billing service after the outage. " + ("B" * 520)
    memories = extract_memories(f"{medium}\n\n{large}", min_confidence=0.1)
    assert len(memories) == 2


def test_general_extractor_positive_problem_can_become_emotional_without_resolution():
    result = _disambiguate("problem", "I feel happy and relieved now.", {"emotional": 1})
    assert result == "emotional"


def test_general_extractor_positive_problem_can_become_milestone_without_resolution():
    result = _disambiguate("problem", "I feel happy about the change.", {"milestone": 1})
    assert result == "milestone"


def test_entity_detector_covers_versioned_projects_and_addressed_people():
    text = "MemPalace-2.0 shipped today. Alice, review the patch and she merged it."
    scores = score_entity("MemPalace", text, text.splitlines())
    assert any("versioned/hyphenated" in signal for signal in scores["project_signals"])

    classified = classify_entity(
        "Alice",
        3,
        {
            "person_score": 6,
            "project_score": 0,
            "person_signals": ["addressed directly (1x)", "action verb nearby (1x)"],
            "project_signals": [],
        },
    )
    assert classified["type"] == "person"


def test_entity_registry_skips_known_entities_and_marks_common_words_ambiguous(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[{"name": "Alice", "relationship": "friend", "context": "personal"}],
        projects=[],
    )

    with (
        patch("mempalace.entity_detector.extract_candidates", return_value={"Alice": 3, "Grace": 4}),
        patch(
            "mempalace.entity_detector.score_entity",
            return_value={
                "person_score": 8,
                "project_score": 0,
                "person_signals": ["dialogue marker", "action verb nearby"],
                "project_signals": [],
            },
        ),
        patch(
            "mempalace.entity_detector.classify_entity",
            return_value={"name": "Grace", "type": "person", "confidence": 0.9},
        ),
    ):
        learned = registry.learn_from_text("Alice and Grace talked.", min_confidence=0.5)

    assert [entry["name"] for entry in learned] == ["Grace"]
    assert "grace" in registry._data["ambiguous_flags"]


def test_confirm_entities_edit_mode_reclassifies_and_removes_entries():
    detected = {
        "people": [{"name": "Alice", "confidence": 0.9, "signals": ["dialogue marker"]}],
        "projects": [{"name": "MemPalace", "confidence": 0.9, "signals": ["project verb"]}],
        "uncertain": [{"name": "Jordan", "confidence": 0.5, "signals": ["mixed"]}],
    }

    with patch("builtins.input", side_effect=["edit", "r", "1", "1", "n"]):
        confirmed = confirm_entities(detected, yes=False)

    assert confirmed["people"] == []
    assert confirmed["projects"] == ["Jordan"]


def test_layers_cover_bad_importance_and_room_only_empty_label(monkeypatch):
    col = MagicMock()
    col.get.side_effect = [
        {
            "documents": ["Important memory about auth migration."],
            "metadatas": [{"room": "backend", "importance": "oops", "source_file": "src/app.py"}],
        },
        RuntimeError("db broke"),
    ]
    monkeypatch.setattr("mempalace.layers._get_collection", lambda palace_path, create=False: col)

    text = Layer1(palace_path="/tmp/palace").generate()
    assert "Important memory" in text

    empty_col = MagicMock()
    empty_col.get.return_value = {"documents": [], "metadatas": []}
    monkeypatch.setattr("mempalace.layers._get_collection", lambda palace_path, create=False: empty_col)

    result = Layer2(palace_path="/tmp/palace").retrieve(room="backend")
    assert result == "No drawers found for room=backend."


def test_layer1_breaks_after_second_batch_exception(monkeypatch):
    docs = ["auth memory"] * 500
    metas = [{"room": "backend", "source_file": "src/app.py"}] * 500
    col = MagicMock()
    col.get.side_effect = [
        {"documents": docs, "metadatas": metas},
        RuntimeError("db broke"),
    ]
    monkeypatch.setattr("mempalace.layers._get_collection", lambda palace_path, create=False: col)

    text = Layer1(palace_path="/tmp/palace").generate()
    assert "auth memory" in text


def test_knowledge_graph_incoming_as_of_filters_dates(tmp_path):
    graph = KnowledgeGraph(db_path=tmp_path / "kg.sqlite3")
    try:
        graph.add_triple("Alice", "works_at", "OldCo", valid_from="2020-01-01", valid_to="2021-01-01")
        graph.add_triple("Bob", "reports_to", "Alice", valid_from="2020-06-01")
        facts = graph.query_entity("Alice", as_of="2020-07-01", direction="incoming")
    finally:
        graph.close()

    assert facts[0]["subject"] == "Bob"


def test_dialect_extra_branches(tmp_path):
    dialect = Dialect(entities={"alice": "ALC"})
    config_path = tmp_path / "dialect.json"
    dialect.save_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["entities"] == {"alice": "ALC"}
    assert dialect.encode_entity("Alice") == "ALC"

    zettel = {
        "id": "zettel-1",
        "title": 'note - "The future feels real"',
        "summary": "",
        "people": [],
        "topics": [],
        "emotions": [],
        "date_context": "2026-01-01",
    }
    assert dialect.extract_key_quote(
        {
            **zettel,
            "summary": 'A note that says: "The future feels real."',
        }
    ) == '"The future feels real"'

    encoded = dialect.encode_file(
        {
            "source_file": "1-memory.txt",
            "zettels": [{"id": "z-1", "date_context": "2026-01-01", "people": []}],
        }
    )
    assert "|???|" in encoded

    input_dir = tmp_path / "compressed"
    input_dir.mkdir()
    (input_dir / "one.json").write_text(
        json.dumps(
            {
                "source_file": "1-memory.txt",
                "zettels": [
                    {
                        "id": "z-1",
                        "date_context": "2026-01-01",
                        "title": "plain title",
                        "people": [],
                        "topics": ["auth", "db"],
                        "summary": "A remembered decision about auth.",
                        "emotions": [],
                        "emotional_weight": 1.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    layer1 = dialect.generate_layer1(input_dir)
    assert "???" in layer1
    assert "auth_db" in layer1

    with (
        patch("mempalace.dialect.re.findall", side_effect=[["The future feels real"], []]),
        patch("mempalace.dialect.re.finditer", return_value=[]),
    ):
        assert (
            dialect.extract_key_quote(
                {
                    "title": "note",
                    "summary": "unused",
                    "people": [],
                    "topics": [],
                    "emotions": [],
                }
            )
            == "The future feels real"
        )


def test_misc_small_branch_helpers(monkeypatch, tmp_path):
    agent_dir = tmp_path / "agents"
    agent_dir.mkdir()
    (agent_dir / "broken.json").write_text("[]", encoding="utf-8")
    assert list_agents(config_dir=tmp_path)["errors"]

    fake_col = MagicMock()
    fake_col.count.return_value = 0
    monkeypatch.setattr("mempalace.palace_graph._get_collection", lambda config=None: fake_col)
    assert build_graph() == ({}, [])

    raw = ("Status dump without newline. " * 40) + "Why did we switch databases? trailing context"
    sanitized = sanitize_query(raw)
    assert sanitized["method"] in {"question_extraction", "tail_sentence"}

    project = tmp_path / "project"
    project.mkdir()
    with (
        patch("mempalace.miner.scan_project", return_value=[]),
        patch("mempalace.room_detector_local.detect_rooms_from_folders", return_value=[]),
        patch("mempalace.room_detector_local.detect_rooms_from_files", return_value=[]),
        patch("mempalace.room_detector_local.get_user_approval") as mock_approval,
        patch("mempalace.room_detector_local.save_config") as mock_save,
    ):
        detect_rooms_local(str(project), yes=True)
    mock_approval.assert_not_called()
    mock_save.assert_called_once()

    export_col = MagicMock()
    export_col.count.return_value = 2
    export_col.get.side_effect = [
        {"ids": ["drawer_1"], "documents": ["doc"], "metadatas": [{"wing": "w", "room": "r"}]},
        {"ids": [], "documents": [], "metadatas": []},
    ]
    with patch("mempalace.exporter.get_collection", return_value=export_col):
        stats = export_palace("/tmp/palace", str(tmp_path / "export"))
    assert stats["drawers"] == 1

    assert _try_claude_ai_json({"chat_messages": [{"role": "user", "content": "hello"}]}) is None

    privacy_export = [{"chat_messages": [{"role": "user", "content": "hello"}]}]
    assert _try_claude_ai_json(privacy_export) is None

    with patch("mempalace.query_sanitizer._SENTENCE_SPLIT", re.compile(r"[.!\n]+")):
        fallback = sanitize_query(
            ("Status line. " * 40) + "Why did we switch databases? trailing context"
        )
    assert fallback["method"] == "question_extraction"


def test_spellcheck_helpers_cover_available_speller_and_system_dict(monkeypatch, tmp_path):
    fake_autocorrect = types.ModuleType("autocorrect")

    class FakeSpeller:
        def __init__(self, lang):
            self.lang = lang

    fake_autocorrect.Speller = FakeSpeller
    monkeypatch.setitem(sys.modules, "autocorrect", fake_autocorrect)
    monkeypatch.setattr("mempalace.spellcheck._speller", None)
    monkeypatch.setattr("mempalace.spellcheck._autocorrect_available", None)
    speller = _get_speller()
    assert isinstance(speller, FakeSpeller)

    dict_path = tmp_path / "words"
    dict_path.write_text("Alpha\nBeta\n", encoding="utf-8")
    monkeypatch.setattr("mempalace.spellcheck._system_words", None)
    monkeypatch.setattr("mempalace.spellcheck._SYSTEM_DICT", dict_path)
    assert _get_system_words() == {"alpha", "beta"}


def test_split_mega_main_skips_oversized_inputs(monkeypatch, tmp_path, capsys):
    giant = tmp_path / "huge.txt"
    giant.write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["split_mega_files", "--source", str(tmp_path)])
    original_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        if self == giant:
            return SimpleNamespace(st_size=600 * 1024 * 1024, st_mode=0)
        return original_stat(self, *args, **kwargs)

    with patch.object(Path, "stat", fake_stat):
        split_mega_main()

    assert "SKIP: huge.txt exceeds 500 MB limit" in capsys.readouterr().out


def test_miner_branch_edges(tmp_path, monkeypatch):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("\n# comment\n/\n", encoding="utf-8")
    assert GitignoreMatcher.from_dir(tmp_path) is None

    matcher = GitignoreMatcher(tmp_path, [{"pattern": "tmp", "anchored": False, "dir_only": False, "negated": False}])
    assert matcher.matches(tmp_path) is None
    assert matcher.matches(tmp_path.parent / "outside.txt", is_dir=False) is None
    inner = tmp_path / "inner.txt"
    inner.write_text("content", encoding="utf-8")
    assert matcher.matches(inner) in {None, False}

    dir_matcher = GitignoreMatcher(
        tmp_path,
        [{"pattern": "src/build", "anchored": True, "dir_only": True, "negated": False}],
    )
    assert dir_matcher._rule_matches(dir_matcher.rules[0], "src/build", is_dir=True) is True
    assert dir_matcher._match_from_root(["src", "cache"], ["**", "cache"]) is True
    assert is_force_included(tmp_path.parent / "outside.txt", tmp_path, {"docs"}) is False
    assert is_force_included(tmp_path, tmp_path, {"docs"}) is False

    project = tmp_path / "project"
    project.mkdir()
    rooms = [{"name": "backend", "keywords": ["server"]}]
    file_path = project / "backend-notes.txt"
    file_path.write_text("short content that is still long enough to route", encoding="utf-8")
    assert detect_room(file_path, file_path.read_text(), rooms, project) == "backend"

    short = project / "tiny.txt"
    short.write_text("tiny", encoding="utf-8")
    assert process_file(short, project, MagicMock(), "wing", rooms, "agent", False) == (0, None)

    target = project / "app.py"
    target.write_text("print('hello world')\n" * 20, encoding="utf-8")
    symlink = project / "link.py"
    symlink.symlink_to(target)
    broken = project / "broken.py"
    broken.write_text("print('x')", encoding="utf-8")

    original_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        if self == broken and kwargs.get("follow_symlinks", True) is not False:
            raise OSError("stat failed")
        if self == target and kwargs.get("follow_symlinks", True) is not False:
            return SimpleNamespace(st_size=20 * 1024 * 1024, st_mode=0)
        return original_stat(self, *args, **kwargs)

    with patch.object(Path, "stat", fake_stat):
        files = scan_project(str(project), respect_gitignore=False)

    assert target not in files
    assert symlink not in files

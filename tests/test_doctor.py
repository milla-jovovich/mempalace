"""Unit tests for mempalace.doctor."""

import json
import sqlite3
from pathlib import Path

import pytest

from mempalace.doctor import (
    FAIL,
    OK,
    WARN,
    check_aaak_config,
    check_chromadb,
    check_duplicate_drawers,
    check_identity,
    check_knowledge_graph,
    check_orphan_drawers,
    format_report,
    run_doctor,
)


# ── check_orphan_drawers ──────────────────────────────────────────────────


def test_orphan_drawers_all_complete():
    metas = [
        {"wing": "wing_a", "room": "room_x"},
        {"wing": "wing_b", "room": "room_y"},
    ]
    result = check_orphan_drawers(metas)
    assert result.status == OK


def test_orphan_drawers_detects_missing_fields():
    metas = [
        {"wing": "wing_a", "room": "room_x"},
        {"wing": "wing_b"},  # missing room
        {"room": "room_z"},  # missing wing
        {},  # missing both
    ]
    result = check_orphan_drawers(metas)
    assert result.status == WARN
    assert "3" in result.message
    assert len(result.details) == 3


def test_orphan_drawers_empty_input():
    assert check_orphan_drawers([]).status == OK


# ── check_duplicate_drawers ────────────────────────────────────────────────


def test_duplicate_drawers_none():
    docs = ["alpha", "beta", "gamma"]
    ids = ["1", "2", "3"]
    assert check_duplicate_drawers(docs, ids).status == OK


def test_duplicate_drawers_detected():
    docs = ["alpha", "beta", "alpha", "gamma", "beta"]
    ids = ["1", "2", "3", "4", "5"]
    result = check_duplicate_drawers(docs, ids)
    assert result.status == WARN
    assert "2" in result.message


def test_duplicate_drawers_ignores_blank_and_none():
    docs = ["", "  ", None, "real"]
    ids = ["1", "2", "3", "4"]
    assert check_duplicate_drawers(docs, ids).status == OK


# ── check_knowledge_graph ──────────────────────────────────────────────────


def _make_kg(tmp_path: Path, triples: list[tuple], entities: list[str]) -> Path:
    db = tmp_path / "kg.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE entities (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE triples (
            id TEXT PRIMARY KEY,
            subject TEXT,
            predicate TEXT,
            object TEXT
        );
        """
    )
    for ent in entities:
        conn.execute("INSERT INTO entities (id, name) VALUES (?, ?)", (ent, ent))
    for tid, sub, pred, obj in triples:
        conn.execute(
            "INSERT INTO triples (id, subject, predicate, object) VALUES (?, ?, ?, ?)",
            (tid, sub, pred, obj),
        )
    conn.commit()
    conn.close()
    return db


def test_knowledge_graph_missing_db_warns(tmp_path):
    result = check_knowledge_graph(str(tmp_path / "absent.sqlite3"))
    assert result.status == WARN


def test_knowledge_graph_clean(tmp_path):
    db = _make_kg(
        tmp_path,
        triples=[("t1", "kai", "works_on", "orion")],
        entities=["kai", "orion"],
    )
    result = check_knowledge_graph(str(db))
    assert result.status == OK
    assert "1 triple" in result.message


def test_knowledge_graph_dangling_reference(tmp_path):
    db = _make_kg(
        tmp_path,
        triples=[
            ("t1", "kai", "works_on", "orion"),
            ("t2", "ghost", "knows", "kai"),  # ghost not in entities
        ],
        entities=["kai", "orion"],
    )
    result = check_knowledge_graph(str(db))
    assert result.status == FAIL
    assert "1 dangling" in result.message


# ── check_identity ─────────────────────────────────────────────────────────


def test_identity_missing(tmp_path):
    assert check_identity(str(tmp_path / "identity.txt")).status == WARN


def test_identity_empty(tmp_path):
    p = tmp_path / "identity.txt"
    p.write_text("")
    assert check_identity(str(p)).status == WARN


def test_identity_present(tmp_path):
    p = tmp_path / "identity.txt"
    p.write_text("I am a helpful assistant.")
    assert check_identity(str(p)).status == OK


# ── check_aaak_config ──────────────────────────────────────────────────────


def test_aaak_config_missing(tmp_path):
    assert check_aaak_config(str(tmp_path / "config.json")).status == WARN


def test_aaak_config_invalid_json(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{not json")
    assert check_aaak_config(str(p)).status == FAIL


def test_aaak_config_missing_keys(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"palace_path": "/tmp/p"}))
    result = check_aaak_config(str(p))
    assert result.status == FAIL
    assert "collection_name" in result.message


def test_aaak_config_valid(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"palace_path": "/tmp/p", "collection_name": "drawers"}))
    assert check_aaak_config(str(p)).status == OK


# ── check_chromadb ─────────────────────────────────────────────────────────


def test_chromadb_missing_palace(tmp_path):
    result = check_chromadb(str(tmp_path / "no_palace"))
    assert result.status == FAIL


# ── run_doctor end-to-end with injected loader ─────────────────────────────


def test_run_doctor_healthy(tmp_path):
    palace = tmp_path / "palace"
    palace.mkdir()
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps({"palace_path": str(palace), "collection_name": "drawers"})
    )
    (config_dir / "identity.txt").write_text("I am MemPalace.")
    _make_kg(
        config_dir,
        triples=[("t1", "kai", "works_on", "orion")],
        entities=["kai", "orion"],
    )
    # _make_kg writes to kg.sqlite3 — rename to expected filename
    (config_dir / "kg.sqlite3").rename(config_dir / "knowledge_graph.sqlite3")

    def loader(_path, _coll):
        docs = ["one", "two"]
        metas = [
            {"wing": "wing_a", "room": "room_x"},
            {"wing": "wing_a", "room": "room_y"},
        ]
        ids = ["d1", "d2"]
        return docs, metas, ids

    report = run_doctor(
        palace_path=str(palace),
        config_dir=str(config_dir),
        chroma_loader=loader,
    )
    assert report.healthy
    assert all(r.status == OK for r in report.results)


def test_run_doctor_surfaces_failures(tmp_path):
    palace = tmp_path / "palace"
    palace.mkdir()
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    # Invalid config to trigger FAIL
    (config_dir / "config.json").write_text("{broken")

    def loader(_path, _coll):
        return ["dup", "dup"], [{"wing": "w"}, {"wing": "w", "room": "r"}], ["a", "b"]

    report = run_doctor(
        palace_path=str(palace),
        config_dir=str(config_dir),
        chroma_loader=loader,
    )
    assert not report.healthy
    statuses = {r.name: r.status for r in report.results}
    assert statuses["AAAK config"] == FAIL
    assert statuses["Orphan drawers"] == WARN
    assert statuses["Duplicate drawers"] == WARN


# ── format_report ──────────────────────────────────────────────────────────


def test_format_report_no_color_contains_marks(tmp_path):
    palace = tmp_path / "palace"
    palace.mkdir()
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()

    def loader(_p, _c):
        return [], [], []

    report = run_doctor(
        palace_path=str(palace),
        config_dir=str(config_dir),
        chroma_loader=loader,
    )
    text = format_report(report, use_color=False)
    assert "MemPalace Doctor" in text
    assert "ChromaDB connection" in text
    # No ANSI escape codes when color disabled
    assert "\033[" not in text


def test_format_report_with_color():
    from mempalace.doctor import CheckResult, DoctorReport, GREEN

    rep = DoctorReport()
    rep.add(CheckResult("dummy", OK, "fine"))
    text = format_report(rep, use_color=True)
    assert GREEN in text


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])

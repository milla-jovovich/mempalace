"""Subprocess-level smoke tests for public CLI entry points."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_cli_init_yes_bootstraps_promised_files(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    (project / "docs").mkdir(parents=True)
    (project / "src").mkdir(parents=True)
    (project / "README.md").write_text(
        "# Demo\nAlice and MemPalace are planning Orion.\n", encoding="utf-8"
    )
    (project / "src" / "notes.txt").write_text(
        "Bob discussed architecture for Orion.\n", encoding="utf-8"
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)

    result = subprocess.run(
        [sys.executable, "-m", "mempalace", "init", "--yes", str(project)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    mempalace_home = home / ".mempalace"
    assert "Wing config saved" in result.stdout
    assert (mempalace_home / "aaak_entities.md").exists()
    assert (mempalace_home / "critical_facts.md").exists()
    assert (mempalace_home / "wing_config.json").exists()
    assert (mempalace_home / "identity.txt").exists()
    assert sorted(path.name for path in (mempalace_home / "agents").glob("*.json")) == [
        "architect.json",
        "ops.json",
        "reviewer.json",
    ]


def test_fact_checker_module_cli_outputs_json(tmp_path):
    from mempalace.knowledge_graph import KnowledgeGraph

    db_path = tmp_path / "kg.sqlite3"
    kg = KnowledgeGraph(db_path=str(db_path))
    kg.add_triple("Alice", "works_at", "NewCo")
    kg.close()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mempalace.fact_checker",
            "Alice",
            "works_at",
            "OldCo",
            "--kg",
            str(db_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["status"] == "conflict"
    assert payload["conflicts"][0]["object"] == "NewCo"

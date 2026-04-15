import json

import pytest

from mempalace.project_tracker import ProjectTracker, ProjectTrackerError


def test_register_project_detects_mempalace_metadata(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "mempalace.yaml").write_text(
        "wing: sample-wing\nrooms:\n  - name: docs\n  - name: code\n",
        encoding="utf-8",
    )
    (project_dir / "entities.json").write_text(
        json.dumps({"people": ["Alice"], "projects": ["MemPalace"]}),
        encoding="utf-8",
    )

    tracker = ProjectTracker(db_path=str(tmp_path / "tracker.sqlite3"))
    result = tracker.register_project(str(project_dir))

    assert result["created"] is True
    assert result["wing"] == "sample-wing"
    assert result["metadata"]["has_mempalace_yaml"] is True
    assert result["metadata"]["room_count"] == 2
    assert result["metadata"]["entity_people_count"] == 1
    assert result["metadata"]["entity_project_count"] == 1


def test_register_project_updates_existing_record(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tracker = ProjectTracker(db_path=str(tmp_path / "tracker.sqlite3"))

    first = tracker.register_project(str(project_dir), name="First", wing="wing-a")
    second = tracker.register_project(
        str(project_dir),
        name="Second",
        wing="wing-b",
        metadata={"source": "test"},
    )

    assert first["project_id"] == second["project_id"]
    assert second["created"] is False
    assert second["name"] == "Second"
    assert second["wing"] == "wing-b"
    assert second["metadata"]["source"] == "test"


def test_task_lifecycle_logs_and_resume(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tracker = ProjectTracker(db_path=str(tmp_path / "tracker.sqlite3"))
    project = tracker.register_project(str(project_dir), wing="wing-x")

    task = tracker.start_task(
        project["project_id"],
        "Upgrade tracker",
        stage="planning",
        percent=10,
        summary="Tracker started",
    )
    task_id = task["task_id"]

    logged = tracker.log_event(
        task_id,
        "Collected current repo context",
        stage="analysis",
        percent=30,
        payload={"files": 3},
    )
    assert logged["event"]["kind"] == "log"
    assert logged["task"]["stage"] == "analysis"
    assert logged["task"]["percent"] == 30

    checkpoint = tracker.add_checkpoint(
        task_id,
        "Schema finalized",
        stage="design",
        state={"step": "schema"},
    )
    assert checkpoint["checkpoint"]["summary"] == "Schema finalized"

    updated = tracker.update_task(
        task_id,
        status="completed",
        percent=100,
        summary="Upgrade finished",
    )
    assert updated["status"] == "completed"
    assert updated["ended_at"] is not None

    resumed = tracker.resume_task(project_selector=project["project_id"])
    assert resumed["task"]["task_id"] == task_id
    assert resumed["latest_checkpoint"]["summary"] == "Schema finalized"
    assert any(event["kind"] == "task_started" for event in resumed["recent_events"])
    assert any(event["kind"] == "checkpoint" for event in resumed["recent_events"])
    assert resumed["thread"]["thread_id"] == task_id
    assert resumed["task"]["event_chain"][0]["event_hash"]
    assert resumed["task"]["event_chain"][-1]["chain_hash"]


def test_project_status_includes_task_counts(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tracker = ProjectTracker(db_path=str(tmp_path / "tracker.sqlite3"))
    project = tracker.register_project(str(project_dir))

    tracker.start_task(project["project_id"], "First task", status="queued")
    tracker.start_task(project["project_id"], "Second task", status="running")

    status = tracker.project_status(project["project_id"])
    counts = status["project"]["task_counts"]
    assert counts["queued"] == 1
    assert counts["running"] == 1
    assert status["project"]["latest_task"]["title"] == "Second task"


def test_tracker_rejects_missing_project_path(tmp_path):
    tracker = ProjectTracker(db_path=str(tmp_path / "tracker.sqlite3"))
    with pytest.raises(ProjectTrackerError):
        tracker.register_project(str(tmp_path / "missing"))

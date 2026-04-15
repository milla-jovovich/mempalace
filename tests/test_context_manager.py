from mempalace.context_manager import ContextManager
from mempalace.project_tracker import ProjectTracker


def test_context_pack_combines_thread_memory_and_diary(tmp_path, palace_path, seeded_collection):
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    tracker = ProjectTracker(db_path=str(tmp_path / "tracker.sqlite3"))
    project = tracker.register_project(str(project_dir), name="Demo Project", wing="project")
    task = tracker.start_task(
        project["project_id"],
        "Investigate auth flow",
        stage="planning",
        percent=10,
        summary="Task started",
    )
    task_id = task["task_id"]

    tracker.log_event(
        task_id,
        "Checked JWT room",
        stage="analysis",
        percent=50,
        payload={"files": 2},
    )
    tracker.add_checkpoint(
        task_id,
        "Saved current findings",
        stage="analysis",
        state={"cursor": "auth.py:10"},
    )

    seeded_collection.add(
        ids=["diary_codex_1"],
        documents=["Need to focus on auth regressions before changing token expiry."],
        metadatas=[
            {
                "wing": "wing_codex",
                "room": "diary",
                "topic": "work",
                "filed_at": "2026-04-15T10:00:00",
                "date": "2026-04-15",
            }
        ],
    )

    manager = ContextManager(palace_path=palace_path, tracker=tracker)
    result = manager.build_context_pack(
        query="JWT authentication",
        project_selector=project["project_id"],
        agent_name="Codex",
    )

    assert result["thread"]["thread_id"] == task_id
    assert result["task"]["latest_checkpoint"]["summary"] == "Saved current findings"
    assert result["search"]["results"]
    assert result["diary"]["entries"][0]["topic"] == "work"
    assert "THREAD SNAPSHOT" in result["prompt"]
    assert any(section["title"] == "RECENT EVENTS" and section["included"] for section in result["sections"])

    event_chain = result["task"]["event_chain"]
    assert event_chain[0]["sequence"] == 1
    assert event_chain[-1]["chain_hash"]


def test_context_pack_respects_budget(tmp_path, palace_path, seeded_collection):
    manager = ContextManager(palace_path=palace_path)

    result = manager.build_context_pack(
        query="JWT authentication",
        wing="project",
        room="backend",
        max_chars=1200,
    )

    assert len(result["prompt"]) <= 1200
    assert any(section["truncated"] for section in result["sections"])

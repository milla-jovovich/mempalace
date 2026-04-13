"""Direct tests for the specialist agent registry."""

import json

from mempalace.agents import ensure_default_agents, list_agents, write_agent


def test_ensure_default_agents_creates_scaffold(tmp_path):
    created = ensure_default_agents(config_dir=tmp_path)
    result = list_agents(config_dir=tmp_path)

    assert len(created) == 3
    assert result["count"] == 3
    assert {agent["name"] for agent in result["agents"]} == {"reviewer", "architect", "ops"}


def test_ensure_default_agents_preserves_existing_definition(tmp_path):
    custom = {
        "name": "reviewer",
        "focus": "Custom focus",
        "description": "Keep my edits.",
        "prompt_hint": "Do not overwrite.",
        "wing": "wing_custom_reviewer",
        "diary_room": "notes",
    }
    custom_path = write_agent(custom, config_dir=tmp_path)

    created = ensure_default_agents(config_dir=tmp_path)
    result = list_agents(config_dir=tmp_path)

    assert all(path.name != "reviewer.json" for path in created)
    reviewer = next(agent for agent in result["agents"] if agent["name"] == "reviewer")
    assert reviewer["wing"] == "wing_custom_reviewer"
    assert reviewer["diary_room"] == "notes"
    assert json.loads(custom_path.read_text(encoding="utf-8"))["focus"] == "Custom focus"


def test_list_agents_reports_malformed_files_without_losing_valid_ones(tmp_path):
    write_agent(
        {
            "name": "architect",
            "focus": "Design",
            "description": "Valid entry",
            "prompt_hint": "Use for tradeoffs",
        },
        config_dir=tmp_path,
    )
    bad_path = tmp_path / "agents" / "broken.json"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("{not json", encoding="utf-8")

    result = list_agents(config_dir=tmp_path)

    assert result["count"] == 1
    assert result["agents"][0]["name"] == "architect"
    assert len(result["errors"]) == 1
    assert result["errors"][0]["path"].endswith("broken.json")


def test_write_agent_normalizes_slug_and_defaults(tmp_path):
    path = write_agent(
        {
            "name": "Build Sheriff",
            "focus": "CI and release triage",
            "description": "Tracks flaky builds",
            "prompt_hint": "Use for pipelines",
        },
        config_dir=tmp_path,
    )
    result = list_agents(config_dir=tmp_path)

    assert path.name == "build_sheriff.json"
    agent = result["agents"][0]
    assert agent["slug"] == "build_sheriff"
    assert agent["wing"] == "wing_build_sheriff"
    assert agent["diary_room"] == "diary"

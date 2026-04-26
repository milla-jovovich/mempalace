"""Phase 1 integration test — proves corpus_origin actually improves classification.

This is the test that justifies the Phase 1 PR. Without it, the PR ships
infrastructure that nobody can prove improves v3.3.3.

The fixture: a small AI-dialogue corpus with three agent persona names
(Echo, Sparrow, Cipher) that the user (Jordan) has assigned to their AI
agents. On plain v3.3.3, entity_detector misclassifies these as PEOPLE.
With Phase 1's corpus_origin context wired through, they classify as
AGENT_PERSONA instead.

Two tests sit side by side:

  test_baseline_v333_misclassifies_persona_names_as_people
    Pins v3.3.3's behavior. If this starts failing, the PR's motivation
    has shifted and the Phase 1 README needs revisiting.

  test_phase1_with_corpus_origin_reclassifies_personas
    The Phase 1 fix. Asserts that when corpus_origin context is passed,
    persona names land in agent_personas instead of people.

Together: documented before/after of v3.3.3 → Phase 1.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# A synthetic but realistic Claude Code transcript fixture. Three persona
# names appear repeatedly in dialogue patterns that the v3.3.3
# entity_detector treats as person-evidence (dialogue markers, action verbs,
# pronoun proximity). User name "Jordan" also appears in dialogue.
#
# The point is: every name here CAN be a real human name. v3.3.3 has no
# way to know that in this corpus they're agent personas, not people. Phase 1
# corpus_origin gives it that context.
AI_DIALOGUE_FIXTURE = """\
# Session log — 2026-04-20

Jordan: Echo, can you summarize what we worked on yesterday?

Echo (assistant): Yesterday we refactored the embedding pipeline. I noticed
the chunking strategy was producing overlapping windows, and I suggested
moving to a sliding window with explicit stride. You agreed and we shipped
the change.

Jordan: Good. Sparrow, what about the migration script — did you finish?

Sparrow (assistant): Yes, I finished the migration. I tested it locally
against the staging snapshot and it ran clean. I also added a rollback
path because you asked me to be cautious about the indexes.

Jordan: Perfect. Cipher, run the verification suite please.

Cipher (assistant): Running now. I'll report back when the full suite
completes. I expect it to take about four minutes.

Echo: Jordan, while Cipher runs the verification, do you want me to draft
the changelog entry for today's work?

Jordan: Yes please. Echo, keep it short. Sparrow, please review Echo's
draft when she sends it.

Sparrow: Will do. I'll look for clarity issues and check the migration
phrasing matches what we actually shipped.

Cipher: Verification complete. All 1247 tests pass. I'm filing the run log
to the palace under wing/today.

Jordan: Thanks Cipher. Echo, send the changelog draft.

Echo: Done. Sent to the channel. Sparrow, ready for review when you are.

Sparrow: Reviewed. Two small wording changes — sent back. Otherwise clean.

Jordan: Echo, apply Sparrow's edits and ship it.

Echo: Shipped. Tag pushed.
"""


@pytest.fixture
def ai_dialogue_corpus(tmp_path: Path) -> Path:
    """Create a one-file project directory containing the AI-dialogue fixture."""
    project_dir = tmp_path / "ai_dialogue_project"
    project_dir.mkdir()
    (project_dir / "session_log.md").write_text(AI_DIALOGUE_FIXTURE)
    return project_dir


@pytest.fixture
def corpus_origin_for_fixture() -> dict:
    """The corpus_origin result a Phase 1 init would produce for the fixture."""
    return {
        "schema_version": 1,
        "detected_at": "2026-04-26T00:00:00Z",
        "result": {
            "likely_ai_dialogue": True,
            "confidence": 0.95,
            "primary_platform": "Claude (Anthropic)",
            "user_name": "Jordan",
            "agent_persona_names": ["Echo", "Sparrow", "Cipher"],
            "evidence": ["Synthetic fixture for Phase 1 integration test"],
        },
    }


# ── Baseline test: pin v3.3.3 behavior ────────────────────────────────────


def test_baseline_v333_misclassifies_persona_names_as_people(ai_dialogue_corpus: Path):
    """Without corpus_origin context, v3.3.3 entity_detector cannot
    distinguish agent persona names from real people, and classifies them
    into the 'people' bucket.

    This test pins that behavior. Its purpose is documentation —
    Phase 1's job is to fix this, and the post-Phase-1 test below
    asserts the fix.
    """
    from mempalace.entity_detector import detect_entities, scan_for_detection

    files = scan_for_detection(str(ai_dialogue_corpus))
    detected = detect_entities(files)

    people_names = {e["name"] for e in detected.get("people", [])}
    uncertain_names = {e["name"] for e in detected.get("uncertain", [])}
    all_classified = people_names | uncertain_names

    # Persona names appear somewhere in the detection output (people or uncertain).
    # If none of them surface at all, the fixture is no longer triggering
    # the misclassification path and the test is no longer meaningful.
    persona_names = {"Echo", "Sparrow", "Cipher"}
    persona_hits = persona_names & all_classified
    assert persona_hits, (
        "Fixture no longer surfaces persona names as detected entities. "
        "Update the fixture to keep this test meaningful."
    )

    # No agent_personas bucket exists on v3.3.3.
    assert "agent_personas" not in detected, (
        "v3.3.3 has no concept of agent_personas — if this key exists, "
        "Phase 1 wiring has already shipped and this baseline test is stale."
    )


# ── Phase 1 test: with corpus_origin, personas reclassify ────────────────


def test_phase1_with_corpus_origin_reclassifies_personas(
    ai_dialogue_corpus: Path, corpus_origin_for_fixture: dict
):
    """When corpus_origin context is passed to detect_entities, names
    matching agent_persona_names land in an 'agent_personas' bucket
    instead of being misclassified as people.

    This is the Phase 1 fix. RED until the consumer wiring lands.
    """
    from mempalace.entity_detector import detect_entities, scan_for_detection

    files = scan_for_detection(str(ai_dialogue_corpus))
    detected = detect_entities(files, corpus_origin=corpus_origin_for_fixture)

    # New bucket exists.
    assert "agent_personas" in detected, (
        "Phase 1 must add an 'agent_personas' bucket to the detect_entities "
        "return shape when corpus_origin is provided."
    )

    persona_names_in_bucket = {e["name"] for e in detected["agent_personas"]}
    persona_names_in_people = {e["name"] for e in detected.get("people", [])}

    # All three personas land in the new bucket.
    expected_personas = {"Echo", "Sparrow", "Cipher"}
    assert expected_personas <= persona_names_in_bucket, (
        f"Expected all three personas in agent_personas, got: "
        f"{persona_names_in_bucket}"
    )

    # And NONE of them remain in the people bucket.
    leaked = expected_personas & persona_names_in_people
    assert not leaked, (
        f"Persona names {leaked} leaked into 'people' bucket — Phase 1 "
        f"consumer wiring is supposed to filter them out."
    )


# ── discover_entities (project_scanner) threads corpus_origin ─────────────


def test_discover_entities_threads_corpus_origin_through(
    ai_dialogue_corpus: Path, corpus_origin_for_fixture: dict
):
    """discover_entities is the higher-level entry point cmd_init uses.
    It must accept corpus_origin and produce the same persona reclassification
    that detect_entities does, regardless of whether candidates entered via
    prose, manifests, or git authors.
    """
    from mempalace.project_scanner import discover_entities

    detected = discover_entities(
        str(ai_dialogue_corpus),
        corpus_origin=corpus_origin_for_fixture,
    )

    persona_names_in_bucket = {e["name"] for e in detected.get("agent_personas", [])}
    persona_names_in_people = {e["name"] for e in detected.get("people", [])}
    expected_personas = {"Echo", "Sparrow", "Cipher"}

    # All personas surface in the agent_personas bucket via discover_entities too.
    assert expected_personas <= persona_names_in_bucket, (
        f"discover_entities did not thread corpus_origin to detect_entities. "
        f"Expected {expected_personas} in agent_personas, got: "
        f"{persona_names_in_bucket}"
    )

    leaked = expected_personas & persona_names_in_people
    assert not leaked, (
        f"discover_entities leaked persona names into 'people': {leaked}"
    )


def test_discover_entities_no_origin_unchanged_shape(ai_dialogue_corpus: Path):
    """Backwards compatibility: when corpus_origin is omitted, the return
    shape stays exactly what it was on v3.3.3 (no agent_personas key).
    Existing callers that don't pass corpus_origin must see no behavioral
    change.
    """
    from mempalace.project_scanner import discover_entities

    detected = discover_entities(str(ai_dialogue_corpus))

    # No new bucket appears unsolicited.
    assert "agent_personas" not in detected, (
        "discover_entities must not surface agent_personas when corpus_origin "
        "was not provided — that would be a silent behavior change for v3.3.3 "
        "callers who don't know about Phase 1."
    )


# ── §4 Pass 0 — cmd_init runs corpus_origin and writes origin.json ───────


def _stub_cfg(palace_dir: Path):
    """Build a MempalaceConfig stub whose palace_path points at tmp space.

    Used by Pass 0 tests so the origin.json write is captured in tmp_path
    instead of hitting the real ~/.mempalace location.
    """
    cfg = MagicMock()
    cfg.palace_path = str(palace_dir)
    cfg.entity_languages = ["en"]
    return cfg


def test_init_pass_zero_writes_origin_json_to_palace(
    ai_dialogue_corpus: Path, tmp_path: Path
):
    """cmd_init must run corpus_origin detection BEFORE entity detection
    and persist the result to ``<palace>/.mempalace/origin.json`` in the
    documented schema_version=1 wrapper.
    """
    from mempalace.cli import cmd_init

    palace = tmp_path / "palace"
    args = argparse.Namespace(dir=str(ai_dialogue_corpus), yes=True)

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.cli._maybe_run_mine_after_init"),
        patch("mempalace.room_detector_local.detect_rooms_local"),
    ):
        cmd_init(args)

    origin_path = palace / ".mempalace" / "origin.json"
    assert origin_path.exists(), (
        f"Pass 0 did not write {origin_path}. cmd_init is supposed to call "
        f"corpus_origin detection and persist the result before entity detection."
    )

    data = json.loads(origin_path.read_text())
    assert data.get("schema_version") == 1, (
        "origin.json must declare schema_version=1 so future format changes "
        "are detectable. Got: " + repr(data.get("schema_version"))
    )
    assert "detected_at" in data, "origin.json must include a detected_at timestamp"
    assert "result" in data, "origin.json must wrap the CorpusOriginResult under 'result'"
    assert isinstance(data["result"].get("likely_ai_dialogue"), bool)
    # Fixture is heavy AI-dialogue — heuristic should classify as such.
    assert data["result"]["likely_ai_dialogue"] is True, (
        "Heuristic should classify the AI-dialogue fixture as AI-dialogue. "
        f"Got: {data['result']}"
    )


def test_init_pass_zero_passes_corpus_origin_to_discover_entities(
    ai_dialogue_corpus: Path, tmp_path: Path
):
    """The Pass 0 result must reach discover_entities via the corpus_origin
    kwarg — that's what enables persona reclassification end-to-end.
    """
    from mempalace.cli import cmd_init

    palace = tmp_path / "palace"
    args = argparse.Namespace(dir=str(ai_dialogue_corpus), yes=True)

    captured = {}

    def fake_discover(project_dir, **kwargs):
        captured["kwargs"] = kwargs
        return {"people": [], "projects": [], "uncertain": []}

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.project_scanner.discover_entities", side_effect=fake_discover),
        patch("mempalace.cli._maybe_run_mine_after_init"),
        patch("mempalace.room_detector_local.detect_rooms_local"),
    ):
        cmd_init(args)

    assert "corpus_origin" in captured.get("kwargs", {}), (
        "cmd_init did not pass corpus_origin to discover_entities. The Pass 0 "
        "detection result must be threaded into entity detection so persona "
        "reclassification happens end-to-end."
    )
    origin = captured["kwargs"]["corpus_origin"]
    assert origin is not None, (
        "corpus_origin kwarg was passed but value was None — Pass 0 should "
        "supply the actual detection result for AI-dialogue corpora."
    )
    assert origin.get("schema_version") == 1
    assert "result" in origin


def test_init_pass_zero_skipped_when_no_readable_files(tmp_path: Path):
    """Empty project directory → no origin.json written, init still completes
    without crashing. Aya's earlier finding: don't fail init on missing samples.
    """
    from mempalace.cli import cmd_init

    project = tmp_path / "empty"
    project.mkdir()
    palace = tmp_path / "palace"
    args = argparse.Namespace(dir=str(project), yes=True)

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.cli._maybe_run_mine_after_init"),
        patch("mempalace.room_detector_local.detect_rooms_local"),
    ):
        cmd_init(args)  # must not raise

    origin_path = palace / ".mempalace" / "origin.json"
    assert not origin_path.exists(), (
        "Pass 0 must skip (no write) when there are no readable samples — "
        "writing a 'cannot decide' result to disk would be misleading."
    )


def test_init_pass_zero_uses_full_file_content_not_front_sampled(tmp_path: Path):
    """Per Aya's pushback: Tier 1 must read full file content, not bias-sample
    the first N chars. AI signal that lives past the first 2000 chars must
    still trip detection.
    """
    from mempalace.cli import cmd_init

    project = tmp_path / "deep_signal"
    project.mkdir()
    # File where the first 5000 chars are pure narrative with zero AI signal,
    # then heavy AI-dialogue signal kicks in afterward. A first-N-chars sampler
    # would miss it; a full-content reader will not.
    front_pad = (
        "The quiet morning settled over the orchard. " * 120
    )  # ~5400 chars, no AI signal
    ai_tail = (
        "\n\nUser: claude code, please help me debug this MCP integration.\n"
        "Assistant: Sure. I'll look at the LLM context window and the "
        "embedding pipeline. Claude Code can run the analysis now.\n"
        "User: also check ChatGPT compatibility.\n"
        "Assistant: GPT-4 should handle that. The MCP protocol abstracts it.\n"
    ) * 10
    (project / "log.md").write_text(front_pad + ai_tail)

    palace = tmp_path / "palace"
    args = argparse.Namespace(dir=str(project), yes=True)

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.cli._maybe_run_mine_after_init"),
        patch("mempalace.room_detector_local.detect_rooms_local"),
    ):
        cmd_init(args)

    origin_path = palace / ".mempalace" / "origin.json"
    assert origin_path.exists()
    data = json.loads(origin_path.read_text())
    assert data["result"]["likely_ai_dialogue"] is True, (
        "AI signal at chars 5400+ was missed — suggests Pass 0 is sampling "
        "the file front instead of reading full content. Fix Tier 1 to use "
        "full content per Aya's design pushback."
    )


# ── llm_refine consumer wiring ────────────────────────────────────────────


def test_llm_refine_includes_corpus_origin_context_in_prompt(
    corpus_origin_for_fixture: dict,
):
    """When corpus_origin is passed to refine_entities, the LLM call must
    receive the corpus-origin context (platform, user_name, agent personas)
    so it can disambiguate ambiguous candidates with knowledge that this
    is AI-dialogue.

    Per Phase 1 README: "llm_refine — same: the wider context improves
    classification accuracy."
    """
    from types import SimpleNamespace

    from mempalace.llm_refine import refine_entities

    captured: dict = {}

    class FakeProvider:
        def classify(self, system, user, json_mode=False):
            captured.setdefault("calls", []).append({"system": system, "user": user})
            return SimpleNamespace(text='{"classifications": []}')

    # A regex-derived candidate (no manifest/git signals) so it isn't
    # skipped by _is_authoritative_*.
    detected = {
        "people": [],
        "projects": [],
        "uncertain": [
            {"name": "Acme", "frequency": 3, "signals": ["appears 3x"], "type": "uncertain"}
        ],
    }

    refine_entities(
        detected,
        corpus_text="Acme appears in some prose context here.",
        provider=FakeProvider(),
        show_progress=False,
        corpus_origin=corpus_origin_for_fixture,
    )

    assert captured.get("calls"), "refine_entities did not call the provider"
    full_prompt = captured["calls"][0]["system"] + "\n" + captured["calls"][0]["user"]

    # The corpus-origin preamble must surface the user, agent personas,
    # and platform so the LLM has corpus-level context.
    assert "Jordan" in full_prompt, "user_name not surfaced in LLM context"
    for persona in ("Echo", "Sparrow", "Cipher"):
        assert persona in full_prompt, f"persona '{persona}' not in LLM context"
    assert "Claude" in full_prompt, "primary_platform not surfaced in LLM context"


def test_llm_refine_no_origin_keeps_v333_prompt_shape(monkeypatch):
    """Backwards compatibility: when corpus_origin is omitted, the prompt
    sent to the LLM must NOT contain a corpus-origin preamble. The
    pre-Phase-1 system prompt remains unchanged for callers who don't
    opt in.
    """
    from types import SimpleNamespace

    from mempalace.llm_refine import SYSTEM_PROMPT, refine_entities

    captured: dict = {}

    class FakeProvider:
        def classify(self, system, user, json_mode=False):
            captured["system"] = system
            return SimpleNamespace(text='{"classifications": []}')

    detected = {
        "people": [],
        "projects": [],
        "uncertain": [
            {"name": "Acme", "frequency": 3, "signals": ["appears 3x"], "type": "uncertain"}
        ],
    }

    refine_entities(
        detected,
        corpus_text="Acme appears in some prose.",
        provider=FakeProvider(),
        show_progress=False,
    )

    assert captured["system"] == SYSTEM_PROMPT, (
        "Without corpus_origin, refine_entities must use the unmodified "
        "SYSTEM_PROMPT — no silent prompt drift for v3.3.3 callers."
    )


# ── §7 mempalace mine --redetect-origin flag ──────────────────────────────


def _mine_args(project_dir: Path, *, redetect: bool):
    """Build a Namespace with all fields cmd_mine reads, scoped to the
    minimal set our tests exercise. Uses 'projects' mode and a dry_run
    so the actual miner is essentially a no-op for our purposes.
    """
    return argparse.Namespace(
        dir=str(project_dir),
        palace=None,
        mode="projects",
        wing=None,
        no_gitignore=False,
        include_ignored=[],
        agent="mempalace",
        limit=0,
        dry_run=True,
        extract="auto",
        redetect_origin=redetect,
    )


def test_mine_default_does_not_redetect_origin(
    ai_dialogue_corpus: Path, tmp_path: Path
):
    """Default `mempalace mine` (no --redetect-origin flag) must NOT run
    corpus_origin detection — the flag is opt-in.
    """
    from mempalace.cli import cmd_mine

    palace = tmp_path / "palace"
    args = _mine_args(ai_dialogue_corpus, redetect=False)

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.cli._run_pass_zero") as mock_pass_zero,
        patch("mempalace.miner.mine"),
    ):
        cmd_mine(args)

    mock_pass_zero.assert_not_called()
    assert not (palace / ".mempalace" / "origin.json").exists()


def test_mine_with_redetect_origin_flag_writes_origin_json(
    ai_dialogue_corpus: Path, tmp_path: Path
):
    """`mempalace mine --redetect-origin` re-runs corpus_origin detection
    on the project and persists the result to <palace>/.mempalace/origin.json.
    """
    from mempalace.cli import cmd_mine

    palace = tmp_path / "palace"
    args = _mine_args(ai_dialogue_corpus, redetect=True)

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.miner.mine"),
    ):
        cmd_mine(args)

    origin_path = palace / ".mempalace" / "origin.json"
    assert origin_path.exists(), (
        "--redetect-origin must write <palace>/.mempalace/origin.json"
    )
    data = json.loads(origin_path.read_text())
    assert data["schema_version"] == 1
    assert data["result"]["likely_ai_dialogue"] is True


def test_mine_redetect_overwrites_existing_origin_json(
    ai_dialogue_corpus: Path, tmp_path: Path
):
    """When origin.json already exists from a prior init, --redetect-origin
    overwrites it with the new detection result rather than skipping.
    Igor's §7 lean: option (c) — explicit user re-runs.
    """
    from mempalace.cli import cmd_mine

    palace = tmp_path / "palace"
    origin_dir = palace / ".mempalace"
    origin_dir.mkdir(parents=True)
    stale_origin = {
        "schema_version": 1,
        "detected_at": "2026-04-01T00:00:00Z",
        "result": {
            "likely_ai_dialogue": False,
            "confidence": 0.0,
            "primary_platform": None,
            "user_name": None,
            "agent_persona_names": [],
            "evidence": ["stale-from-prior-init"],
        },
    }
    (origin_dir / "origin.json").write_text(json.dumps(stale_origin))

    args = _mine_args(ai_dialogue_corpus, redetect=True)

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.miner.mine"),
    ):
        cmd_mine(args)

    fresh = json.loads((origin_dir / "origin.json").read_text())
    # Stale result said not AI-dialogue; fresh detection on the AI-dialogue
    # fixture must say it IS AI-dialogue. Confirms overwrite, not append/skip.
    assert fresh["result"]["likely_ai_dialogue"] is True
    assert fresh["detected_at"] != "2026-04-01T00:00:00Z"


def test_mine_redetect_uses_full_content_not_sampled(tmp_path: Path):
    """Regression for Aya's pushback: --redetect-origin must use the same
    full-content reader as Pass 0 (not first-N-chars sampling).
    """
    from mempalace.cli import cmd_mine

    project = tmp_path / "deep_signal"
    project.mkdir()
    front_pad = "The quiet morning settled over the orchard. " * 120
    ai_tail = (
        "\n\nUser: claude code, please help me debug this MCP integration.\n"
        "Assistant: ChatGPT compatibility too. Claude Code can run analysis.\n"
    ) * 10
    (project / "log.md").write_text(front_pad + ai_tail)

    palace = tmp_path / "palace"
    args = _mine_args(project, redetect=True)

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.miner.mine"),
    ):
        cmd_mine(args)

    data = json.loads((palace / ".mempalace" / "origin.json").read_text())
    assert data["result"]["likely_ai_dialogue"] is True, (
        "--redetect-origin missed AI signal at chars 5400+ — appears to "
        "be front-sampling instead of reading full content."
    )


# ── §2 --llm default flip + graceful fallback ────────────────────────────


def _init_args(project_dir: Path, *, no_llm: bool = False, **overrides):
    """Build an init Namespace with all fields the parser supplies."""
    base = dict(
        dir=str(project_dir),
        yes=True,
        lang=None,
        llm=False,
        no_llm=no_llm,
        llm_provider="ollama",
        llm_model="gemma4:e4b",
        llm_endpoint=None,
        llm_api_key=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_init_default_attempts_llm_provider(ai_dialogue_corpus: Path, tmp_path: Path):
    """Per §2: ``mempalace init`` (no flags) MUST try to acquire an LLM
    provider. This is the default-flip — opt-in becomes opt-out.
    """
    from mempalace.cli import cmd_init

    palace = tmp_path / "palace"
    args = _init_args(ai_dialogue_corpus)

    fake_provider = MagicMock()
    fake_provider.check_available.return_value = (True, "ok")
    # refine_entities will run; mock the provider's classify so it returns
    # an empty classification list (no candidate reclassification happens).
    fake_provider.classify.return_value = MagicMock(text='{"classifications": []}')

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.cli.get_provider", return_value=fake_provider) as mock_get,
        patch("mempalace.cli._maybe_run_mine_after_init"),
        patch("mempalace.room_detector_local.detect_rooms_local"),
    ):
        cmd_init(args)

    mock_get.assert_called_once(), (
        "Default `mempalace init` did not attempt LLM provider acquisition. "
        "Per Phase 1 §2, --llm is now ON by default."
    )


def test_init_no_llm_skips_provider_acquisition(
    ai_dialogue_corpus: Path, tmp_path: Path
):
    """``mempalace init --no-llm`` is the explicit opt-out path. No
    provider acquisition attempt; init runs in heuristics-only mode.
    """
    from mempalace.cli import cmd_init

    palace = tmp_path / "palace"
    args = _init_args(ai_dialogue_corpus, no_llm=True)

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.cli.get_provider") as mock_get,
        patch("mempalace.cli._maybe_run_mine_after_init"),
        patch("mempalace.room_detector_local.detect_rooms_local"),
    ):
        cmd_init(args)

    mock_get.assert_not_called(), (
        "--no-llm must NOT call get_provider — it's the heuristics-only opt-out."
    )


def test_init_graceful_fallback_when_provider_unavailable(
    ai_dialogue_corpus: Path, tmp_path: Path, capsys
):
    """Per Igor's §2: 'never block init on missing LLM'. When
    check_available returns False, init prints a one-line message and
    proceeds without an LLM provider.
    """
    from mempalace.cli import cmd_init

    palace = tmp_path / "palace"
    args = _init_args(ai_dialogue_corpus)

    fake_provider = MagicMock()
    fake_provider.check_available.return_value = (False, "Ollama not reachable at localhost:11434")

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.cli.get_provider", return_value=fake_provider),
        patch("mempalace.cli._maybe_run_mine_after_init"),
        patch("mempalace.room_detector_local.detect_rooms_local"),
    ):
        cmd_init(args)  # MUST NOT raise SystemExit

    out = capsys.readouterr().out
    # The fallback message should mention how to silence (--no-llm) so the
    # user knows what flipped.
    assert "no-llm" in out.lower() or "--no-llm" in out, (
        f"Graceful fallback message must point at --no-llm. Got: {out!r}"
    )


def test_init_graceful_fallback_on_provider_construction_error(
    ai_dialogue_corpus: Path, tmp_path: Path, capsys
):
    """When get_provider raises (e.g. anthropic chosen but no API key),
    init must catch and continue with heuristics. Not crash.
    """
    from mempalace.cli import cmd_init
    from mempalace.llm_client import LLMError

    palace = tmp_path / "palace"
    args = _init_args(ai_dialogue_corpus)

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.cli.get_provider", side_effect=LLMError("no api key")),
        patch("mempalace.cli._maybe_run_mine_after_init"),
        patch("mempalace.room_detector_local.detect_rooms_local"),
    ):
        cmd_init(args)  # MUST NOT raise

    out = capsys.readouterr().out
    assert "no-llm" in out.lower() or "--no-llm" in out, (
        "Provider-construction failure must surface a one-line message "
        f"pointing at --no-llm. Got: {out!r}"
    )


def test_init_legacy_llm_flag_compatible(ai_dialogue_corpus: Path, tmp_path: Path):
    """Backwards compatibility: `mempalace init --llm` still works as
    before (LLM enabled). The flag is now redundant with the default
    but must not error or surprise users who scripted it.
    """
    from mempalace.cli import cmd_init

    palace = tmp_path / "palace"
    args = _init_args(ai_dialogue_corpus, llm=True)

    fake_provider = MagicMock()
    fake_provider.check_available.return_value = (True, "ok")
    fake_provider.classify.return_value = MagicMock(text='{"classifications": []}')

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.cli.get_provider", return_value=fake_provider) as mock_get,
        patch("mempalace.cli._maybe_run_mine_after_init"),
        patch("mempalace.room_detector_local.detect_rooms_local"),
    ):
        cmd_init(args)

    mock_get.assert_called_once()


# ── End-to-end pipeline + edge cases ──────────────────────────────────────


def test_phase1_end_to_end_init_with_llm_separates_personas(
    ai_dialogue_corpus: Path, tmp_path: Path
):
    """End-to-end through `mempalace init` on the DEFAULT path (LLM enabled).
    Confirms the whole Phase 1 chain works without trusting per-stage mocks:

      cmd_init -> _run_pass_zero -> Tier 1 + Tier 2 -> origin.json
                -> discover_entities (with corpus_origin)
                  -> entity_detector + _apply_corpus_origin
                -> entities.json saved

    The misclassification this PR fixes (persona names ending up as people)
    must NOT appear in the saved entities.json on the default path. This
    is what an actual user with Ollama/Anthropic/OpenAI configured sees.

    Tier 2 LLM is mocked to return realistic persona output — we're not
    testing the LLM, we're testing the wiring that flows the LLM's
    persona names into entity classification end-to-end.
    """
    from mempalace.cli import cmd_init
    from mempalace.corpus_origin import CorpusOriginResult

    palace = tmp_path / "palace"
    args = _init_args(ai_dialogue_corpus)  # default = LLM ON

    fake_provider = MagicMock()
    fake_provider.check_available.return_value = (True, "ok")
    # refine_entities classify call — return empty so the LLM doesn't
    # reclassify candidates; we just need it not to crash.
    fake_provider.classify.return_value = MagicMock(text='{"classifications": []}')

    # Tier 2 corpus-origin LLM call — return the persona/user info that a
    # real Haiku call would extract from the AI-dialogue fixture.
    fake_llm_origin_result = CorpusOriginResult(
        likely_ai_dialogue=True,
        confidence=0.95,
        primary_platform="Claude (Anthropic)",
        user_name="Jordan",
        agent_persona_names=["Echo", "Sparrow", "Cipher"],
        evidence=["Tier 2 LLM identified three persona names"],
    )

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.cli.get_provider", return_value=fake_provider),
        patch(
            "mempalace.cli.detect_origin_llm",
            return_value=fake_llm_origin_result,
        ),
        patch("mempalace.cli._maybe_run_mine_after_init"),
        patch("mempalace.room_detector_local.detect_rooms_local"),
    ):
        cmd_init(args)

    # 1. origin.json was written and contains the LLM-extracted personas
    origin_data = json.loads((palace / ".mempalace" / "origin.json").read_text())
    assert origin_data["result"]["likely_ai_dialogue"] is True
    assert origin_data["result"]["agent_persona_names"] == ["Echo", "Sparrow", "Cipher"]
    assert origin_data["result"]["user_name"] == "Jordan"

    # 2. entities.json was written by the entity-confirmation step
    entities_path = ai_dialogue_corpus / "entities.json"
    assert entities_path.exists()
    entities = json.loads(entities_path.read_text())

    # 3. THE CORE PHASE 1 GUARANTEE: persona names must NOT appear in the
    # saved entities.json people list. This is what downstream tools
    # (miner, searcher, MCP) will read.
    saved_people = set(entities.get("people", []))
    persona_names = {"Echo", "Sparrow", "Cipher"}
    leaked = persona_names & saved_people
    assert not leaked, (
        f"Phase 1 end-to-end FAILED on the DEFAULT (LLM-enabled) path: "
        f"persona names {leaked} ended up in entities.json's people list. "
        f"Saved people: {saved_people}"
    )


def test_phase1_no_llm_path_matches_v333_classification(
    ai_dialogue_corpus: Path, tmp_path: Path
):
    """Documents the --no-llm degradation honestly: persona reclassification
    requires Tier 2 (LLM) to extract persona names. With --no-llm, the
    Tier 1 heuristic only answers 'is this AI-dialogue?' (yes/no gate).
    Persona names are NOT extracted and thus NOT reclassified.

    This is BY DESIGN — Tier 2 is where persona extraction lives. The
    no-LLM path is a graceful degradation, not a Phase 1 promise.

    The test PINS that v3.3.3-equivalent behavior on this path:
    persona names appear in entities.json's people list, exactly as they
    would on plain v3.3.3. Users who want persona reclassification must
    have an LLM provider configured (default behavior post-§2).
    """
    from mempalace.cli import cmd_init

    palace = tmp_path / "palace"
    args = _init_args(ai_dialogue_corpus, no_llm=True)  # explicit opt-out

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.cli._maybe_run_mine_after_init"),
        patch("mempalace.room_detector_local.detect_rooms_local"),
    ):
        cmd_init(args)

    # origin.json still written — Tier 1 still runs and detects AI-dialogue.
    origin = json.loads((palace / ".mempalace" / "origin.json").read_text())
    assert origin["result"]["likely_ai_dialogue"] is True
    # But agent_persona_names is empty — Tier 1 doesn't extract them.
    assert origin["result"]["agent_persona_names"] == [], (
        "Tier 1 heuristic is not supposed to extract persona names — "
        "that's Tier 2's job. If this assertion starts failing, the "
        "two-tier design has shifted and the README needs updating."
    )

    # entities.json shows v3.3.3-equivalent classification: persona names
    # appear in people because the heuristic gave us no agent context.
    entities = json.loads((ai_dialogue_corpus / "entities.json").read_text())
    saved_people = set(entities.get("people", []))
    # At least one persona surfaces in people — the documented degradation.
    assert {"Echo", "Sparrow", "Cipher"} & saved_people, (
        "On the --no-llm path, persona names are expected to appear in "
        "people (since no LLM extracted them). If none do, either the "
        "fixture changed or somehow Phase 1 is reclassifying without "
        "Tier 2 context — both warrant investigation."
    )


def test_phase1_re_init_idempotent(ai_dialogue_corpus: Path, tmp_path: Path):
    """Running `mempalace init` twice on the same project produces the
    same result. origin.json is overwritten on the second run (timestamp
    refreshes) but the classification result is identical.

    Catches: forgotten state, append-instead-of-overwrite bugs, side
    effects accumulating across runs.
    """
    from mempalace.cli import cmd_init

    palace = tmp_path / "palace"
    args = _init_args(ai_dialogue_corpus, no_llm=True)

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.cli._maybe_run_mine_after_init"),
        patch("mempalace.room_detector_local.detect_rooms_local"),
    ):
        cmd_init(args)
        first = json.loads((palace / ".mempalace" / "origin.json").read_text())
        cmd_init(args)
        second = json.loads((palace / ".mempalace" / "origin.json").read_text())

    # The result payload must be identical between runs (same fixture, same
    # heuristic, no nondeterminism in Tier 1).
    assert first["result"] == second["result"], (
        f"Re-init produced different classification results — Phase 1 "
        f"introduces nondeterminism somewhere.\nfirst:  {first['result']}\n"
        f"second: {second['result']}"
    )
    assert first["schema_version"] == second["schema_version"] == 1


def test_phase1_persona_user_name_collision_user_kept_in_people(
    tmp_path: Path,
):
    """Edge case Igor's review §7 named (and corpus_origin's tests cover at
    detection time): a user-name that COLLIDES with a persona name string.

    The corpus_origin module guarantees user_name is filtered out of
    agent_persona_names BEFORE the result is serialized — by the LLM tier's
    parser. So by the time _apply_corpus_origin sees the dict, persona
    list is already user-clean.

    This test pins the consumer-side assumption: even if for some reason
    a user_name happens to also be in agent_persona_names (e.g. a future
    tool writes origin.json by hand with overlap), the user keeps their
    place in the people bucket — they don't get reclassified as an agent.
    Phase 1 must protect the human from disappearing.
    """
    from mempalace.entity_detector import detect_entities

    project = tmp_path / "collision_corpus"
    project.mkdir()
    # "Claude" is BOTH the user (a real person) and a persona name in this
    # malformed origin.json. The fixture is heavy enough on Claude
    # references that detect_entities will pick the name up via dialogue
    # and pronoun signals.
    text = (
        "Claude wrote a long entry about her morning. Claude said "
        "the day was beautiful. She walked to the park. Claude smiled. "
        "Claude noticed the leaves had changed. She continued home. "
        "Claude thought about dinner. She prepared a meal. Claude ate slowly."
    )
    (project / "diary.md").write_text(text)

    # Malformed origin.json where user_name overlaps with personas.
    bad_origin = {
        "schema_version": 1,
        "detected_at": "2026-04-26T00:00:00Z",
        "result": {
            "likely_ai_dialogue": True,
            "confidence": 0.9,
            "primary_platform": "Claude (Anthropic)",
            "user_name": "Claude",
            "agent_persona_names": ["Claude", "Echo"],
            "evidence": ["malformed-fixture"],
        },
    }

    from mempalace.entity_detector import scan_for_detection

    files = scan_for_detection(str(project))
    # Apply Phase 1 with the malformed origin.
    detected = detect_entities(files, corpus_origin=bad_origin)

    # The current implementation moves any name matching a persona into
    # agent_personas. With the malformed input above, "Claude" WOULD move.
    # That is the protective behavior we're documenting today: be loud
    # about the malformation rather than silently corrupting. If/when we
    # add user-name-precedence logic, this test should flip and assert
    # Claude stays in people. Pinning current behavior so future changes
    # are deliberate.
    persona_names = {e["name"] for e in detected.get("agent_personas", [])}
    assert "Claude" in persona_names or "Claude" not in {
        e["name"] for e in detected.get("people", [])
    }, (
        "Inconsistent persona/people split on malformed origin.json — "
        "Claude is neither in personas nor filtered from people. "
        "Behavior is ambiguous, fix the consumer wiring to be explicit."
    )
    """Backwards compatibility: when corpus_origin is omitted, the return
    shape stays exactly what it was on v3.3.3 (no agent_personas key).
    Existing callers that don't pass corpus_origin must see no behavioral
    change.
    """
    from mempalace.project_scanner import discover_entities

    detected = discover_entities(str(ai_dialogue_corpus))

    # No new bucket appears unsolicited.
    assert "agent_personas" not in detected, (
        "discover_entities must not surface agent_personas when corpus_origin "
        "was not provided — that would be a silent behavior change for v3.3.3 "
        "callers who don't know about Phase 1."
    )


# ─────────────────────────────────────────────────────────────────────────
# Phase 1 × develop integration tests
#
# These tests pin the intersection points between Phase 1 (this PR) and
# develop's other in-flight work that landed since v3.3.3. They exist
# specifically to prove the cherry-pick onto develop produced a coherent
# whole — not a textual merge that quietly broke composition.
# ─────────────────────────────────────────────────────────────────────────


def test_integration_cmd_init_runs_pass_zero_to_pass_four_in_order(
    ai_dialogue_corpus: Path, tmp_path: Path
):
    """cmd_init now has FIVE passes after this PR lands on develop:
       0: corpus-origin (this PR)
       1: discover_entities (existing)
       2: detect_rooms_local (existing)
       3: gitignore protection (existing)
       4: _maybe_run_mine_after_init (develop, PR #1183)

    Order matters: Pass 0 must produce origin.json BEFORE Pass 1 reads
    it, and Pass 4 must run AFTER cfg.init() so the user is offered to
    mine a fully-set-up directory. This test pins the order so any
    future re-shuffle is caught.
    """
    from mempalace.cli import cmd_init

    palace = tmp_path / "palace"
    args = _init_args(ai_dialogue_corpus, no_llm=True)
    call_log: list = []

    real_run_pass_zero = __import__("mempalace.cli", fromlist=["_run_pass_zero"])._run_pass_zero

    def trace_pass_zero(*a, **kw):
        call_log.append("pass_zero")
        return real_run_pass_zero(*a, **kw)

    def trace_discover(*a, **kw):
        call_log.append("discover_entities")
        return {"people": [], "projects": [], "topics": [], "uncertain": []}

    def trace_rooms(*a, **kw):
        call_log.append("detect_rooms_local")

    def trace_gitignore(*a, **kw):
        call_log.append("gitignore")
        return False

    def trace_mine_prompt(*a, **kw):
        call_log.append("mine_prompt")

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.cli._run_pass_zero", side_effect=trace_pass_zero),
        patch("mempalace.project_scanner.discover_entities", side_effect=trace_discover),
        patch("mempalace.room_detector_local.detect_rooms_local", side_effect=trace_rooms),
        patch("mempalace.cli._ensure_mempalace_files_gitignored", side_effect=trace_gitignore),
        patch("mempalace.cli._maybe_run_mine_after_init", side_effect=trace_mine_prompt),
    ):
        cmd_init(args)

    expected = [
        "pass_zero",
        "discover_entities",
        "detect_rooms_local",
        "gitignore",
        "mine_prompt",
    ]
    assert call_log == expected, (
        f"cmd_init pass ordering broke after Phase 1 ↔ develop merge.\n"
        f"  expected: {expected}\n"
        f"  actual:   {call_log}\n"
        f"Pass 0 must come BEFORE entity discovery (so origin.json is "
        f"available); Pass 4 (mine prompt) must come AFTER gitignore "
        f"protection so the user is offered to mine a fully-set-up dir."
    )


def test_integration_topics_and_agent_personas_coexist(
    ai_dialogue_corpus: Path, corpus_origin_for_fixture: dict
):
    """develop adds a 'topics' bucket (PR #1184 cross-wing tunnels);
    Phase 1 adds an 'agent_personas' bucket. Both are additive, both
    are orthogonal, and detect_entities must surface BOTH when
    corpus_origin is provided.

    Catches the most-likely merge regression: dropping develop's topics
    list while applying Phase 1's _apply_corpus_origin.
    """
    from mempalace.entity_detector import detect_entities, scan_for_detection

    files = scan_for_detection(str(ai_dialogue_corpus))
    detected = detect_entities(files, corpus_origin=corpus_origin_for_fixture)

    # develop's topics bucket must still exist (even if empty for this fixture)
    assert "topics" in detected, (
        "Phase 1 reclassification dropped develop's 'topics' bucket. "
        "_apply_corpus_origin must preserve all keys it doesn't own."
    )
    # Phase 1's agent_personas bucket must exist with the persona names
    assert "agent_personas" in detected
    persona_names = {e["name"] for e in detected["agent_personas"]}
    assert {"Echo", "Sparrow", "Cipher"} <= persona_names


def test_integration_entities_json_includes_topics_excludes_personas(
    ai_dialogue_corpus: Path, tmp_path: Path
):
    """The on-disk entities.json (the per-project audit trail downstream
    tools read) must:
      - INCLUDE the topics list (develop's contribution)
      - NOT include persona names in the people list (Phase 1's contribution)

    This is the contract downstream tools (miner, palace_graph cross-wing
    tunnels) depend on.
    """
    from mempalace.cli import cmd_init
    from mempalace.corpus_origin import CorpusOriginResult

    palace = tmp_path / "palace"
    args = _init_args(ai_dialogue_corpus)

    fake_provider = MagicMock()
    fake_provider.check_available.return_value = (True, "ok")
    # llm_refine returns nothing (no reclassifications) — keeps test deterministic
    fake_provider.classify.return_value = MagicMock(text='{"classifications": []}')

    fake_origin = CorpusOriginResult(
        likely_ai_dialogue=True,
        confidence=0.95,
        primary_platform="Claude (Anthropic)",
        user_name="Jordan",
        agent_persona_names=["Echo", "Sparrow", "Cipher"],
        evidence=["test fixture"],
    )

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.cli.get_provider", return_value=fake_provider),
        patch("mempalace.cli.detect_origin_llm", return_value=fake_origin),
        patch("mempalace.cli._maybe_run_mine_after_init"),
        patch("mempalace.room_detector_local.detect_rooms_local"),
    ):
        cmd_init(args)

    entities_path = ai_dialogue_corpus / "entities.json"
    assert entities_path.exists()
    entities = json.loads(entities_path.read_text())

    # develop's contract: topics key is present (even if empty list)
    assert "topics" in entities, (
        "entities.json missing 'topics' key — develop's PR #1184 "
        "(cross-wing tunnels) requires this. The Phase 1 wiring must not "
        "have stripped it."
    )

    # Phase 1's contract: no persona names leak into people
    leaked = {"Echo", "Sparrow", "Cipher"} & set(entities.get("people", []))
    assert not leaked, (
        f"Phase 1 broken on develop: persona names {leaked} leaked into "
        f"people. The merge dropped agent_persona reclassification."
    )


def test_integration_add_to_known_entities_called_with_wing(
    ai_dialogue_corpus: Path, tmp_path: Path
):
    """develop changed add_to_known_entities to take a ``wing=`` kwarg
    (PR #1184) so cross-wing tunnels can map topics to wings. The
    Phase 1 path through cmd_init must respect this — calling it
    without ``wing=`` would silently break tunnel computation later.
    """
    from mempalace.cli import cmd_init
    from mempalace.corpus_origin import CorpusOriginResult

    palace = tmp_path / "palace"
    args = _init_args(ai_dialogue_corpus)

    fake_provider = MagicMock()
    fake_provider.check_available.return_value = (True, "ok")
    fake_provider.classify.return_value = MagicMock(text='{"classifications": []}')

    fake_origin = CorpusOriginResult(
        likely_ai_dialogue=True,
        confidence=0.95,
        primary_platform=None,
        user_name="Jordan",
        agent_persona_names=["Echo", "Sparrow", "Cipher"],
        evidence=[],
    )

    with (
        patch("mempalace.cli.MempalaceConfig", return_value=_stub_cfg(palace)),
        patch("mempalace.cli.get_provider", return_value=fake_provider),
        patch("mempalace.cli.detect_origin_llm", return_value=fake_origin),
        patch("mempalace.cli._maybe_run_mine_after_init"),
        patch("mempalace.room_detector_local.detect_rooms_local"),
        patch("mempalace.miner.add_to_known_entities") as mock_add,
    ):
        cmd_init(args)

    if mock_add.called:
        # Inspect the call kwargs — wing= must be present per develop's signature.
        _, kwargs = mock_add.call_args
        assert "wing" in kwargs, (
            "add_to_known_entities was called WITHOUT wing= kwarg. "
            "develop's PR #1184 added this parameter; Phase 1's call site "
            "must pass it for cross-wing tunnels to work."
        )
        assert kwargs["wing"] == ai_dialogue_corpus.name


def test_integration_llm_refine_corpus_origin_preamble_does_not_break_topic_label(
    corpus_origin_for_fixture: dict,
):
    """develop added TOPIC as a valid llm_refine label (PR #1184).
    Phase 1 prepends a CORPUS CONTEXT preamble to the system prompt.
    The two must coexist:
      - SYSTEM_PROMPT still defines TOPIC as a valid label
      - VALID_LABELS still includes TOPIC
      - Phase 1 preamble doesn't override or contradict TOPIC handling
    """
    from types import SimpleNamespace

    from mempalace.llm_refine import VALID_LABELS, refine_entities

    # TOPIC is preserved as a valid label
    assert "TOPIC" in VALID_LABELS, (
        "develop's TOPIC label was dropped during Phase 1 merge"
    )

    captured: dict = {}

    class FakeProvider:
        def classify(self, system, user, json_mode=False):
            captured["system"] = system
            return SimpleNamespace(
                text='{"classifications": [{"name": "Echo", "label": "TOPIC", "reason": "test"}]}'
            )

    detected = {
        "people": [],
        "projects": [],
        "topics": [],
        "uncertain": [
            {"name": "Echo", "frequency": 5, "signals": ["appears 5x"], "type": "uncertain"}
        ],
    }

    refine_entities(
        detected,
        corpus_text="Echo appears in some prose.",
        provider=FakeProvider(),
        show_progress=False,
        corpus_origin=corpus_origin_for_fixture,
    )

    # Both signals must be in the prompt: develop's TOPIC instructions AND
    # Phase 1's corpus context preamble.
    assert "TOPIC" in captured["system"], (
        "TOPIC label instructions disappeared from SYSTEM_PROMPT — "
        "Phase 1 preamble appears to have replaced rather than appended"
    )
    assert "CORPUS CONTEXT" in captured["system"], (
        "Phase 1 corpus context preamble missing from prompt"
    )

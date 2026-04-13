"""Fixture-backed normalization tests for real export shapes.

These tests intentionally go through the top-level ``normalize()`` entry point
instead of calling parser helpers directly. The repo already has good unit
coverage for individual branches; these fixtures protect the public contract
that ``mine`` and other higher-level ingestion paths actually rely on.
"""

from pathlib import Path

import pytest

from mempalace.convo_miner import chunk_exchanges
from mempalace.normalize import normalize

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "transcripts"


@pytest.mark.parametrize(
    ("fixture_name", "includes", "excludes", "expected_user_turns", "min_chunks"),
    [
        (
            "claude_code_session.jsonl",
            [
                "> Please review the parser and explain where normalization can fail in exported chat logs.",
                "[Bash] rg -n \"normalize|chat export\" mempalace tests",
                "→ mempalace/normalize.py:23:def normalize(filepath: str)",
                "> Add regression tests so a future refactor cannot silently break exported transcript support.",
            ],
            [],
            2,
            2,
        ),
        (
            "codex_rollout.jsonl",
            [
                "> Review the storage migration checklist and call out the rollback risks before deployment.",
                "The main rollback hazards are schema writes, background reindex jobs, and stale workers still serving old assumptions.",
                "> Then write down the guardrails the release owner should verify during the cutover.",
            ],
            [
                "synthetic context that should not appear in the normalized transcript",
                "duplicate tool context that should also be ignored",
            ],
            2,
            2,
        ),
        (
            "claude_ai_privacy_export.json",
            [
                "> Summarize the migration risks before we cut the release candidate.",
                "The main risks are schema drift, stale caches, and missing rollback checkpoints.",
                "> Write down the rollout guardrails so the ops handoff is explicit.",
            ],
            [],
            2,
            2,
        ),
        (
            "chatgpt_conversations.json",
            [
                "> Review the storage migration plan and call out the rollback hazards before deployment.",
                "Rollback risk is highest around schema writes and background reindex jobs, so capture checkpoints before either step.",
                "> List the release-owner guardrails that must be checked during cutover.",
                "---",
            ],
            [],
            2,
            2,
        ),
        (
            "slack_dm.json",
            [
                "> Can you review the migration notes and flag any rollback hazards before tonight's deploy?",
                "Yes. I want checkpoints around schema writes, cache invalidation, and worker restarts.",
                "> Also list the ownership handoff so the release captain knows who confirms each phase.",
            ],
            [],
            2,
            2,
        ),
    ],
)
def test_normalize_real_export_fixtures(
    fixture_name: str,
    includes: list[str],
    excludes: list[str],
    expected_user_turns: int,
    min_chunks: int,
):
    normalized = normalize(str(FIXTURE_DIR / fixture_name))

    for snippet in includes:
        assert snippet in normalized

    for snippet in excludes:
        assert snippet not in normalized

    # User-turn markers are the stable contract the conversation miner consumes.
    user_turns = [line for line in normalized.splitlines() if line.startswith("> ")]
    assert len(user_turns) == expected_user_turns

    # Chunking the normalized output catches regressions where normalize()
    # technically returns text but no longer emits a mineable transcript shape.
    assert len(chunk_exchanges(normalized)) >= min_chunks

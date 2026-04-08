"""
test_verify.py — Tests for tardygrada contradiction detection on search results.
"""

import subprocess
from unittest.mock import patch, MagicMock

from mempalace.searcher import search_memories

# Sample tardygrada verify-doc output with a conflict
CONFLICT_OUTPUT = """=== Tardygrada Document Verification ===
File: /tmp/mempalace_verify_abc123.md
Sentences: 4
Triples extracted: 6
Entity groups: 2
Pairs checked: 1

[CONFLICT] Lines 1 vs 3:
  "project completed on time"
  "project delayed 3 months"
  -> Triple conflict: (project, status, completed) vs (project, status, delayed)
  Confidence: 0.85

Summary: 1 contradiction found, 1 potential conflict checked, 4 sentences verified
Time: 3ms
"""

CLEAN_OUTPUT = """=== Tardygrada Document Verification ===
File: /tmp/mempalace_verify_abc123.md
Sentences: 4
Triples extracted: 6
Entity groups: 2
Pairs checked: 1

Summary: 0 contradictions found, 1 potential conflict checked, 4 sentences verified
Time: 2ms
"""


class TestVerifyWithTardygrada:
    def test_verify_detects_conflicts(self, palace_path, seeded_collection):
        mock_result = MagicMock()
        mock_result.stdout = CONFLICT_OUTPUT
        mock_result.returncode = 0

        with patch("mempalace.searcher.subprocess.run", return_value=mock_result):
            result = search_memories("authentication", palace_path, verify=True)

        assert "contradictions" in result
        assert len(result["contradictions"]) == 1
        c = result["contradictions"][0]
        assert "project completed on time" in c["claim_a"]
        assert "project delayed 3 months" in c["claim_b"]
        assert c["confidence"] == 0.85

    def test_verify_clean_results(self, palace_path, seeded_collection):
        mock_result = MagicMock()
        mock_result.stdout = CLEAN_OUTPUT
        mock_result.returncode = 0

        with patch("mempalace.searcher.subprocess.run", return_value=mock_result):
            result = search_memories("authentication", palace_path, verify=True)

        assert "contradictions" in result
        assert result["contradictions"] == []

    def test_verify_missing_binary(self, palace_path, seeded_collection):
        with patch(
            "mempalace.searcher.subprocess.run",
            side_effect=FileNotFoundError("tardygrada not found"),
        ):
            result = search_memories("authentication", palace_path, verify=True)

        assert result["contradictions"] is None
        assert "tardygrada" in result["verify_warning"].lower()

    def test_verify_timeout(self, palace_path, seeded_collection):
        with patch(
            "mempalace.searcher.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="tardygrada", timeout=10),
        ):
            result = search_memories("authentication", palace_path, verify=True)

        assert result["contradictions"] is None
        assert "timeout" in result["verify_warning"].lower()

    def test_verify_default_off(self, palace_path, seeded_collection):
        with patch("mempalace.searcher.subprocess.run") as mock_run:
            result = search_memories("authentication", palace_path)

        mock_run.assert_not_called()
        assert "contradictions" not in result

    def test_verify_preserves_results(self, palace_path, seeded_collection):
        mock_result = MagicMock()
        mock_result.stdout = CLEAN_OUTPUT
        mock_result.returncode = 0

        with patch("mempalace.searcher.subprocess.run", return_value=mock_result):
            result = search_memories("authentication", palace_path, verify=True)

        assert "results" in result
        assert len(result["results"]) > 0
        assert result["results"][0]["text"]

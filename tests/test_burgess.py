#!/usr/bin/env python3
"""Tests for the Burgess Principle human-impact scanner."""

from mempalace.burgess import scan_human_impact, format_review_block


class TestScanHumanImpact:
    """Test scan_human_impact detects the correct impact areas."""

    def test_no_impact(self):
        """Plain text with no human-impact signals should not be flagged."""
        result = scan_human_impact("We refactored the sorting algorithm to use merge sort instead.")
        assert result["flagged"] is False
        assert result["areas"] == []
        assert "✅" in result["summary"]

    def test_accessibility_detection(self):
        """Text mentioning accessibility concepts should flag the area."""
        text = "Updated the ARIA labels on the login form and added alt text to images."
        result = scan_human_impact(text)
        assert result["flagged"] is True
        area_names = [a["area"] for a in result["areas"]]
        assert "accessibility" in area_names

    def test_privacy_detection(self):
        """Text mentioning privacy/GDPR concepts should flag the area."""
        text = "Added GDPR consent flow and updated the data retention policy for personal data."
        result = scan_human_impact(text)
        assert result["flagged"] is True
        area_names = [a["area"] for a in result["areas"]]
        assert "privacy" in area_names

    def test_security_detection(self):
        """Text mentioning security concepts should flag the area."""
        text = "Implemented JWT authentication and added input validation to prevent SQL injection."
        result = scan_human_impact(text)
        assert result["flagged"] is True
        area_names = [a["area"] for a in result["areas"]]
        assert "security" in area_names

    def test_billing_detection(self):
        """Text mentioning billing/payment concepts should flag the area."""
        text = "Updated the Stripe payment flow to handle subscription upgrades and refunds."
        result = scan_human_impact(text)
        assert result["flagged"] is True
        area_names = [a["area"] for a in result["areas"]]
        assert "billing" in area_names

    def test_user_language_detection(self):
        """Text mentioning user-facing language should flag the area."""
        text = "Changed the error messages and updated the onboarding tooltip text."
        result = scan_human_impact(text)
        assert result["flagged"] is True
        area_names = [a["area"] for a in result["areas"]]
        assert "user_language" in area_names

    def test_automated_decisions_detection(self):
        """Text mentioning automated decisions should flag the area."""
        text = "The credit scoring algorithm now automatically denies applications with low scores."
        result = scan_human_impact(text)
        assert result["flagged"] is True
        area_names = [a["area"] for a in result["areas"]]
        assert "automated_decisions" in area_names

    def test_deployment_detection(self):
        """Text mentioning deployment/infra concepts should flag the area."""
        text = "Deployed the feature flag changes to production and updated the rollout percentage."
        result = scan_human_impact(text)
        assert result["flagged"] is True
        area_names = [a["area"] for a in result["areas"]]
        assert "deployment" in area_names

    def test_multiple_areas(self):
        """Text touching multiple areas should flag all of them."""
        text = (
            "Updated the GDPR consent flow, changed error messages, "
            "and deployed the new authentication system to production."
        )
        result = scan_human_impact(text)
        assert result["flagged"] is True
        area_names = [a["area"] for a in result["areas"]]
        assert len(area_names) >= 2

    def test_threshold(self):
        """Higher threshold should require more matches to flag."""
        text = "Added a tooltip"  # weak single signal
        scan_human_impact(text, threshold=0.5)
        result_high = scan_human_impact(text, threshold=5.0)
        # Low threshold may flag, high threshold should not
        assert result_high["flagged"] is False

    def test_burgess_question_always_present(self):
        """The Burgess question should always be in the result."""
        result = scan_human_impact("just some plain text")
        assert "burgess_question" in result
        assert "human member" in result["burgess_question"]

    def test_areas_sorted_by_score(self):
        """Flagged areas should be sorted by score descending."""
        text = (
            "auth password credential token jwt oauth sso "
            "tooltip onboarding"
        )
        result = scan_human_impact(text)
        if len(result["areas"]) >= 2:
            scores = [a["score"] for a in result["areas"]]
            assert scores == sorted(scores, reverse=True)


class TestFormatReviewBlock:
    """Test the human-readable review block formatter."""

    def test_no_flags_format(self):
        """Unflagged content should produce a clean pass message."""
        scan_result = scan_human_impact("plain text about merge sort")
        block = format_review_block(scan_result)
        assert "Burgess Principle" in block
        assert "✅" in block

    def test_flagged_format(self):
        """Flagged content should produce a detailed review block."""
        scan_result = scan_human_impact(
            "Added ARIA labels and updated the GDPR consent flow"
        )
        block = format_review_block(scan_result)
        assert "Burgess Principle" in block
        assert "Recommendation" in block
        assert "reviewed by a human" in block

    def test_format_includes_reviewer(self):
        """The review block should recommend specific reviewer types."""
        scan_result = scan_human_impact("Updated JWT authentication and password hashing")
        block = format_review_block(scan_result)
        assert "security engineer" in block

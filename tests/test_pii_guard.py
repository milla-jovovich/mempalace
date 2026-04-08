"""
test_pii_guard.py — Tests for PII detection, sanitization, and restoration.

Covers: email, phone, SSN, credit card, IP address, date of birth detection,
sanitize/restore round-trip, overlap handling, custom patterns, and edge cases.
"""

import re

from mempalace.pii_guard import PIIGuard, _make_token


class TestDetection:
    def test_detect_email(self):
        guard = PIIGuard()
        matches = guard.detect("Contact alice@example.com for details.")
        assert len(matches) == 1
        assert matches[0].pii_type == "EMAIL"
        assert matches[0].original == "alice@example.com"

    def test_detect_multiple_emails(self):
        guard = PIIGuard()
        text = "Send to alice@example.com and bob@company.org"
        matches = guard.detect(text)
        emails = [m for m in matches if m.pii_type == "EMAIL"]
        assert len(emails) == 2

    def test_detect_phone_formats(self):
        guard = PIIGuard()
        phones = [
            "555-123-4567",
            "(555) 123-4567",
            "555.123.4567",
            "5551234567",
            "+1 555-123-4567",
            "1-555-123-4567",
        ]
        for phone in phones:
            matches = guard.detect(f"Call me at {phone} please.")
            phone_matches = [m for m in matches if m.pii_type == "PHONE"]
            assert len(phone_matches) >= 1, f"Failed to detect phone: {phone}"

    def test_detect_ssn(self):
        guard = PIIGuard()
        matches = guard.detect("SSN: 123-45-6789")
        ssn = [m for m in matches if m.pii_type == "SSN"]
        assert len(ssn) == 1
        assert ssn[0].original == "123-45-6789"

    def test_detect_credit_card(self):
        guard = PIIGuard()
        cards = [
            "4111 1111 1111 1111",  # Visa
            "5500-0000-0000-0004",  # Mastercard
            "6011 1111 1111 1117",  # Discover
        ]
        for card in cards:
            matches = guard.detect(f"Card: {card}")
            cc = [m for m in matches if m.pii_type == "CREDIT_CARD"]
            assert len(cc) >= 1, f"Failed to detect card: {card}"

    def test_detect_ip_address(self):
        guard = PIIGuard()
        matches = guard.detect("Server at 192.168.1.100 is down.")
        ips = [m for m in matches if m.pii_type == "IP_ADDRESS"]
        assert len(ips) == 1
        assert ips[0].original == "192.168.1.100"

    def test_detect_date_of_birth(self):
        guard = PIIGuard()
        texts = [
            "DOB: 03/15/1990",
            "Date of Birth: 1990-03-15",
            "born 03/15/1990",
        ]
        for text in texts:
            matches = guard.detect(text)
            dob = [m for m in matches if m.pii_type == "DATE_OF_BIRTH"]
            assert len(dob) >= 1, f"Failed to detect DOB in: {text}"

    def test_no_false_positives_on_clean_text(self):
        guard = PIIGuard()
        clean_texts = [
            "The weather is nice today.",
            "Let's discuss the project timeline.",
            "Python 3.12 was released recently.",
            "The meeting is at 2pm.",
        ]
        for text in clean_texts:
            assert not guard.has_pii(text), f"False positive in: {text}"


class TestSanitize:
    def test_sanitize_single_email(self):
        guard = PIIGuard()
        sanitized, mapping = guard.sanitize("Email: alice@example.com")
        assert "alice@example.com" not in sanitized
        assert "[EMAIL_" in sanitized
        assert len(mapping) == 1

    def test_sanitize_multiple_types(self):
        guard = PIIGuard()
        text = "Email alice@test.com, SSN 123-45-6789, IP 10.0.0.1"
        sanitized, mapping = guard.sanitize(text)
        assert "alice@test.com" not in sanitized
        assert "123-45-6789" not in sanitized
        assert "10.0.0.1" not in sanitized
        assert len(mapping) == 3

    def test_sanitize_empty_string(self):
        guard = PIIGuard()
        sanitized, mapping = guard.sanitize("")
        assert sanitized == ""
        assert mapping == {}

    def test_sanitize_no_pii(self):
        guard = PIIGuard()
        text = "Just a normal sentence."
        sanitized, mapping = guard.sanitize(text)
        assert sanitized == text
        assert mapping == {}

    def test_deterministic_tokens(self):
        """Same PII value always produces the same token."""
        guard = PIIGuard()
        _, map1 = guard.sanitize("Email: alice@example.com")
        _, map2 = guard.sanitize("Contact alice@example.com")
        tokens1 = set(map1.keys())
        tokens2 = set(map2.keys())
        assert tokens1 == tokens2


class TestRestore:
    def test_round_trip(self):
        guard = PIIGuard()
        original = "Email alice@test.com, call 555-123-4567, SSN 123-45-6789"
        sanitized, mapping = guard.sanitize(original)
        restored = guard.restore(sanitized, mapping)
        assert restored == original

    def test_round_trip_multiple_same_type(self):
        guard = PIIGuard()
        original = "Contact alice@a.com or bob@b.com"
        sanitized, mapping = guard.sanitize(original)
        restored = guard.restore(sanitized, mapping)
        assert restored == original

    def test_restore_with_empty_mapping(self):
        guard = PIIGuard()
        text = "No PII here."
        restored = guard.restore(text, {})
        assert restored == text


class TestConfiguration:
    def test_enabled_types_filter(self):
        """Only detect specified PII types."""
        guard = PIIGuard(enabled_types={"EMAIL"})
        text = "Email alice@test.com, SSN 123-45-6789"
        matches = guard.detect(text)
        types = {m.pii_type for m in matches}
        assert "EMAIL" in types
        assert "SSN" not in types

    def test_custom_patterns(self):
        """User-supplied patterns should work alongside built-in ones."""
        guard = PIIGuard(
            custom_patterns={
                "EMPLOYEE_ID": re.compile(r"\bEMP-\d{6}\b"),
            }
        )
        text = "Employee EMP-123456 emailed alice@test.com"
        matches = guard.detect(text)
        types = {m.pii_type for m in matches}
        assert "EMPLOYEE_ID" in types
        assert "EMAIL" in types


class TestEdgeCases:
    def test_overlapping_matches_handled(self):
        """Overlapping PII detections should not cause double-replacement."""
        guard = PIIGuard()
        # An SSN could partially overlap with phone patterns;
        # verify we don't corrupt the text
        text = "SSN: 123-45-6789"
        sanitized, mapping = guard.sanitize(text)
        restored = guard.restore(sanitized, mapping)
        assert restored == text

    def test_pii_at_start_and_end(self):
        guard = PIIGuard()
        text = "alice@test.com is the contact, reach out to bob@test.com"
        sanitized, mapping = guard.sanitize(text)
        restored = guard.restore(sanitized, mapping)
        assert restored == text

    def test_summary(self):
        guard = PIIGuard()
        text = "Email alice@a.com, bob@b.com. SSN 123-45-6789."
        summary = guard.summary(text)
        assert summary["total"] == 3
        assert "EMAIL" in summary["by_type"]
        assert len(summary["by_type"]["EMAIL"]) == 2

    def test_has_pii(self):
        guard = PIIGuard()
        assert guard.has_pii("Email: alice@test.com")
        assert not guard.has_pii("No PII here")

    def test_token_format(self):
        token = _make_token("EMAIL", "alice@test.com")
        assert token.startswith("[EMAIL_")
        assert token.endswith("]")
        assert len(token) == len("[EMAIL_") + 6 + 1  # type + _ + 6 hex + ]

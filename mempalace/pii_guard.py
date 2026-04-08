"""
pii_guard.py — Regex-based PII detection and sanitization for MemPalace
=======================================================================

Detects and replaces personally identifiable information (PII) in text
with deterministic placeholder tokens. Supports round-trip: sanitized
text can be restored to original using the mapping.

Zero new dependencies. Uses stdlib `re` only.

Detected PII types:
  - Email addresses
  - Phone numbers (US formats)
  - Social Security Numbers (SSN)
  - Credit card numbers (Visa, MC, Amex, Discover)
  - IP addresses (IPv4)
  - Dates of birth (common formats)

Usage:
    from mempalace.pii_guard import PIIGuard

    guard = PIIGuard()
    sanitized, mapping = guard.sanitize("Email me at alice@example.com")
    # sanitized: "Email me at [EMAIL_a1b2c3]"
    # mapping: {"[EMAIL_a1b2c3]": "alice@example.com"}

    restored = guard.restore(sanitized, mapping)
    # restored: "Email me at alice@example.com"
"""

import hashlib
import re
from dataclasses import dataclass, field


@dataclass
class PIIMatch:
    """A single PII detection result."""

    pii_type: str
    original: str
    start: int
    end: int
    token: str = ""


# Patterns ordered from most specific to least specific to avoid
# partial matches (e.g. a phone number inside an SSN pattern).
PII_PATTERNS = {
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "CREDIT_CARD": re.compile(
        r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6(?:011|5\d{2}))"
        r"[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{1,4}\b"
    ),
    "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "PHONE": re.compile(
        r"(?<!\d)"
        r"(?:\+?1[\s.-]?)?"
        r"(?:\(?\d{3}\)?[\s.-]?)"
        r"\d{3}[\s.-]?\d{4}"
        r"(?!\d)"
    ),
    "IP_ADDRESS": re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
    ),
    "DATE_OF_BIRTH": re.compile(
        r"\b(?:DOB|dob|Date of Birth|date of birth|born|Born)"
        r"[\s:]*"
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})"
    ),
}


def _make_token(pii_type: str, value: str) -> str:
    """Generate a deterministic placeholder token for a PII value.

    Same input always produces the same token, enabling consistent
    replacement across multiple occurrences of the same PII value.
    """
    digest = hashlib.sha256(value.encode()).hexdigest()[:6]
    return f"[{pii_type}_{digest}]"


@dataclass
class PIIGuard:
    """Regex-based PII sanitizer with round-trip restore capability.

    Attributes:
        enabled_types: Set of PII type names to detect. Defaults to all.
            Valid types: SSN, CREDIT_CARD, EMAIL, PHONE, IP_ADDRESS, DATE_OF_BIRTH
        custom_patterns: Additional regex patterns to detect.
            Dict of {type_name: compiled_regex}.
    """

    enabled_types: set = field(default_factory=lambda: set(PII_PATTERNS.keys()))
    custom_patterns: dict = field(default_factory=dict)

    def detect(self, text: str) -> list:
        """Scan text for PII. Returns list of PIIMatch objects."""
        matches = []
        all_patterns = {**PII_PATTERNS, **self.custom_patterns}

        for pii_type, pattern in all_patterns.items():
            if pii_type not in self.enabled_types and pii_type not in self.custom_patterns:
                continue
            for m in pattern.finditer(text):
                # For DATE_OF_BIRTH, the date itself is in group 1 if present,
                # but we replace the entire match including the label
                original = m.group(0)
                token = _make_token(pii_type, original)
                matches.append(
                    PIIMatch(
                        pii_type=pii_type,
                        original=original,
                        start=m.start(),
                        end=m.end(),
                        token=token,
                    )
                )

        # Sort by position (descending) so replacements don't shift indices
        matches.sort(key=lambda m: m.start, reverse=True)

        # Remove overlapping matches (keep the first/longest one found)
        filtered = []
        used_ranges = []
        for match in matches:
            overlaps = any(
                match.start < ur_end and match.end > ur_start for ur_start, ur_end in used_ranges
            )
            if not overlaps:
                filtered.append(match)
                used_ranges.append((match.start, match.end))

        return filtered

    def sanitize(self, text: str) -> tuple:
        """Replace PII in text with deterministic tokens.

        Returns:
            (sanitized_text, mapping) where mapping is {token: original_value}
        """
        if not text:
            return text, {}

        matches = self.detect(text)
        mapping = {}
        result = text

        # Matches are already sorted descending by position
        for match in matches:
            mapping[match.token] = match.original
            result = result[: match.start] + match.token + result[match.end :]

        return result, mapping

    def restore(self, sanitized_text: str, mapping: dict) -> str:
        """Restore sanitized text using the token mapping."""
        result = sanitized_text
        for token, original in mapping.items():
            result = result.replace(token, original)
        return result

    def has_pii(self, text: str) -> bool:
        """Quick check: does this text contain any detectable PII?"""
        return len(self.detect(text)) > 0

    def summary(self, text: str) -> dict:
        """Return a summary of PII found in text, grouped by type."""
        matches = self.detect(text)
        by_type = {}
        for m in matches:
            by_type.setdefault(m.pii_type, []).append(m.original)
        return {
            "total": len(matches),
            "by_type": by_type,
        }

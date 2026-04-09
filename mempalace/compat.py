"""Cross-platform console compatibility helpers."""

import sys


def _stdout_supports(chars: str) -> bool:
    encoding = getattr(sys.stdout, "encoding", "ascii") or "ascii"
    try:
        chars.encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


CHECKMARK = "✓" if _stdout_supports("✓") else "+"

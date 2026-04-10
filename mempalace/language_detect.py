"""Language detection using Unicode range heuristics.

Detects whether text is primarily Chinese (zh) or English (en) based on
the ratio of CJK Unified Ideograph characters (U+4E00-U+9FFF) to total
alphabetic + CJK characters. No external dependencies required.
"""


def get_chinese_ratio(text: str) -> float:
    """Return ratio of Chinese characters to total alphabetic+CJK characters.

    Returns 0.0 for empty text or text with no alphabetic/CJK characters.
    """
    if not text:
        return 0.0
    cjk_count = 0
    alpha_count = 0
    for c in text:
        if "\u4e00" <= c <= "\u9fff":
            cjk_count += 1
        elif c.isalpha():
            alpha_count += 1
    total = cjk_count + alpha_count
    if total == 0:
        return 0.0
    return cjk_count / total


def detect_language(text: str) -> str:
    """Detect primary language of text.

    Returns 'zh', 'en', or 'unknown'.
    Uses Unicode range analysis: CJK Unified Ideographs (U+4E00-U+9FFF).

    File-level thresholds:
    - >10% CJK characters => 'zh'
    - <1% CJK characters => 'en'
    - Between 1-10% => 'zh' (mixed content with significant CJK)
    """
    if not text or not text.strip():
        return "unknown"
    ratio = get_chinese_ratio(text)
    # Check if text has any alphabetic or CJK content at all
    has_alpha_or_cjk = any(c.isalpha() or "\u4e00" <= c <= "\u9fff" for c in text)
    if not has_alpha_or_cjk:
        return "unknown"
    if ratio > 0.10:
        return "zh"
    elif ratio < 0.01:
        return "en"
    else:
        # Between 1-10%: mixed content, but CJK presence is significant
        # (e.g., "小明用 Python 写了一个组件" has low ratio but is Chinese)
        return "zh"


def detect_chunk_language(text: str) -> str:
    """Chunk-level detection with lower thresholds for mixed content.

    Returns 'zh', 'en', or 'unknown'.
    Uses a lower CJK threshold (5%) than file-level detection (10%)
    because individual chunks in mixed-language content may have
    varying ratios.
    """
    if not text or not text.strip():
        return "unknown"
    ratio = get_chinese_ratio(text)
    if ratio > 0.05:
        return "zh"
    elif ratio < 0.01:
        return "en"
    else:
        # 1-5% CJK at chunk level: likely English with some CJK terms
        return "en"


def is_chinese(text: str) -> bool:
    """Quick check: does text contain significant Chinese characters?

    Returns True if the text has enough CJK characters to be considered
    Chinese content (>5% CJK ratio). Useful for quick guards like
    skipping spellcheck on Chinese text.
    """
    if not text:
        return False
    return get_chinese_ratio(text) > 0.05

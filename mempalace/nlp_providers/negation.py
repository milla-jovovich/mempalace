"""
negation.py -- Detect negation preceding keyword matches.

Pure Python, zero dependencies. Checks for "not", "never", "no", "don't",
"won't", "can't", "isn't", "aren't", "wasn't", "doesn't", "didn't",
"neither", "nor", "without" within a window before a keyword match.
"""

import re
from typing import List, Tuple

NEGATION_CUES = [
    "not",
    "no",
    "never",
    "neither",
    "nor",
    "don't",
    "doesn't",
    "didn't",
    "won't",
    "wouldn't",
    "can't",
    "cannot",
    "isn't",
    "aren't",
    "wasn't",
    "weren't",
    "haven't",
    "hasn't",
    "hadn't",
    "shouldn't",
    "couldn't",
    "mustn't",
]

# Also match contracted forms without apostrophe
_NEGATION_SET = set(NEGATION_CUES) | {
    "dont",
    "doesnt",
    "didnt",
    "wont",
    "wouldnt",
    "cant",
    "isnt",
    "arent",
    "wasnt",
    "werent",
    "havent",
    "hasnt",
    "hadnt",
    "shouldnt",
    "couldnt",
    "mustnt",
    "without",
    "none",
}

# Pre-compiled pattern for tokenizing
_WORD_RE = re.compile(r"\b[\w']+\b")


def is_negated(text: str, position: int, window: int = 5) -> bool:
    """
    Check if a keyword match at `position` is negated.

    Looks for negation cues within `window` tokens before the keyword.

    Args:
        text: The full text string.
        position: Character offset where the keyword match begins.
        window: Number of tokens before the keyword to check (default 5).

    Returns:
        True if a negation cue is found before the keyword within the window.
    """
    # Extract text before the keyword
    prefix = text[:position].lower()

    # Tokenize the prefix, take last N tokens
    tokens = _WORD_RE.findall(prefix)
    check_tokens = tokens[-window:] if len(tokens) >= window else tokens

    return any(t in _NEGATION_SET for t in check_tokens)


def score_with_negation(text: str, markers: list) -> Tuple[float, List[str]]:
    """
    Score text against regex markers, subtracting negated matches.

    Returns (score, matched_keywords) where negated matches reduce score.
    """
    text_lower = text.lower()
    score = 0.0
    keywords = []

    for marker in markers:
        for match in re.finditer(marker, text_lower):
            if is_negated(text_lower, match.start()):
                score -= 0.5  # Negated match reduces score
            else:
                score += 1.0
                matched = match.group(0) if match.group(0) else marker
                keywords.append(matched)

    return max(0.0, score), list(set(keywords))

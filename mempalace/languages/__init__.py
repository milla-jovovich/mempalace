"""
Language data aggregator for mempalace i18n support.

Each language module (en.py, ru.py, ...) provides the same set of exports:
  - PERSON_VERB_PATTERNS: list of regex patterns for person detection
  - PROJECT_VERB_PATTERNS: list of regex patterns for project detection
  - PRONOUN_PATTERNS: list of regex patterns for pronoun proximity
  - ENTITY_STOPWORDS: set of words to exclude from entity candidates
  - EMOTION_SIGNALS: dict of keyword -> emotion code
  - FLAG_SIGNALS: dict of keyword -> flag code
  - TOPIC_STOPWORDS: set of stop words for topic extraction
  - DECISION_WORDS: set of words signaling important sentences

To add a new language:
  1. Create a new file (e.g., de.py) following the same structure as en.py
  2. Import it below and add to the merge lists
"""

from mempalace.languages import en, ru

# All registered language modules — add new languages here
_LANGUAGES = [en, ru]

# === Entity Detection (merged) ===

PERSON_VERB_PATTERNS = []
PROJECT_VERB_PATTERNS = []
PRONOUN_PATTERNS = []
ENTITY_STOPWORDS = set()

for _lang in _LANGUAGES:
    PERSON_VERB_PATTERNS.extend(_lang.PERSON_VERB_PATTERNS)
    PROJECT_VERB_PATTERNS.extend(_lang.PROJECT_VERB_PATTERNS)
    PRONOUN_PATTERNS.extend(_lang.PRONOUN_PATTERNS)
    ENTITY_STOPWORDS.update(_lang.ENTITY_STOPWORDS)

# === AAAK Dialect (merged) ===

EMOTION_SIGNALS = {}
FLAG_SIGNALS = {}
TOPIC_STOPWORDS = set()
DECISION_WORDS = set()

for _lang in _LANGUAGES:
    EMOTION_SIGNALS.update(_lang.EMOTION_SIGNALS)
    FLAG_SIGNALS.update(_lang.FLAG_SIGNALS)
    TOPIC_STOPWORDS.update(_lang.TOPIC_STOPWORDS)
    DECISION_WORDS.update(_lang.DECISION_WORDS)

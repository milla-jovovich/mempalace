"""i18n — Language dictionaries for MemPalace.

Usage:
    from mempalace.i18n import load_lang, t

    load_lang("fr")           # load French
    print(t("cli.mine_start", path="/docs"))  # "Extraction de /docs..."
    print(t("terms.wing"))    # "aile"
    print(t("aaak.instruction"))  # AAAK compression instruction in French

Each locale JSON may include an ``entity`` section with patterns used by
``mempalace.entity_detector``. See ``get_entity_patterns`` for the merge rules
and the README section "Adding a new language" for the schema.
"""

import json
from pathlib import Path

_LANG_DIR = Path(__file__).parent
_strings: dict = {}
_current_lang: str = "en"

# Cache: tuple(langs) -> merged entity pattern dict
_entity_cache: dict = {}


def available_languages() -> list[str]:
    """Return list of available language codes."""
    return sorted(p.stem for p in _LANG_DIR.glob("*.json"))


def load_lang(lang: str = "en") -> dict:
    """Load a language dictionary. Falls back to English if not found."""
    global _strings, _current_lang
    lang_file = _LANG_DIR / f"{lang}.json"
    if not lang_file.exists():
        lang_file = _LANG_DIR / "en.json"
        lang = "en"
    _strings = json.loads(lang_file.read_text(encoding="utf-8"))
    _current_lang = lang
    return _strings


def t(key: str, **kwargs) -> str:
    """Get a translated string by dotted key. Supports {var} interpolation.

    t("cli.mine_complete", closets=5, drawers=20)
    → "Done. 5 closets, 20 drawers created."
    """
    if not _strings:
        load_lang("en")
    parts = key.split(".", 1)
    if len(parts) == 2:
        section, name = parts
        val = _strings.get(section, {}).get(name, key)
    else:
        val = _strings.get(key, key)
    if kwargs and isinstance(val, str):
        try:
            val = val.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return val


def current_lang() -> str:
    """Return current language code."""
    return _current_lang


def get_regex() -> dict:
    """Return the regex patterns for the current language.

    Keys: topic_pattern, stop_words, quote_pattern, action_pattern.
    Returns empty dict if no regex section in the language file.
    """
    if not _strings:
        load_lang("en")
    return _strings.get("regex", {})


def _load_entity_section(lang: str) -> dict:
    """Load the raw entity section for one language. Returns {} if missing."""
    lang_file = _LANG_DIR / f"{lang}.json"
    if not lang_file.exists():
        return {}
    try:
        data = json.loads(lang_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data.get("entity", {}) or {}


def get_entity_patterns(languages=("en",)) -> dict:
    """Return merged entity detection patterns for the requested languages.

    Entity detection patterns live under each locale's ``entity`` section.
    This function merges them into a single dict for consumption by
    ``mempalace.entity_detector``.

    Merge rules:
      - List fields (person_verb_patterns, pronoun_patterns, dialogue_patterns,
        project_verb_patterns) are concatenated in the order of ``languages``,
        with duplicates removed while preserving first occurrence.
      - ``stopwords`` is the set union across all languages, returned as a
        sorted list.
      - ``candidate_patterns`` and ``multi_word_patterns`` are returned as
        lists (one per language) since they use different character classes;
        callers run each pattern independently and union the matches.
      - ``direct_address_pattern`` is returned as a list of per-language
        alternation patterns (not concatenated — each is applied separately).

    If ``languages`` is empty or no requested language declares entity data,
    English is used as a fallback so callers always get a working config.
    """
    if not languages:
        languages = ("en",)
    key = tuple(languages)
    if key in _entity_cache:
        return _entity_cache[key]

    candidate_patterns: list[str] = []
    multi_word_patterns: list[str] = []
    person_verbs: list[str] = []
    pronouns: list[str] = []
    dialogue: list[str] = []
    direct_address: list[str] = []
    project_verbs: list[str] = []
    stopwords: set = set()

    found_any = False
    for lang in languages:
        section = _load_entity_section(lang)
        if not section:
            continue
        found_any = True
        if section.get("candidate_pattern"):
            candidate_patterns.append(section["candidate_pattern"])
        if section.get("multi_word_pattern"):
            multi_word_patterns.append(section["multi_word_pattern"])
        if section.get("direct_address_pattern"):
            direct_address.append(section["direct_address_pattern"])
        person_verbs.extend(section.get("person_verb_patterns", []))
        pronouns.extend(section.get("pronoun_patterns", []))
        dialogue.extend(section.get("dialogue_patterns", []))
        project_verbs.extend(section.get("project_verb_patterns", []))
        stopwords.update(w.lower() for w in section.get("stopwords", []))

    if not found_any:
        # Fallback: load English directly
        section = _load_entity_section("en")
        if section.get("candidate_pattern"):
            candidate_patterns.append(section["candidate_pattern"])
        if section.get("multi_word_pattern"):
            multi_word_patterns.append(section["multi_word_pattern"])
        if section.get("direct_address_pattern"):
            direct_address.append(section["direct_address_pattern"])
        person_verbs.extend(section.get("person_verb_patterns", []))
        pronouns.extend(section.get("pronoun_patterns", []))
        dialogue.extend(section.get("dialogue_patterns", []))
        project_verbs.extend(section.get("project_verb_patterns", []))
        stopwords.update(w.lower() for w in section.get("stopwords", []))

    merged = {
        "candidate_patterns": candidate_patterns,
        "multi_word_patterns": multi_word_patterns,
        "person_verb_patterns": _dedupe(person_verbs),
        "pronoun_patterns": _dedupe(pronouns),
        "dialogue_patterns": _dedupe(dialogue),
        "direct_address_patterns": direct_address,
        "project_verb_patterns": _dedupe(project_verbs),
        "stopwords": sorted(stopwords),
    }
    _entity_cache[key] = merged
    return merged


def _dedupe(items: list) -> list:
    """Remove duplicates while preserving first-occurrence order."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


# Auto-load English on import
load_lang("en")

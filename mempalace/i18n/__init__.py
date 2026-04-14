"""i18n — Language dictionaries for MemPalace.

Usage:
    from mempalace.i18n import load_lang, t

    load_lang("fr")           # load French
    print(t("cli.mine_start", path="/docs"))  # "Extraction de /docs..."
    print(t("terms.wing"))    # "aile"
    print(t("aaak.instruction"))  # AAAK compression instruction in French
"""

import json
from pathlib import Path

_LANG_DIR = Path(__file__).parent
_strings: dict = {}
_current_lang: str = "en"


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


# Auto-load English on import
load_lang("en")

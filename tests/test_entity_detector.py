"""Tests for mempalace.entity_detector."""

import contextlib
import json
import os
from pathlib import Path
from unittest.mock import patch

from mempalace.entity_detector import (
    PROSE_EXTENSIONS,
    STOPWORDS,
    _print_entity_list,
    classify_entity,
    confirm_entities,
    detect_entities,
    extract_candidates,
    scan_for_detection,
    score_entity,
)


# ── extract_candidates ──────────────────────────────────────────────────


def test_extract_candidates_finds_frequent_names():
    text = "Riley said hello. Riley laughed. Riley smiled. Riley waved."
    result = extract_candidates(text)
    assert "Riley" in result
    assert result["Riley"] >= 3


def test_extract_candidates_ignores_stopwords():
    # "The" appears many times but is a stopword
    text = "The The The The The The"
    result = extract_candidates(text)
    assert "The" not in result


def test_extract_candidates_requires_min_frequency():
    text = "Riley said hi. Devon waved."
    result = extract_candidates(text)
    # Each name appears only once, below the threshold of 3
    assert "Riley" not in result
    assert "Devon" not in result


def test_extract_candidates_finds_multi_word_names():
    # Multi-word names need 3+ occurrences and no stopwords
    text = "Claude Code is great. Claude Code rocks. Claude Code works. Claude Code rules."
    result = extract_candidates(text)
    assert "Claude Code" in result


def test_extract_candidates_empty_text():
    result = extract_candidates("")
    assert result == {}


# ── score_entity ────────────────────────────────────────────────────────


def test_score_entity_person_verbs():
    text = "Riley said hello. Riley asked why. Riley told me."
    lines = text.splitlines()
    result = score_entity("Riley", text, lines)
    assert result["person_score"] > 0
    assert len(result["person_signals"]) > 0


def test_score_entity_project_verbs():
    text = "We are building ChromaDB. We deployed ChromaDB. Install ChromaDB."
    lines = text.splitlines()
    result = score_entity("ChromaDB", text, lines)
    assert result["project_score"] > 0
    assert len(result["project_signals"]) > 0


def test_score_entity_dialogue_markers():
    text = "Riley: Hey, how are you?\nRiley: I'm fine."
    lines = text.splitlines()
    result = score_entity("Riley", text, lines)
    assert result["person_score"] > 0


def test_score_entity_code_ref():
    text = "Check out ChromaDB.py for details. Also ChromaDB.js is good."
    lines = text.splitlines()
    result = score_entity("ChromaDB", text, lines)
    assert result["project_score"] > 0


def test_score_entity_no_signals():
    text = "Nothing interesting here at all."
    lines = text.splitlines()
    result = score_entity("Riley", text, lines)
    assert result["person_score"] == 0
    assert result["project_score"] == 0


# ── classify_entity ─────────────────────────────────────────────────────


def test_classify_entity_no_signals_gives_uncertain():
    scores = {
        "person_score": 0,
        "project_score": 0,
        "person_signals": [],
        "project_signals": [],
    }
    result = classify_entity("Foo", 10, scores)
    assert result["type"] == "uncertain"
    assert result["name"] == "Foo"


def test_classify_entity_strong_project():
    scores = {
        "person_score": 0,
        "project_score": 10,
        "person_signals": [],
        "project_signals": ["project verb (5x)", "code file reference (2x)"],
    }
    result = classify_entity("ChromaDB", 5, scores)
    assert result["type"] == "project"


def test_classify_entity_strong_person_needs_two_signal_types():
    scores = {
        "person_score": 10,
        "project_score": 0,
        "person_signals": [
            "dialogue marker (3x)",
            "'Riley ...' action (4x)",
        ],
        "project_signals": [],
    }
    result = classify_entity("Riley", 8, scores)
    assert result["type"] == "person"


def test_classify_entity_pronoun_only_is_uncertain():
    scores = {
        "person_score": 8,
        "project_score": 0,
        "person_signals": ["pronoun nearby (4x)"],
        "project_signals": [],
    }
    result = classify_entity("Riley", 5, scores)
    assert result["type"] == "uncertain"


def test_classify_entity_mixed_signals():
    scores = {
        "person_score": 5,
        "project_score": 5,
        "person_signals": ["pronoun nearby (2x)"],
        "project_signals": ["project verb (2x)"],
    }
    result = classify_entity("Lantern", 5, scores)
    assert result["type"] == "uncertain"
    assert "mixed signals" in result["signals"][-1]


# ── detect_entities (integration) ───────────────────────────────────────


def test_detect_entities_with_person_file(tmp_path):
    f = tmp_path / "notes.txt"
    content = "\n".join(
        [
            "Riley said hello today.",
            "Riley asked about the project.",
            "Riley told me she was happy.",
            "Riley: I think we should go.",
            "Hey Riley, thanks for the help.",
            "Riley laughed and smiled.",
            "Riley decided to join.",
            "Riley pushed the change.",
        ]
    )
    f.write_text(content)
    result = detect_entities([f])
    all_names = [e["name"] for cat in result.values() for e in cat]
    assert "Riley" in all_names


def test_detect_entities_with_project_file(tmp_path):
    f = tmp_path / "readme.txt"
    # "ChromaDB" has uppercase+lowercase mix but extract_candidates looks
    # for /[A-Z][a-z]{1,19}/ — so we need a name that matches that regex.
    # Use "Lantern" which matches the capitalized-word pattern.
    content = "\n".join(
        [
            "The Lantern project is great.",
            "Building Lantern was fun.",
            "We deployed Lantern today.",
            "Install Lantern with pip install Lantern.",
            "Check Lantern.py for the source.",
            "Lantern v2 is faster.",
        ]
    )
    f.write_text(content)
    result = detect_entities([f])
    all_names = [e["name"] for cat in result.values() for e in cat]
    assert "Lantern" in all_names


def test_detect_entities_empty_files(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("")
    result = detect_entities([f])
    assert result == {"people": [], "projects": [], "uncertain": []}


def test_detect_entities_handles_missing_file(tmp_path):
    missing = tmp_path / "nonexistent.txt"
    result = detect_entities([missing])
    assert result == {"people": [], "projects": [], "uncertain": []}


def test_detect_entities_respects_max_files(tmp_path):
    files = []
    for i in range(5):
        f = tmp_path / f"file{i}.txt"
        f.write_text("Riley said hello. " * 10)
        files.append(f)
    # max_files=2 should only read 2 files
    result = detect_entities(files, max_files=2)
    # Should still work without error
    assert isinstance(result, dict)


# ── scan_for_detection ──────────────────────────────────────────────────


def test_scan_for_detection_finds_prose(tmp_path):
    (tmp_path / "notes.md").write_text("hello")
    (tmp_path / "data.txt").write_text("world")
    (tmp_path / "code.py").write_text("import os")
    files = scan_for_detection(str(tmp_path))
    extensions = {os.path.splitext(str(f))[1] for f in files}
    # Prose files should be found
    assert ".md" in extensions or ".txt" in extensions


def test_scan_for_detection_skips_git_dir(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config.txt").write_text("git config")
    (tmp_path / "readme.md").write_text("hello")
    files = scan_for_detection(str(tmp_path))
    file_strs = [str(f) for f in files]
    assert not any(".git" in f for f in file_strs)


# ── module-level constants ──────────────────────────────────────────────


def test_stopwords_contains_common_words():
    assert "the" in STOPWORDS
    assert "import" in STOPWORDS
    assert "class" in STOPWORDS


def test_prose_extensions():
    assert ".txt" in PROSE_EXTENSIONS
    assert ".md" in PROSE_EXTENSIONS


# ── _print_entity_list ─────────────────────────────────────────────────


def test_print_entity_list_with_entities(capsys):
    entities = [
        {"name": "Alice", "confidence": 0.9, "signals": ["dialogue marker (3x)"]},
        {"name": "Bob", "confidence": 0.5, "signals": []},
    ]
    _print_entity_list(entities, "PEOPLE")
    out = capsys.readouterr().out
    assert "PEOPLE" in out
    assert "Alice" in out
    assert "Bob" in out


def test_print_entity_list_empty(capsys):
    _print_entity_list([], "PEOPLE")
    out = capsys.readouterr().out
    assert "none detected" in out


# ── confirm_entities ───────────────────────────────────────────────────


def test_confirm_entities_yes_mode():
    detected = {
        "people": [{"name": "Alice", "confidence": 0.9, "signals": ["test"]}],
        "projects": [{"name": "Acme", "confidence": 0.8, "signals": ["test"]}],
        "uncertain": [{"name": "Foo", "confidence": 0.4, "signals": ["test"]}],
    }
    result = confirm_entities(detected, yes=True)
    assert result["people"] == ["Alice"]
    assert result["projects"] == ["Acme"]


def test_confirm_entities_accept_all():
    detected = {
        "people": [{"name": "Alice", "confidence": 0.9, "signals": ["test"]}],
        "projects": [],
        "uncertain": [],
    }
    with patch("builtins.input", side_effect=["", "n"]):
        result = confirm_entities(detected, yes=False)
    assert "Alice" in result["people"]


def test_confirm_entities_edit_reclassify_uncertain():
    detected = {
        "people": [],
        "projects": [],
        "uncertain": [
            {"name": "Foo", "confidence": 0.4, "signals": ["test"]},
            {"name": "Bar", "confidence": 0.4, "signals": ["test"]},
        ],
    }
    with patch(
        "builtins.input",
        side_effect=[
            "edit",  # choice
            "p",  # Foo -> person
            "s",  # Bar -> skip
            "",  # no removals from people
            "",  # no removals from projects
            "n",  # don't add missing
        ],
    ):
        result = confirm_entities(detected, yes=False)
    assert "Foo" in result["people"]
    assert "Bar" not in result["people"]
    assert "Bar" not in result["projects"]


def test_confirm_entities_add_mode():
    detected = {
        "people": [],
        "projects": [],
        "uncertain": [],
    }
    with patch(
        "builtins.input",
        side_effect=[
            "add",  # choice = add
            "NewPerson",  # name
            "p",  # person
            "NewProj",  # name
            "r",  # project
            "",  # stop adding
        ],
    ):
        result = confirm_entities(detected, yes=False)
    assert "NewPerson" in result["people"]
    assert "NewProj" in result["projects"]


# ── scan_for_detection fallback ────────────────────────────────────────


def test_scan_for_detection_fallback_to_all_readable(tmp_path):
    """When fewer than 3 prose files, falls back to include all readable files."""
    (tmp_path / "one.md").write_text("hello")
    (tmp_path / "two.txt").write_text("world")
    # Only 2 prose files, so it should also include code files
    (tmp_path / "code.py").write_text("import os")
    (tmp_path / "app.js").write_text("console.log()")
    files = scan_for_detection(str(tmp_path))
    extensions = {os.path.splitext(str(f))[1] for f in files}
    assert ".py" in extensions or ".js" in extensions


def test_scan_for_detection_max_files(tmp_path):
    """Caps to max_files."""
    for i in range(20):
        (tmp_path / f"note{i}.md").write_text(f"content {i}")
    files = scan_for_detection(str(tmp_path), max_files=5)
    assert len(files) <= 5


# ── multi-language infra ───────────────────────────────────────────────


@contextlib.contextmanager
def _temp_locale(locale_code: str, entity_section: dict):
    """Context manager that drops a locale JSON into mempalace/i18n/ for the test body.

    Cleans up the file and clears every cache that depends on locale data on exit,
    even if the test fails or the entity section is invalid.

    Note: writes into the real mempalace/i18n/ directory. If a test process is
    SIGKILLed mid-test the orphan zz-test-*.json file will break test_all_languages_load
    on the next run (the fixture lacks the required terms/cli/aaak sections).
    Recover with `rm mempalace/i18n/zz-test-*.json`.
    """
    from mempalace import i18n
    from mempalace import entity_detector

    locale_path = Path(i18n.__file__).parent / f"{locale_code}.json"
    if locale_path.exists():
        raise RuntimeError(f"Test locale {locale_code} collides with an existing file")

    payload = {
        "lang": locale_code,
        "label": locale_code,
        "terms": {},
        "cli": {},
        "aaak": {"instruction": "test"},
        "entity": entity_section,
    }
    locale_path.write_text(json.dumps(payload), encoding="utf-8")

    def _clear_caches():
        i18n._entity_cache.clear()
        entity_detector._build_patterns.cache_clear()
        entity_detector._pronoun_re.cache_clear()
        entity_detector._get_stopwords.cache_clear()

    _clear_caches()
    try:
        yield locale_path
    finally:
        try:
            locale_path.unlink()
        except OSError:
            pass
        _clear_caches()


def test_extract_candidates_default_languages_is_english_only():
    """Default languages tuple = ('en',) — accented names dropped (as today)."""
    text = "João said hi. João laughed. João waved. João decided."
    result = extract_candidates(text)  # default ("en",)
    assert "João" not in result


def test_extract_candidates_with_extra_locale_picks_up_new_charset():
    """A locale with a Latin+diacritics candidate_pattern catches accented names."""
    locale = {
        "candidate_pattern": "[A-ZÀ-Ú][a-zà-ÿ]{1,19}",
        "multi_word_pattern": "[A-ZÀ-Ú][a-zà-ÿ]+(?:\\s+[A-ZÀ-Ú][a-zà-ÿ]+)+",
        "person_verb_patterns": [],
        "pronoun_patterns": [],
        "dialogue_patterns": [],
        "project_verb_patterns": [],
        "stopwords": [],
    }
    with _temp_locale("zz-test-latin", locale):
        text = "João said hi. João laughed. João waved. João decided."
        result = extract_candidates(text, languages=("en", "zz-test-latin"))
        assert "João" in result
        assert result["João"] >= 3


def test_extract_candidates_with_cyrillic_locale():
    """A locale with a Cyrillic candidate_pattern catches Russian names."""
    locale = {
        "candidate_pattern": "[А-ЯЁ][а-яё]{1,19}",
        "multi_word_pattern": "[А-ЯЁ][а-яё]+(?:\\s+[А-ЯЁ][а-яё]+)+",
        "person_verb_patterns": [],
        "pronoun_patterns": [],
        "dialogue_patterns": [],
        "project_verb_patterns": [],
        "stopwords": [],
    }
    with _temp_locale("zz-test-cyrillic", locale):
        text = "Иван сказал привет. Иван засмеялся. Иван помахал. Иван решил."
        result = extract_candidates(text, languages=("en", "zz-test-cyrillic"))
        assert "Иван" in result


def test_score_entity_unions_person_verbs_across_languages():
    """A non-English person-verb pattern fires when its locale is enabled."""
    locale = {
        "candidate_pattern": "[A-Z][a-z]{1,19}",
        "multi_word_pattern": "[A-Z][a-z]+(?:\\s+[A-Z][a-z]+)+",
        "person_verb_patterns": [
            "\\b{name}\\s+disse\\b",
            "\\b{name}\\s+falou\\b",
            "\\b{name}\\s+riu\\b",
        ],
        "pronoun_patterns": [],
        "dialogue_patterns": [],
        "project_verb_patterns": [],
        "stopwords": [],
    }
    with _temp_locale("zz-test-verbs", locale):
        text = "Maria disse oi. Maria falou. Maria riu."
        lines = text.splitlines()

        en_only = score_entity("Maria", text, lines, languages=("en",))
        multi = score_entity("Maria", text, lines, languages=("en", "zz-test-verbs"))

        assert multi["person_score"] > en_only["person_score"]
        assert any("action" in s for s in multi["person_signals"])


def test_get_entity_patterns_unknown_lang_falls_back_to_english():
    """Asking for a non-existent language returns English defaults."""
    from mempalace.i18n import get_entity_patterns

    patterns = get_entity_patterns(("zz-does-not-exist",))
    assert len(patterns["stopwords"]) > 0
    assert patterns["candidate_patterns"]  # English fallback


def test_get_entity_patterns_dedupes_across_overlapping_languages():
    """Loading ('en', 'en') doesn't double-count patterns or stopwords."""
    from mempalace.i18n import get_entity_patterns

    single = get_entity_patterns(("en",))
    doubled = get_entity_patterns(("en", "en"))
    assert len(doubled["person_verb_patterns"]) == len(single["person_verb_patterns"])
    assert len(doubled["stopwords"]) == len(single["stopwords"])


def test_build_patterns_cache_is_keyed_by_language():
    """Same name with different language tuples yields different compiled sets."""
    from mempalace.entity_detector import _build_patterns

    locale = {
        "candidate_pattern": "[A-Z][a-z]+",
        "multi_word_pattern": "[A-Z][a-z]+(?:\\s+[A-Z][a-z]+)+",
        "person_verb_patterns": ["\\b{name}\\s+ranxx\\b"],
        "pronoun_patterns": [],
        "dialogue_patterns": [],
        "project_verb_patterns": [],
        "stopwords": [],
    }
    with _temp_locale("zz-test-cache", locale):
        en_patterns = _build_patterns("Sam", ("en",))
        multi_patterns = _build_patterns("Sam", ("en", "zz-test-cache"))
        assert len(multi_patterns["person_verbs"]) > len(en_patterns["person_verbs"])


def test_normalize_langs_handles_string_input():
    """Passing a bare string instead of a tuple still works."""
    from mempalace.entity_detector import _normalize_langs

    assert _normalize_langs("en") == ("en",)
    assert _normalize_langs(["en", "pt-br"]) == ("en", "pt-br")
    assert _normalize_langs(None) == ("en",)
    assert _normalize_langs(()) == ("en",)


def test_config_entity_languages_defaults_to_english(tmp_path, monkeypatch):
    """MempalaceConfig.entity_languages defaults to ['en'] with no config file."""
    from mempalace.config import MempalaceConfig

    monkeypatch.delenv("MEMPALACE_ENTITY_LANGUAGES", raising=False)
    monkeypatch.delenv("MEMPAL_ENTITY_LANGUAGES", raising=False)
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.entity_languages == ["en"]


def test_config_entity_languages_from_env(tmp_path, monkeypatch):
    """Env var overrides config file."""
    from mempalace.config import MempalaceConfig

    monkeypatch.setenv("MEMPALACE_ENTITY_LANGUAGES", "en,pt-br,ru")
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg.entity_languages == ["en", "pt-br", "ru"]


def test_config_set_entity_languages_persists(tmp_path, monkeypatch):
    """set_entity_languages writes to disk and is read back."""
    from mempalace.config import MempalaceConfig

    monkeypatch.delenv("MEMPALACE_ENTITY_LANGUAGES", raising=False)
    monkeypatch.delenv("MEMPAL_ENTITY_LANGUAGES", raising=False)
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    cfg.set_entity_languages(["en", "pt-br"])
    cfg2 = MempalaceConfig(config_dir=str(tmp_path))
    assert cfg2.entity_languages == ["en", "pt-br"]


def test_config_set_entity_languages_empty_falls_back_to_english(tmp_path, monkeypatch):
    """An empty list normalizes to ['en']."""
    from mempalace.config import MempalaceConfig

    monkeypatch.delenv("MEMPALACE_ENTITY_LANGUAGES", raising=False)
    monkeypatch.delenv("MEMPAL_ENTITY_LANGUAGES", raising=False)
    cfg = MempalaceConfig(config_dir=str(tmp_path))
    result = cfg.set_entity_languages([])
    assert result == ["en"]
    assert cfg.entity_languages == ["en"]


# ── boundary_chars for combining-mark scripts ─────────────────────────

# Devanagari vowel signs (matras) are Unicode Mc — not matched by \w.
# Without boundary_chars, \b truncates names like अनीता → अनीत and
# person_verb patterns never fire.  With boundary_chars, the i18n loader
# replaces \b with a script-aware lookaround, fixing both.

_DEVANAGARI_ENTITY = {
    "boundary_chars": "\\w\\u0900-\\u097F",
    "candidate_pattern": "[\\u0900-\\u097F]{2,20}",
    "multi_word_pattern": "[\\u0900-\\u097F]+(?:\\s+[\\u0900-\\u097F]+)+",
    "person_verb_patterns": [
        "\\b{name}\\s+ने\\s+कहा\\b",
        "\\b{name}\\s+हँसा\\b",
    ],
    "pronoun_patterns": ["\\bवह\\b", "\\bउसने\\b"],
    "dialogue_patterns": ["^{name}:\\s"],
    "direct_address_pattern": "\\bनमस्ते\\s+{name}\\b",
    "project_verb_patterns": [],
    "stopwords": ["यह", "वह", "और", "का", "के", "की"],
}


def test_devanagari_candidate_extraction_with_boundary_chars():
    """Names ending in matras are extracted in full with boundary_chars."""
    with _temp_locale("zz-test-hindi", _DEVANAGARI_ENTITY):
        text = "अनीता ने कहा। अनीता हँसा। अनीता सोचा। अनीता बोला।"
        result = extract_candidates(text, languages=("en", "zz-test-hindi"))
        assert "अनीता" in result, f"expected अनीता in {result}"
        assert result["अनीता"] >= 3


def test_devanagari_candidate_without_boundary_chars_truncates():
    """Without boundary_chars, a matra-ending name gets truncated."""
    locale_no_boundary = dict(_DEVANAGARI_ENTITY)
    del locale_no_boundary["boundary_chars"]
    with _temp_locale("zz-test-hindi-no-b", locale_no_boundary):
        text = "अनीता ने कहा। अनीता हँसा। अनीता सोचा।"
        result = extract_candidates(text, languages=("en", "zz-test-hindi-no-b"))
        # Without boundary_chars, \b splits on the matra — full name won't appear
        assert "अनीता" not in result


def test_devanagari_person_verb_fires_with_boundary_chars():
    """Hindi person-verb patterns fire when boundary_chars extends \\b."""
    with _temp_locale("zz-test-hindi", _DEVANAGARI_ENTITY):
        text = "राज ने कहा कुछ। राज हँसा।"
        lines = text.splitlines()
        scores = score_entity("राज", text, lines, languages=("en", "zz-test-hindi"))
        assert scores["person_score"] > 0, f"expected person_score > 0, got {scores}"
        assert any("action" in s for s in scores["person_signals"])


def test_devanagari_person_verb_silent_without_boundary_chars():
    """Without boundary_chars, Hindi person verbs don't fire."""
    locale_no_boundary = dict(_DEVANAGARI_ENTITY)
    del locale_no_boundary["boundary_chars"]
    with _temp_locale("zz-test-hindi-no-b", locale_no_boundary):
        text = "राज ने कहा कुछ। राज हँसा।"
        lines = text.splitlines()
        scores = score_entity("राज", text, lines, languages=("en", "zz-test-hindi-no-b"))
        assert scores["person_score"] == 0


def test_boundary_chars_english_regression():
    """English patterns (no boundary_chars) still work identically."""
    text = "Riley said hello. Riley laughed. Riley smiled. Riley waved."
    result = extract_candidates(text, languages=("en",))
    assert "Riley" in result
    assert result["Riley"] >= 3

"""Tests for mempalace.entity_detector."""

import os
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

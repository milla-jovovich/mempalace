from pathlib import Path

from mempalace.entity_detector import (
    extract_candidates,
    score_entity,
    classify_entity,
    detect_entities,
    scan_for_detection,
)


def _write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_extract_candidates_finds_proper_nouns():
    text = "Alice went to the store. Alice bought milk. Alice came home. Bob was waiting."
    candidates = extract_candidates(text)
    assert "Alice" in candidates
    assert candidates["Alice"] >= 3


def test_extract_candidates_filters_stopwords():
    text = "The The The This This This That That That"
    candidates = extract_candidates(text)
    assert "The" not in candidates
    assert "This" not in candidates


def test_extract_candidates_finds_multi_word():
    text = "Claude Code is great. Claude Code is useful. Claude Code works."
    candidates = extract_candidates(text)
    assert "Claude Code" in candidates


def test_extract_candidates_min_frequency():
    text = "Alice appeared once. Bob appeared once."
    candidates = extract_candidates(text)
    assert "Alice" not in candidates


def test_score_entity_person_verbs():
    text = "Alice said hello. Alice laughed. Alice smiled."
    lines = text.splitlines()
    scores = score_entity("Alice", text, lines)
    assert scores["person_score"] > 0


def test_score_entity_project_verbs():
    text = "Building MemPalace now. Deploy MemPalace soon. The MemPalace architecture."
    lines = text.splitlines()
    scores = score_entity("MemPalace", text, lines)
    assert scores["project_score"] > 0


def test_classify_entity_person():
    scores = {
        "person_score": 15,
        "project_score": 0,
        "person_signals": ["dialogue marker (3x)", "action (2x)"],
        "project_signals": [],
    }
    entity = classify_entity("Alice", 10, scores)
    assert entity["type"] == "person"
    assert entity["confidence"] > 0.5


def test_classify_entity_project():
    scores = {
        "person_score": 0,
        "project_score": 12,
        "person_signals": [],
        "project_signals": ["project verb (4x)"],
    }
    entity = classify_entity("MemPalace", 8, scores)
    assert entity["type"] == "project"


def test_classify_entity_uncertain_no_signals():
    scores = {
        "person_score": 0,
        "project_score": 0,
        "person_signals": [],
        "project_signals": [],
    }
    entity = classify_entity("Foo", 5, scores)
    assert entity["type"] == "uncertain"


def test_classify_entity_pronoun_only_downgraded():
    scores = {
        "person_score": 8,
        "project_score": 0,
        "person_signals": ["pronoun nearby (4x)"],
        "project_signals": [],
    }
    entity = classify_entity("Foo", 5, scores)
    assert entity["type"] == "uncertain"


def test_detect_entities_end_to_end(tmp_dir):
    text = (
        "Alice said hello to Bob. Alice laughed at Bob's joke. "
        "Alice asked Bob a question. Alice told Bob the answer. "
        "Hey Alice, thanks Alice, hi Alice.\n"
    ) * 3
    f = tmp_dir / "chat.txt"
    f.write_text(text)
    detected = detect_entities([f], max_files=1)
    all_names = [
        e["name"] for e in detected["people"] + detected["projects"] + detected["uncertain"]
    ]
    assert "Alice" in all_names


def test_scan_for_detection_prefers_prose(tmp_dir):
    _write_file(tmp_dir / "notes.md", "# Notes\n" * 20)
    _write_file(tmp_dir / "app.py", "def main(): pass\n" * 20)
    files = scan_for_detection(str(tmp_dir))
    extensions = {f.suffix for f in files}
    assert ".md" in extensions

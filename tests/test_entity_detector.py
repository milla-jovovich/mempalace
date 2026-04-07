"""Tests for entity_detector.py — entity detection from content and directory structure."""

import textwrap

import pytest

from mempalace.entity_detector import (
    STOPWORDS,
    classify_entity,
    detect_directory_projects,
    detect_entities,
    extract_candidates,
    scan_for_detection,
    score_entity,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def repos_dir(tmp_path):
    """Create a temporary directory with several git repos as children."""
    for name in ["acme-dashboard", "acme-chess", "acme-notes"]:
        repo = tmp_path / name
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "README.md").write_text(f"# {name}\nA project.")

    # Non-git directory (should be ignored)
    plain_dir = tmp_path / "random-notes"
    plain_dir.mkdir()
    (plain_dir / "notes.txt").write_text("some notes")

    # Hidden directory (should be ignored)
    hidden = tmp_path / ".hidden-repo"
    hidden.mkdir()
    (hidden / ".git").mkdir()

    # SKIP_DIRS entry (should be ignored)
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (node_modules / ".git").mkdir()

    return tmp_path


@pytest.fixture
def prose_dir(tmp_path):
    """Create a directory with prose files containing entity-like content."""
    content = textwrap.dedent("""\
        Kai said the auth migration was critical. Kai pushed the fix.
        Kai told Maya about the deadline. Maya replied with the timeline.
        Maya asked about the deployment schedule.
        Hey Kai, thanks for the review.
        Building Orion is the top priority. We shipped Orion last week.
        The Orion architecture needs refactoring. Deploy Orion to staging.
        Kai said Orion v2 is ready.
    """)
    md = tmp_path / "notes.md"
    md.write_text(content)
    return tmp_path


# ─────────────────────────────────────────────────────────────────────────────
# detect_directory_projects
# ─────────────────────────────────────────────────────────────────────────────


class TestDetectDirectoryProjects:
    def test_finds_git_repos(self, repos_dir):
        projects = detect_directory_projects(str(repos_dir))
        names = [p["name"] for p in projects]
        assert "acme-dashboard" in names
        assert "acme-chess" in names
        assert "acme-notes" in names

    def test_skips_non_git_directories(self, repos_dir):
        projects = detect_directory_projects(str(repos_dir))
        names = [p["name"] for p in projects]
        assert "random-notes" not in names

    def test_skips_hidden_directories(self, repos_dir):
        projects = detect_directory_projects(str(repos_dir))
        names = [p["name"] for p in projects]
        assert ".hidden-repo" not in names

    def test_skips_skip_dirs(self, repos_dir):
        projects = detect_directory_projects(str(repos_dir))
        names = [p["name"] for p in projects]
        assert "node_modules" not in names

    def test_high_confidence(self, repos_dir):
        projects = detect_directory_projects(str(repos_dir))
        for p in projects:
            assert p["confidence"] >= 0.9
            assert p["type"] == "project"
            assert "git repository directory" in p["signals"]

    def test_returns_empty_for_nonexistent_dir(self, tmp_path):
        result = detect_directory_projects(str(tmp_path / "nonexistent"))
        assert result == []

    def test_returns_empty_for_dir_without_repos(self, tmp_path):
        (tmp_path / "just-a-folder").mkdir()
        (tmp_path / "another-folder").mkdir()
        result = detect_directory_projects(str(tmp_path))
        assert result == []

    def test_detects_git_file_worktrees(self, tmp_path):
        """Git worktrees use a .git file instead of a .git directory."""
        repo = tmp_path / "worktree-repo"
        repo.mkdir()
        (repo / ".git").write_text("gitdir: /some/path/.git/worktrees/worktree-repo")
        projects = detect_directory_projects(str(tmp_path))
        names = [p["name"] for p in projects]
        assert "worktree-repo" in names


# ─────────────────────────────────────────────────────────────────────────────
# detect_entities with base_dir
# ─────────────────────────────────────────────────────────────────────────────


class TestDetectEntitiesWithBaseDir:
    def test_includes_directory_projects(self, repos_dir):
        result = detect_entities([], base_dir=str(repos_dir))
        project_names = [p["name"] for p in result["projects"]]
        assert "acme-dashboard" in project_names
        assert "acme-chess" in project_names
        assert "acme-notes" in project_names

    def test_merges_content_and_directory_projects(self, repos_dir, prose_dir):
        # Add a repo with same name as a content-detected project
        orion_repo = repos_dir / "Orion"
        orion_repo.mkdir()
        (orion_repo / ".git").mkdir()

        # Create prose file in repos_dir
        content = textwrap.dedent("""\
            Building Orion is key. The Orion pipeline is fast.
            Ship Orion today. Deploy Orion to prod.
            The Orion system handles auth. Install Orion now.
        """)
        (repos_dir / "notes.md").write_text(content)

        files = scan_for_detection(str(repos_dir))
        result = detect_entities(files, base_dir=str(repos_dir))
        project_names = [p["name"] for p in result["projects"]]

        # Orion should appear only once (no duplicates)
        assert project_names.count("Orion") <= 1
        # Directory repos should be present
        assert "acme-dashboard" in project_names

    def test_without_base_dir_no_directory_projects(self, repos_dir):
        """Without base_dir, no directory-based projects are detected."""
        result = detect_entities([])
        assert result["projects"] == []

    def test_directory_projects_sorted_by_confidence(self, repos_dir):
        result = detect_entities([], base_dir=str(repos_dir))
        confidences = [p["confidence"] for p in result["projects"]]
        assert confidences == sorted(confidences, reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# extract_candidates and stopwords
# ─────────────────────────────────────────────────────────────────────────────


class TestStopwords:
    @pytest.mark.parametrize(
        "word",
        ["Code", "Typescript", "Javascript", "Node", "Plugin", "Icon", "Low", "Visual", "Figma"],
    )
    def test_generic_tech_words_in_stopwords(self, word):
        """Words from issue #97 that should be filtered as stopwords."""
        assert word.lower() in STOPWORDS

    def test_extract_candidates_filters_stopwords(self):
        # Repeat each word 5+ times to pass the frequency filter
        text = " ".join(["Code"] * 10 + ["Typescript"] * 10 + ["Node"] * 10)
        candidates = extract_candidates(text)
        assert "Code" not in candidates
        assert "Typescript" not in candidates
        assert "Node" not in candidates

    def test_extract_candidates_keeps_real_entities(self):
        text = " ".join(["Kai"] * 5 + ["Orion"] * 5 + ["Maya"] * 5)
        candidates = extract_candidates(text)
        assert "Kai" in candidates
        assert "Orion" in candidates
        assert "Maya" in candidates


# ─────────────────────────────────────────────────────────────────────────────
# score_entity and classify_entity
# ─────────────────────────────────────────────────────────────────────────────


class TestScoreAndClassify:
    def test_person_with_strong_signals(self):
        text = (
            "Kai said hello. Kai pushed the fix. Hey Kai, thanks for the review.\n"
            "Kai told Maya about it. She was happy."
        )
        lines = text.splitlines()
        scores = score_entity("Kai", text, lines)
        assert scores["person_score"] > 0
        assert scores["person_score"] > scores["project_score"]

    def test_project_with_strong_signals(self):
        text = (
            "Building Orion is critical. Deploy Orion today.\n"
            "The Orion pipeline runs fast. Ship Orion to prod.\n"
            "Install Orion via pip install Orion."
        )
        lines = text.splitlines()
        scores = score_entity("Orion", text, lines)
        assert scores["project_score"] > 0
        assert scores["project_score"] > scores["person_score"]

    def test_classify_uncertain_no_signals(self):
        result = classify_entity(
            "Unknown",
            5,
            {"person_score": 0, "project_score": 0, "person_signals": [], "project_signals": []},
        )
        assert result["type"] == "uncertain"


# ─────────────────────────────────────────────────────────────────────────────
# scan_for_detection
# ─────────────────────────────────────────────────────────────────────────────


class TestScanForDetection:
    def test_finds_prose_files(self, tmp_path):
        (tmp_path / "readme.md").write_text("# Hello")
        (tmp_path / "notes.txt").write_text("Some notes")
        (tmp_path / "data.csv").write_text("a,b,c")
        files = scan_for_detection(str(tmp_path))
        extensions = {f.suffix for f in files}
        assert ".md" in extensions
        assert ".txt" in extensions

    def test_skips_git_dir(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("git config")
        (tmp_path / "readme.md").write_text("# Hello")
        files = scan_for_detection(str(tmp_path))
        for f in files:
            assert ".git" not in str(f)

    def test_falls_back_to_readable_files(self, tmp_path):
        """When fewer than 3 prose files, includes readable code files too."""
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "readme.md").write_text("# Hello")
        files = scan_for_detection(str(tmp_path))
        extensions = {f.suffix for f in files}
        assert ".py" in extensions
        assert ".md" in extensions

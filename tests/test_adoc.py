from pathlib import Path

from mempalace.miner import preprocess_adoc, scan_project


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def scanned_files(project_root: Path, **kwargs):
    files = scan_project(str(project_root), **kwargs)
    return sorted(path.relative_to(project_root).as_posix() for path in files)


class TestAdocScan:
    def test_scan_discovers_adoc_files(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        write_file(
            project_root / "docs" / "lecture.adoc",
            "== Authentication\n\nUse the /auth endpoint.\n" * 5,
        )
        write_file(
            project_root / "src" / "app.py",
            "def main():\n    print('hello')\n" * 5,
        )
        assert "docs/lecture.adoc" in scanned_files(project_root)
        assert "src/app.py" in scanned_files(project_root)


class TestPreprocessAdoc:
    def test_strips_block_delimiters(self):
        content = (
            "== Section\n"
            "\n"
            "Some text.\n"
            "\n"
            "----\n"
            "code here\n"
            "----\n"
            "\n"
            "More text.\n"
        )
        result = preprocess_adoc(content)
        assert "----" not in result
        assert "code here" in result
        assert "Some text." in result
        assert "More text." in result

    def test_strips_various_block_delimiters(self):
        content = (
            "====\n"
            "Admonition text.\n"
            "====\n"
            "\n"
            "....\n"
            "Literal block.\n"
            "....\n"
            "\n"
            "++++\n"
            "Passthrough.\n"
            "++++\n"
            "\n"
            "****\n"
            "Sidebar.\n"
            "****\n"
        )
        result = preprocess_adoc(content)
        assert "====" not in result
        assert "...." not in result
        assert "++++" not in result
        assert "****" not in result
        assert "Admonition text." in result
        assert "Literal block." in result
        assert "Passthrough." in result
        assert "Sidebar." in result

    def test_strips_attribute_definitions(self):
        content = (
            ":gls_prefix:\n"
            ":exercise_path: ~/course/labs/{gls_lab_script}\n"
            ":experimental:\n"
            "\n"
            "== Section Title\n"
            "\n"
            "Body text here.\n"
        )
        result = preprocess_adoc(content)
        assert ":gls_prefix:" not in result
        assert ":exercise_path:" not in result
        assert ":experimental:" not in result
        assert "== Section Title" in result
        assert "Body text here." in result

    def test_strips_block_attributes(self):
        content = (
            "== Code Example\n"
            "\n"
            "[source,python]\n"
            "print('hello')\n"
            "\n"
            "[subs=+quotes]\n"
            "some code\n"
            "\n"
            "[role='Checklist']\n"
            "== Instructions\n"
        )
        result = preprocess_adoc(content)
        assert "[source,python]" not in result
        assert "[subs=+quotes]" not in result
        assert "[role='Checklist']" not in result
        assert "print('hello')" in result
        assert "== Instructions" in result

    def test_preserves_non_attribute_colons(self):
        content = "Time: 10 minutes\nNote: important detail\n"
        result = preprocess_adoc(content)
        assert "Time: 10 minutes" in result
        assert "Note: important detail" in result

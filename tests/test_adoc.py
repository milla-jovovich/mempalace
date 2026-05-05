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

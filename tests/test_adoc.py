from pathlib import Path

from mempalace.miner import chunk_adoc, preprocess_adoc, scan_project


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
        content = "== Section\n\nSome text.\n\n----\ncode here\n----\n\nMore text.\n"
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

    def test_strips_include_directives(self):
        content = (
            "include::{gls_snippets_dir}/before_you_begin.adoc[]\n"
            "\n"
            "Body text.\n"
            "\n"
            "ifdef::backend-html5[]\n"
            "HTML only.\n"
            "endif::backend-html5[]\n"
            "\n"
            "ifndef::ebook[]\n"
            "Not ebook.\n"
            "endif::[]\n"
        )
        result = preprocess_adoc(content)
        assert "include::" not in result
        assert "ifdef::" not in result
        assert "ifndef::" not in result
        assert "endif::" not in result
        assert "Body text." in result

    def test_strips_callout_markers(self):
        content = (
            "data_in: Input[Artifact], <1>\n"
            "data_out: Output[Artifact] <2>\n"
            "regular line with no callout\n"
        )
        result = preprocess_adoc(content)
        assert "<1>" not in result
        assert "<2>" not in result
        assert "data_in: Input[Artifact]," in result
        assert "regular line with no callout" in result

    def test_simplifies_inline_macros(self):
        content = (
            "Click btn:[Create run] to start.\n"
            "Go to menu:Actions[Create run].\n"
            "Use pass:a,n[{gls_res_outcomes}] for outcomes.\n"
        )
        result = preprocess_adoc(content)
        assert "btn:[" not in result
        assert "Create run" in result
        assert "menu:" not in result
        assert "Actions > Create run" in result
        assert "pass:a,n[" not in result

    def test_preserves_section_headers(self):
        content = "== Section One\n\n=== Subsection\n\nBody text.\n"
        result = preprocess_adoc(content)
        assert "== Section One" in result
        assert "=== Subsection" in result

    def test_preserves_comments(self):
        content = (
            "// ARCH REVIEW: Does the API support OCI connections?\n"
            "// DEVELOPER: Leave as is for now.\n"
            "Body text.\n"
        )
        result = preprocess_adoc(content)
        assert "ARCH REVIEW" in result
        assert "DEVELOPER" in result


class TestChunkAdoc:
    def test_splits_on_section_headers(self):
        content = (
            "== Authentication\n"
            "\n"
            "Use the /auth endpoint to authenticate.\n"
            "\n"
            "== User Endpoints\n"
            "\n"
            "The /users endpoint returns a list of users.\n"
            "\n"
            "== Admin Endpoints\n"
            "\n"
            "Admin-only endpoints require elevated permissions.\n"
        )
        chunks = chunk_adoc(content, "api.adoc")
        assert len(chunks) == 3
        assert "Authentication" in chunks[0]["content"]
        assert "User Endpoints" in chunks[1]["content"]
        assert "Admin Endpoints" in chunks[2]["content"]

    def test_section_header_included_in_chunk(self):
        content = "== My Section\n\nBody text here.\n"
        chunks = chunk_adoc(content, "test.adoc")
        assert len(chunks) == 1
        assert chunks[0]["content"].startswith("== My Section")

    def test_sequential_chunk_indices(self):
        content = "== A\n\nText A.\n\n== B\n\nText B.\n\n== C\n\nText C.\n"
        chunks = chunk_adoc(content, "test.adoc")
        indices = [c["chunk_index"] for c in chunks]
        assert indices == [0, 1, 2]

    def test_oversized_section_gets_sub_chunked(self):
        long_body = "This is a long paragraph of text. " * 100  # ~3400 chars
        content = f"== Big Section\n\n{long_body}\n"
        chunks = chunk_adoc(content, "test.adoc")
        assert len(chunks) > 1
        assert "== Big Section" in chunks[0]["content"]

    def test_content_before_first_header_becomes_chunk(self):
        content = "Document preamble text here.\n\n== First Section\n\nSection body.\n"
        chunks = chunk_adoc(content, "test.adoc")
        assert len(chunks) == 2
        assert "preamble" in chunks[0]["content"]
        assert "First Section" in chunks[1]["content"]

    def test_tiny_sections_are_skipped(self):
        content = (
            "== Real Section\n"
            "\n"
            "Enough text to pass the minimum chunk size threshold for filtering.\n"
            "\n"
            "== Tiny\n"
            "\n"
            "x\n"
        )
        chunks = chunk_adoc(content, "test.adoc")
        contents = " ".join(c["content"] for c in chunks)
        assert "Real Section" in contents

    def test_handles_mixed_header_levels(self):
        content = (
            "== Top Level\n"
            "\n"
            "Top body.\n"
            "\n"
            "=== Sub Level\n"
            "\n"
            "Sub body.\n"
            "\n"
            "== Another Top\n"
            "\n"
            "Another body.\n"
        )
        chunks = chunk_adoc(content, "test.adoc")
        assert len(chunks) == 3

    def test_empty_content_returns_empty(self):
        assert chunk_adoc("", "test.adoc") == []
        assert chunk_adoc("   \n\n  ", "test.adoc") == []

    def test_no_headers_falls_back_to_paragraph_chunking(self):
        content = "Just plain text without any AsciiDoc headers.\n" * 30
        chunks = chunk_adoc(content, "test.adoc")
        assert len(chunks) >= 1
        assert all("chunk_index" in c for c in chunks)

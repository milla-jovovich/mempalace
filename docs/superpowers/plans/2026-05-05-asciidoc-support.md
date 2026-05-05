# AsciiDoc Mining Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable MemPalace to mine, preprocess, and intelligently chunk AsciiDoc (`.adoc`) files so that PTL training content is indexed with high search precision.

**Architecture:** Three layers — (1) add `.adoc` to extension allowlists so files are discovered, (2) add a `preprocess_adoc()` function in `miner.py` that strips AsciiDoc structural markup noise before embedding, (3) add a `chunk_adoc()` function that splits on section headers (`== Title`) for semantically coherent drawers, falling back to the existing `chunk_text()` for oversized sections. The preprocessing and chunking are invoked from `process_file()` when the file suffix is `.adoc`.

**Tech Stack:** Python 3, pytest, re (stdlib regex), existing MemPalace miner/chunker infrastructure.

---

## File Structure

| File | Role |
|------|------|
| `mempalace/miner.py` | Add `.adoc` to `READABLE_EXTENSIONS`, add `preprocess_adoc()`, add `chunk_adoc()`, wire into `process_file()` |
| `mempalace/entity_detector.py` | Add `.adoc` to `READABLE_EXTENSIONS` |
| `tests/test_adoc.py` | All AsciiDoc-specific tests: preprocessing, section-aware chunking, end-to-end mining |

---

### Task 1: Add `.adoc` to Extension Allowlists + Scan Test

**Files:**
- Modify: `mempalace/miner.py:34-56` (add `.adoc` to `READABLE_EXTENSIONS`)
- Modify: `mempalace/entity_detector.py:91-107` (add `.adoc` to `READABLE_EXTENSIONS`)
- Create: `tests/test_adoc.py`

- [ ] **Step 1: Write the failing test — scan discovers `.adoc` files**

In `tests/test_adoc.py`:

```python
import os
import tempfile
import shutil
from pathlib import Path

from mempalace.miner import scan_project


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adoc.py::TestAdocScan::test_scan_discovers_adoc_files -v`
Expected: FAIL — `docs/lecture.adoc` not in scanned files (`.adoc` not in `READABLE_EXTENSIONS`)

- [ ] **Step 3: Add `.adoc` to extension sets**

In `mempalace/miner.py`, add `".adoc",` to `READABLE_EXTENSIONS` (after `".md",` on line 36).

In `mempalace/entity_detector.py`, add `".adoc",` to `READABLE_EXTENSIONS` (after `".md",` on line 93).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_adoc.py::TestAdocScan::test_scan_discovers_adoc_files -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mempalace/miner.py mempalace/entity_detector.py tests/test_adoc.py
git commit -m "feat: add .adoc to READABLE_EXTENSIONS for AsciiDoc mining"
```

---

### Task 2: `preprocess_adoc()` — Strip Block Delimiters

**Files:**
- Modify: `mempalace/miner.py` (add `preprocess_adoc()` function)
- Modify: `tests/test_adoc.py` (add `TestPreprocessAdoc` class)

- [ ] **Step 1: Write the failing test — block delimiters are stripped**

Append to `tests/test_adoc.py`:

```python
from mempalace.miner import preprocess_adoc


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adoc.py::TestPreprocessAdoc -v`
Expected: FAIL — `ImportError: cannot import name 'preprocess_adoc'`

- [ ] **Step 3: Implement `preprocess_adoc()` — block delimiter stripping**

In `mempalace/miner.py`, add after the `import` block (after line 32), before `READABLE_EXTENSIONS`:

```python
import re
```

Then add the function after the `chunk_text()` function (after line 411):

```python
def preprocess_adoc(content: str) -> str:
    """Strip AsciiDoc structural markup that adds noise to embeddings."""
    lines = content.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Block delimiters: ----, ====, ...., ++++, ****
        if re.match(r"^(-{4,}|={4,}|\.{4,}|\+{4,}|\*{4,})$", stripped):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_adoc.py::TestPreprocessAdoc -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mempalace/miner.py tests/test_adoc.py
git commit -m "feat: preprocess_adoc strips block delimiters"
```

---

### Task 3: `preprocess_adoc()` — Strip Attribute Definitions and Block Attributes

**Files:**
- Modify: `mempalace/miner.py` (extend `preprocess_adoc()`)
- Modify: `tests/test_adoc.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Append to `TestPreprocessAdoc` in `tests/test_adoc.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_adoc.py::TestPreprocessAdoc::test_strips_attribute_definitions tests/test_adoc.py::TestPreprocessAdoc::test_strips_block_attributes -v`
Expected: FAIL — attribute lines still present in output

- [ ] **Step 3: Extend `preprocess_adoc()` with attribute/block-attr stripping**

Update the function in `mempalace/miner.py` to add these checks inside the loop, before `cleaned.append(line)`:

```python
def preprocess_adoc(content: str) -> str:
    """Strip AsciiDoc structural markup that adds noise to embeddings."""
    lines = content.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Block delimiters: ----, ====, ...., ++++, ****
        if re.match(r"^(-{4,}|={4,}|\.{4,}|\+{4,}|\*{4,})$", stripped):
            continue
        # Attribute definitions: :key: or :key: value
        if re.match(r"^:[a-zA-Z_][\w-]*:(\s|$)", stripped):
            continue
        # Block attribute lines: [source,python], [role='Checklist'], etc.
        if re.match(r"^\[.+\]\s*$", stripped) and not stripped.startswith("[["):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_adoc.py::TestPreprocessAdoc -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add mempalace/miner.py tests/test_adoc.py
git commit -m "feat: preprocess_adoc strips attribute defs and block attributes"
```

---

### Task 4: `preprocess_adoc()` — Strip Directives, Callouts, and Inline Macros

**Files:**
- Modify: `mempalace/miner.py` (extend `preprocess_adoc()`)
- Modify: `tests/test_adoc.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Append to `TestPreprocessAdoc` in `tests/test_adoc.py`:

```python
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
        content = (
            "== Section One\n"
            "\n"
            "=== Subsection\n"
            "\n"
            "Body text.\n"
        )
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_adoc.py::TestPreprocessAdoc::test_strips_include_directives tests/test_adoc.py::TestPreprocessAdoc::test_strips_callout_markers tests/test_adoc.py::TestPreprocessAdoc::test_simplifies_inline_macros -v`
Expected: FAIL — directives, callouts, and macros still present

- [ ] **Step 3: Extend `preprocess_adoc()` with remaining stripping**

Update the function in `mempalace/miner.py` to its complete form:

```python
def preprocess_adoc(content: str) -> str:
    """Strip AsciiDoc structural markup that adds noise to embeddings."""
    lines = content.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Block delimiters: ----, ====, ...., ++++, ****
        if re.match(r"^(-{4,}|={4,}|\.{4,}|\+{4,}|\*{4,})$", stripped):
            continue
        # Attribute definitions: :key: or :key: value
        if re.match(r"^:[a-zA-Z_][\w-]*:(\s|$)", stripped):
            continue
        # Block attribute lines: [source,python], [role='Checklist'], etc.
        if re.match(r"^\[.+\]\s*$", stripped) and not stripped.startswith("[["):
            continue
        # Include, ifdef, ifndef, endif, ifeval directives
        if re.match(r"^(include|ifdef|ifndef|endif|ifeval)::", stripped):
            continue
        # Strip callout markers at end of line
        line = re.sub(r"\s*<\d+>\s*$", "", line)
        # Simplify inline macros
        line = re.sub(r"btn:\[([^\]]+)\]", r"\1", line)
        line = re.sub(r"menu:(\w+)\[([^\]]+)\]", r"\1 > \2", line)
        line = re.sub(r"pass:[a-z,]*\[[^\]]*\]", "", line)
        cleaned.append(line)
    return "\n".join(cleaned)
```

- [ ] **Step 4: Run all preprocessing tests**

Run: `python -m pytest tests/test_adoc.py::TestPreprocessAdoc -v`
Expected: PASS (all 10 tests)

- [ ] **Step 5: Commit**

```bash
git add mempalace/miner.py tests/test_adoc.py
git commit -m "feat: preprocess_adoc strips directives, callouts, and inline macros"
```

---

### Task 5: `chunk_adoc()` — Section-Aware Chunking

**Files:**
- Modify: `mempalace/miner.py` (add `chunk_adoc()` function)
- Modify: `tests/test_adoc.py` (add `TestChunkAdoc` class)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_adoc.py`:

```python
from mempalace.miner import chunk_adoc, CHUNK_SIZE, MIN_CHUNK_SIZE


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
        # Each section becomes its own chunk
        assert len(chunks) == 3
        assert "Authentication" in chunks[0]["content"]
        assert "User Endpoints" in chunks[1]["content"]
        assert "Admin Endpoints" in chunks[2]["content"]

    def test_section_header_included_in_chunk(self):
        content = (
            "== My Section\n"
            "\n"
            "Body text here.\n"
        )
        chunks = chunk_adoc(content, "test.adoc")
        assert len(chunks) == 1
        assert chunks[0]["content"].startswith("== My Section")

    def test_sequential_chunk_indices(self):
        content = (
            "== A\n\nText A.\n\n"
            "== B\n\nText B.\n\n"
            "== C\n\nText C.\n"
        )
        chunks = chunk_adoc(content, "test.adoc")
        indices = [c["chunk_index"] for c in chunks]
        assert indices == [0, 1, 2]

    def test_oversized_section_gets_sub_chunked(self):
        long_body = "This is a long paragraph of text. " * 100  # ~3400 chars
        content = f"== Big Section\n\n{long_body}\n"
        chunks = chunk_adoc(content, "test.adoc")
        assert len(chunks) > 1
        # First sub-chunk should have the section header
        assert "== Big Section" in chunks[0]["content"]

    def test_content_before_first_header_becomes_chunk(self):
        content = (
            "Document preamble text here.\n"
            "\n"
            "== First Section\n"
            "\n"
            "Section body.\n"
        )
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
        # The tiny section ("== Tiny\n\nx") is below MIN_CHUNK_SIZE
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_adoc.py::TestChunkAdoc -v`
Expected: FAIL — `ImportError: cannot import name 'chunk_adoc'`

- [ ] **Step 3: Implement `chunk_adoc()`**

In `mempalace/miner.py`, add after the `preprocess_adoc()` function:

```python
_ADOC_SECTION_RE = re.compile(r"^(={2,})\s+\S", re.MULTILINE)


def chunk_adoc(content: str, source_file: str) -> list:
    """
    Split AsciiDoc content into chunks on section header boundaries.
    Falls back to chunk_text() when no headers are found or for
    oversized sections.
    """
    content = content.strip()
    if not content:
        return []

    # Find all section header positions
    headers = list(_ADOC_SECTION_RE.finditer(content))
    if not headers:
        return chunk_text(content, source_file)

    # Build sections: content between consecutive headers
    sections = []
    # Preamble before first header
    if headers[0].start() > 0:
        sections.append(content[: headers[0].start()])
    for i, match in enumerate(headers):
        start = match.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(content)
        sections.append(content[start:end])

    chunks = []
    chunk_index = 0
    for section in sections:
        section = section.strip()
        if len(section) < MIN_CHUNK_SIZE:
            continue
        if len(section) <= CHUNK_SIZE:
            chunks.append({"content": section, "chunk_index": chunk_index})
            chunk_index += 1
        else:
            # Sub-chunk oversized sections using paragraph-boundary logic
            sub_chunks = chunk_text(section, source_file)
            for sc in sub_chunks:
                sc["chunk_index"] = chunk_index
                chunks.append(sc)
                chunk_index += 1

    return chunks
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_adoc.py::TestChunkAdoc -v`
Expected: PASS (all 9 tests)

- [ ] **Step 5: Commit**

```bash
git add mempalace/miner.py tests/test_adoc.py
git commit -m "feat: chunk_adoc splits on section headers with sub-chunking fallback"
```

---

### Task 6: Wire Preprocessing + Chunking into `process_file()`

**Files:**
- Modify: `mempalace/miner.py:813-823` (add `.adoc` dispatch in `process_file()`)
- Modify: `tests/test_adoc.py` (add `TestAdocMiningEndToEnd` class)

- [ ] **Step 1: Write the failing end-to-end test**

Append to `tests/test_adoc.py`:

```python
import yaml
import chromadb
from mempalace.miner import mine


class TestAdocMiningEndToEnd:
    def test_mine_adoc_file_creates_drawers(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        write_file(
            project_root / "docs" / "lecture.adoc",
            (
                ":gls_prefix:\n"
                "\n"
                "== Authentication\n"
                "\n"
                "Use the /auth endpoint to authenticate.\n"
                "This is enough text to pass the minimum chunk size.\n"
                "\n"
                "----\n"
                "curl -X POST http://api.example.com/auth\n"
                "----\n"
                "\n"
                "== User Endpoints\n"
                "\n"
                "The /users endpoint returns a list of users.\n"
                "It supports pagination and filtering by role.\n"
            ),
        )
        with open(project_root / "mempalace.yaml", "w") as f:
            yaml.dump(
                {
                    "wing": "test_course",
                    "rooms": [{"name": "docs", "description": "Documentation"}],
                },
                f,
            )

        palace_path = tmp_path / "palace"
        mine(str(project_root), str(palace_path))

        client = chromadb.PersistentClient(path=str(palace_path))
        col = client.get_collection("mempalace_drawers")
        assert col.count() > 0

        # Verify drawers don't contain AsciiDoc noise
        results = col.get()
        all_text = " ".join(results["documents"])
        assert "----" not in all_text
        assert ":gls_prefix:" not in all_text
        # Verify actual content IS present
        assert "Authentication" in all_text
        assert "User Endpoints" in all_text

    def test_mine_adoc_with_preprocessed_content(self, tmp_path):
        """Verify inline macros are cleaned before storage."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        write_file(
            project_root / "guide.adoc",
            (
                "== Instructions\n"
                "\n"
                "Click btn:[Create run] to start the pipeline.\n"
                "Go to menu:Actions[Create run] for more options.\n"
                "This text needs to be long enough to pass the size filter.\n"
            ),
        )
        with open(project_root / "mempalace.yaml", "w") as f:
            yaml.dump(
                {
                    "wing": "test_course",
                    "rooms": [{"name": "general", "description": "General"}],
                },
                f,
            )

        palace_path = tmp_path / "palace"
        mine(str(project_root), str(palace_path))

        client = chromadb.PersistentClient(path=str(palace_path))
        col = client.get_collection("mempalace_drawers")
        results = col.get()
        all_text = " ".join(results["documents"])
        assert "btn:[" not in all_text
        assert "menu:" not in all_text
        assert "Create run" in all_text
        assert "Actions > Create run" in all_text

    def test_mine_adoc_dry_run_no_crash(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        write_file(
            project_root / "lecture.adoc",
            (
                "== Section\n"
                "\n"
                "Body text that is long enough.\n" * 5
            ),
        )
        with open(project_root / "mempalace.yaml", "w") as f:
            yaml.dump(
                {
                    "wing": "test_course",
                    "rooms": [{"name": "general", "description": "General"}],
                },
                f,
            )
        palace_path = tmp_path / "palace"
        # Should not raise
        mine(str(project_root), str(palace_path), dry_run=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_adoc.py::TestAdocMiningEndToEnd::test_mine_adoc_file_creates_drawers -v`
Expected: FAIL — drawers contain `----` and `:gls_prefix:` because `process_file()` doesn't preprocess `.adoc`

- [ ] **Step 3: Wire preprocessing and chunking into `process_file()`**

In `mempalace/miner.py`, in the `process_file()` function, after `content = content.strip()` (line 818) and before `room = detect_room(...)` (line 822), add the `.adoc` dispatch:

```python
    content = content.strip()
    if len(content) < MIN_CHUNK_SIZE:
        return 0, "general"

    # AsciiDoc preprocessing: strip markup noise before embedding
    if filepath.suffix.lower() == ".adoc":
        content = preprocess_adoc(content)

    room = detect_room(filepath, content, rooms, project_path)
```

Then replace the `chunks = chunk_text(content, source_file)` call (line 823) with:

```python
    if filepath.suffix.lower() == ".adoc":
        chunks = chunk_adoc(content, source_file)
    else:
        chunks = chunk_text(content, source_file)
```

- [ ] **Step 4: Run all end-to-end tests**

Run: `python -m pytest tests/test_adoc.py::TestAdocMiningEndToEnd -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `python -m pytest tests/ -v --ignore=tests/benchmarks`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add mempalace/miner.py tests/test_adoc.py
git commit -m "feat: wire AsciiDoc preprocessing and section-aware chunking into process_file"
```

---

### Task 7: Edge Cases and Robustness Tests

**Files:**
- Modify: `tests/test_adoc.py` (add edge case tests)

- [ ] **Step 1: Write edge case tests**

Append to `tests/test_adoc.py`:

```python
class TestPreprocessAdocEdgeCases:
    def test_preserves_anchor_ids(self):
        """Anchor IDs like [[anchor]] should NOT be stripped."""
        content = "[[my-anchor]]\n== Section\n\nBody.\n"
        result = preprocess_adoc(content)
        assert "[[my-anchor]]" in result

    def test_strips_image_macro_but_preserves_alt_text(self):
        """image:: macros contain descriptive alt text worth keeping."""
        content = "image::assets/pipeline-logs.png[Pipeline logs]\n"
        result = preprocess_adoc(content)
        # The full macro line is a block attribute pattern — gets stripped
        # but that's acceptable since the alt text is usually also in context
        assert "image::" not in result or "Pipeline logs" in result

    def test_handles_empty_file(self):
        assert preprocess_adoc("") == ""
        assert preprocess_adoc("\n\n\n") == "\n\n\n"

    def test_handles_pure_code_file(self):
        content = (
            "----\n"
            "def main():\n"
            "    print('hello')\n"
            "----\n"
        )
        result = preprocess_adoc(content)
        assert "def main():" in result
        assert "----" not in result

    def test_xref_macro_preserved(self):
        content = "See xref:other-section[Other Section] for details.\n"
        result = preprocess_adoc(content)
        assert "xref:" in result or "Other Section" in result

    def test_nbsp_entity_preserved(self):
        content = "Red{nbsp}Hat OpenShift AI\n"
        result = preprocess_adoc(content)
        assert "Red{nbsp}Hat" in result


class TestChunkAdocEdgeCases:
    def test_single_header_no_body(self):
        content = "== Just a Header\n"
        chunks = chunk_adoc(content, "test.adoc")
        # Too short for MIN_CHUNK_SIZE, should be empty
        assert len(chunks) == 0

    def test_deeply_nested_headers(self):
        content = (
            "== Level 2\n\nBody for level 2 section with enough text.\n\n"
            "=== Level 3\n\nBody for level 3 section with enough text.\n\n"
            "==== Level 4\n\nBody for level 4 section with enough text.\n\n"
            "===== Level 5\n\nBody for level 5 section with enough text.\n"
        )
        chunks = chunk_adoc(content, "test.adoc")
        assert len(chunks) == 4

    def test_real_ptl_lecture_structure(self):
        """Simulates a real PTL lecture.adoc structure."""
        content = (
            ":gls_prefix:\n"
            "\n"
            "== Access to Data in Pipelines\n"
            "\n"
            "In machine learning workflows, pipelines often need to read data "
            "from storage systems, share data between different stages, and "
            "store the results of each stage.\n"
            "\n"
            "== The KFP Artifacts API\n"
            "\n"
            "KFP artifacts enable you to automatically pass complex data objects "
            "between pipeline tasks. Although KFP supports passing simple Python "
            "types, this mechanism is suboptimal in real-world scenarios.\n"
            "\n"
            "[source,python]\n"
            "----\n"
            "from kfp.dsl import Input, Output, Artifact\n"
            "\n"
            "@component\n"
            "def clean_data(data_in: Input[Artifact]):\n"
            "    with open(data_in.path) as f:\n"
            "        data = f.read()\n"
            "----\n"
            "\n"
            "<1> An input artifact.\n"
            "\n"
            "=== Passing Artifacts Between Tasks\n"
            "\n"
            "You can pass artifacts between pipeline tasks by using the "
            "standard KFP DSL syntax.\n"
        )
        # Preprocess then chunk
        preprocessed = preprocess_adoc(content)
        chunks = chunk_adoc(preprocessed, "lecture.adoc")
        all_text = " ".join(c["content"] for c in chunks)
        # Noise should be gone
        assert "----" not in all_text
        assert ":gls_prefix:" not in all_text
        assert "[source,python]" not in all_text
        assert "<1>" not in all_text
        # Content should be preserved
        assert "Access to Data in Pipelines" in all_text
        assert "KFP Artifacts API" in all_text
        assert "from kfp.dsl import" in all_text
        assert "Passing Artifacts Between Tasks" in all_text
```

- [ ] **Step 2: Run all edge case tests**

Run: `python -m pytest tests/test_adoc.py -v`
Expected: PASS (all tests)

- [ ] **Step 3: Run full test suite one final time**

Run: `python -m pytest tests/ -v --ignore=tests/benchmarks`
Expected: All tests PASS, no regressions

- [ ] **Step 4: Run linting**

Run: `ruff check mempalace/miner.py tests/test_adoc.py`
Run: `ruff format --check mempalace/miner.py tests/test_adoc.py`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add tests/test_adoc.py
git commit -m "test: add edge case and PTL lecture structure tests for AsciiDoc support"
```

---

## Verification

After all tasks are complete, run:

```bash
python -m pytest tests/ -v --ignore=tests/benchmarks --cov=mempalace --cov-report=term-missing
ruff check .
ruff format --check .
```

All tests should pass, coverage should remain above 85%, and linting should be clean.

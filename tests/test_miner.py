import os
import shutil
import tempfile
from pathlib import Path

import chromadb
import yaml

from mempalace.miner import chunk_python_ast, chunk_text, mine, scan_project


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def scanned_files(project_root: Path, **kwargs):
    files = scan_project(str(project_root), **kwargs)
    return sorted(path.relative_to(project_root).as_posix() for path in files)


def test_project_mining():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        os.makedirs(project_root / "backend")

        write_file(
            project_root / "backend" / "app.py", "def main():\n    print('hello world')\n" * 20
        )
        with open(project_root / "mempalace.yaml", "w") as f:
            yaml.dump(
                {
                    "wing": "test_project",
                    "rooms": [
                        {"name": "backend", "description": "Backend code"},
                        {"name": "general", "description": "General"},
                    ],
                },
                f,
            )

        palace_path = project_root / "palace"
        mine(str(project_root), str(palace_path))

        client = chromadb.PersistentClient(path=str(palace_path))
        col = client.get_collection("mempalace_drawers")
        assert col.count() > 0
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_respects_gitignore():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "ignored.py\ngenerated/\n")
        write_file(project_root / "src" / "app.py", "print('hello')\n" * 20)
        write_file(project_root / "ignored.py", "print('ignore me')\n" * 20)
        write_file(project_root / "generated" / "artifact.py", "print('artifact')\n" * 20)

        assert scanned_files(project_root) == ["src/app.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_respects_nested_gitignore():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "*.log\n")
        write_file(project_root / "subrepo" / ".gitignore", "tasks/\n")
        write_file(project_root / "subrepo" / "src" / "main.py", "print('main')\n" * 20)
        write_file(project_root / "subrepo" / "tasks" / "task.py", "print('task')\n" * 20)
        write_file(project_root / "subrepo" / "debug.log", "debug\n" * 20)

        assert scanned_files(project_root) == ["subrepo/src/main.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_allows_nested_gitignore_override():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "*.csv\n")
        write_file(project_root / "subrepo" / ".gitignore", "!keep.csv\n")
        write_file(project_root / "drop.csv", "a,b,c\n" * 20)
        write_file(project_root / "subrepo" / "keep.csv", "a,b,c\n" * 20)

        assert scanned_files(project_root) == ["subrepo/keep.csv"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_allows_gitignore_negation_when_parent_dir_is_visible():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "generated/*\n!generated/keep.py\n")
        write_file(project_root / "generated" / "drop.py", "print('drop')\n" * 20)
        write_file(project_root / "generated" / "keep.py", "print('keep')\n" * 20)

        assert scanned_files(project_root) == ["generated/keep.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_does_not_reinclude_file_from_ignored_directory():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "generated/\n!generated/keep.py\n")
        write_file(project_root / "generated" / "drop.py", "print('drop')\n" * 20)
        write_file(project_root / "generated" / "keep.py", "print('keep')\n" * 20)

        assert scanned_files(project_root) == []
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_disable_gitignore():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "data/\n")
        write_file(project_root / "data" / "stuff.csv", "a,b,c\n" * 20)

        assert scanned_files(project_root, respect_gitignore=False) == ["data/stuff.csv"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_include_ignored_directory():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "docs/\n")
        write_file(project_root / "docs" / "guide.md", "# Guide\n" * 20)

        assert scanned_files(project_root, include_ignored=["docs"]) == ["docs/guide.md"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_include_specific_ignored_file():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "generated/\n")
        write_file(project_root / "generated" / "drop.py", "print('drop')\n" * 20)
        write_file(project_root / "generated" / "keep.py", "print('keep')\n" * 20)

        assert scanned_files(project_root, include_ignored=["generated/keep.py"]) == [
            "generated/keep.py"
        ]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_can_include_exact_file_without_known_extension():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".gitignore", "README\n")
        write_file(project_root / "README", "hello\n" * 20)

        assert scanned_files(project_root, include_ignored=["README"]) == ["README"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_include_override_beats_skip_dirs():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".pytest_cache" / "cache.py", "print('cache')\n" * 20)

        assert scanned_files(
            project_root,
            respect_gitignore=False,
            include_ignored=[".pytest_cache"],
        ) == [".pytest_cache/cache.py"]
    finally:
        shutil.rmtree(tmpdir)


def test_scan_project_skip_dirs_still_apply_without_override():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()

        write_file(project_root / ".pytest_cache" / "cache.py", "print('cache')\n" * 20)
        write_file(project_root / "main.py", "print('main')\n" * 20)

        assert scanned_files(project_root, respect_gitignore=False) == ["main.py"]
    finally:
        shutil.rmtree(tmpdir)


# =============================================================================
# chunk_python_ast tests
# =============================================================================

# Build content long enough to exceed MIN_CHUNK_SIZE (50 chars)
_FUNC_BODY = "    pass\n" * 6  # ~54 chars when combined with def line


def _func(name: str = "my_func") -> str:
    return f"def {name}():\n{_FUNC_BODY}"


def _class_with_methods(class_name: str = "MyClass", method_names: list | None = None) -> str:
    if method_names is None:
        method_names = ["method_a", "method_b"]
    # Use real statements (not comments) so AST end_lineno covers all lines
    methods = "".join(
        f"    def {m}(self):\n" + "        x = 0\n" * 8
        for m in method_names
    )
    return f"class {class_name}:\n{methods}"


class TestChunkPythonAst:
    def test_function_produces_one_chunk(self):
        code = _func()
        chunks = chunk_python_ast(code, "example.py")
        assert len(chunks) == 1
        assert chunks[0]["symbol_type"] == "function"
        assert chunks[0]["symbol_name"] == "my_func"

    def test_class_produces_class_plus_methods(self):
        code = _class_with_methods(method_names=["alpha", "beta"])
        chunks = chunk_python_ast(code, "example.py")
        types = [c["symbol_type"] for c in chunks]
        assert types.count("class") == 1
        assert types.count("method") == 2
        assert len(chunks) == 3

    def test_symbol_metadata_fields_present(self):
        code = _func()
        chunks = chunk_python_ast(code, "example.py")
        c = chunks[0]
        assert "symbol_type" in c
        assert "symbol_name" in c
        assert "parent_symbol" in c

    def test_top_level_function_has_no_parent(self):
        chunks = chunk_python_ast(_func(), "example.py")
        assert chunks[0]["parent_symbol"] is None

    def test_method_parent_symbol_is_class_name(self):
        code = _class_with_methods("Foo", ["bar"])
        chunks = chunk_python_ast(code, "example.py")
        method_chunks = [c for c in chunks if c["symbol_type"] == "method"]
        assert len(method_chunks) == 1
        assert method_chunks[0]["parent_symbol"] == "Foo"
        assert method_chunks[0]["symbol_name"] == "bar"

    def test_syntax_error_falls_back_to_chunk_text(self):
        bad_code = "def broken(\n    # never closed\n" + "pass\n" * 30
        result = chunk_python_ast(bad_code, "bad.py")
        # Must return something (chunk_text fallback) without raising
        assert isinstance(result, list)
        for chunk in result:
            assert "symbol_type" not in chunk

    def test_module_level_only_falls_back_to_chunk_text(self):
        # Only module-level assignments — no functions or classes
        code = ("X = 1\n" * 60)
        result = chunk_python_ast(code, "constants.py")
        assert isinstance(result, list)
        # chunk_text chunks have no symbol_type
        for chunk in result:
            assert "symbol_type" not in chunk

    def test_chunk_index_is_sequential(self):
        code = _func("f1") + "\n" + _func("f2") + "\n" + _func("f3")
        chunks = chunk_python_ast(code, "multi.py")
        assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))

    def test_content_contains_symbol_source(self):
        code = _func("greet")
        chunks = chunk_python_ast(code, "greet.py")
        assert "def greet" in chunks[0]["content"]

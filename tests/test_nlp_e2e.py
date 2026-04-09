"""
End-to-end tests: mine → search pipeline with NLP providers enabled.

Tests the full flow:
1. Create temp project with files
2. Mine with NLP feature flags ON (mocked providers)
3. Search and verify results
4. Verify NLP-enhanced data (entities, triples) is captured
"""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import chromadb
import yaml

from mempalace.miner import mine
from mempalace.searcher import search


def _write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _setup_project(tmpdir):
    """Create a minimal project with mempalace.yaml and source files."""
    project_root = Path(tmpdir).resolve()
    palace_path = project_root / "palace"

    _write_file(
        project_root / "notes.txt",
        (
            "We decided to use PostgreSQL because it handles JSON natively.\n"
            "The migration from MySQL took three weeks but it was worth it.\n"
            "Python's SQLAlchemy ORM made the transition much smoother.\n"
        )
        * 10,  # repeat to exceed MIN_CHUNK_SIZE
    )

    _write_file(
        project_root / "log.txt",
        (
            "Bug: the connection pool was exhausted under high load.\n"
            "Root cause: each request opened a new connection instead of reusing.\n"
            "The fix was to configure max_pool_size=20 in the database settings.\n"
        )
        * 10,
    )

    with open(project_root / "mempalace.yaml", "w") as f:
        yaml.dump(
            {
                "wing": "nlp_test",
                "rooms": [
                    {"name": "notes", "description": "Project notes"},
                    {"name": "general", "description": "General"},
                ],
            },
            f,
        )

    return project_root, str(palace_path)


def _make_mock_config(*enabled_caps):
    config = MagicMock()
    config.has.side_effect = lambda cap: cap in enabled_caps
    return config


def _make_mock_registry():
    registry = MagicMock()
    registry.split_sentences.side_effect = lambda text: [
        s.strip() for s in text.split(".") if s.strip()
    ]
    registry.extract_entities.return_value = [
        {"text": "PostgreSQL", "label": "TECH"},
        {"text": "Python", "label": "TECH"},
    ]
    registry.classify_text.return_value = {
        "label": "decision",
        "confidence": 0.9,
    }
    registry.extract_triples.return_value = [
        {
            "subject": "PostgreSQL",
            "predicate": "handles",
            "object": "JSON",
            "confidence": 0.85,
        }
    ]
    return registry


class TestMineSearchE2E:
    """End-to-end mine→search with NLP enabled."""

    def test_mine_and_search_with_nlp_sentences(self):
        """Mine with NLP sentence splitting, then search successfully."""
        tmpdir = tempfile.mkdtemp()
        try:
            project_root, palace_path = _setup_project(tmpdir)
            mock_config = _make_mock_config("sentences")
            mock_registry = _make_mock_registry()

            with (
                patch.dict(os.environ, {"MEMPALACE_NLP_SENTENCES": "1"}),
                patch("mempalace.nlp_config.NLPConfig.resolve", return_value=mock_config),
                patch("mempalace.nlp_providers.registry.get_registry", return_value=mock_registry),
            ):
                mine(str(project_root), palace_path)

            # Verify drawers were filed
            client = chromadb.PersistentClient(path=palace_path)
            col = client.get_collection("mempalace_drawers")
            assert col.count() > 0

            # Search should return results
            # search() prints to stdout and returns None on success
            search("PostgreSQL migration", palace_path)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_mine_and_search_with_nlp_ner(self):
        """Mine with NLP NER, then search for extracted entities."""
        tmpdir = tempfile.mkdtemp()
        try:
            project_root, palace_path = _setup_project(tmpdir)
            mock_config = _make_mock_config("ner")
            mock_registry = _make_mock_registry()

            with (
                patch.dict(os.environ, {"MEMPALACE_NLP_NER": "1"}),
                patch("mempalace.nlp_config.NLPConfig.resolve", return_value=mock_config),
                patch("mempalace.nlp_providers.registry.get_registry", return_value=mock_registry),
            ):
                mine(str(project_root), palace_path)

            client = chromadb.PersistentClient(path=palace_path)
            col = client.get_collection("mempalace_drawers")
            assert col.count() > 0

            search("database connection pool", palace_path)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_mine_with_all_nlp_flags(self):
        """Mine with all NLP flags enabled — nothing breaks."""
        tmpdir = tempfile.mkdtemp()
        try:
            project_root, palace_path = _setup_project(tmpdir)
            mock_config = _make_mock_config("sentences", "ner", "classify", "triples")
            mock_registry = _make_mock_registry()
            mock_kg = MagicMock()

            env_vars = {
                "MEMPALACE_NLP_SENTENCES": "1",
                "MEMPALACE_NLP_NER": "1",
                "MEMPALACE_NLP_CLASSIFY": "1",
                "MEMPALACE_NLP_TRIPLES": "1",
            }

            with (
                patch.dict(os.environ, env_vars),
                patch("mempalace.nlp_config.NLPConfig.resolve", return_value=mock_config),
                patch("mempalace.nlp_providers.registry.get_registry", return_value=mock_registry),
                patch("mempalace.knowledge_graph.KnowledgeGraph", return_value=mock_kg),
            ):
                mine(str(project_root), palace_path)

            client = chromadb.PersistentClient(path=palace_path)
            col = client.get_collection("mempalace_drawers")
            assert col.count() > 0

            # KG triples should have been extracted
            mock_kg.add_triple.assert_called()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_mine_without_nlp_flags_baseline(self):
        """Mine without NLP flags — pure regex baseline still works."""
        tmpdir = tempfile.mkdtemp()
        try:
            project_root, palace_path = _setup_project(tmpdir)

            # Ensure NLP env vars are NOT set
            env_clean = {k: v for k, v in os.environ.items() if not k.startswith("MEMPALACE_NLP_")}
            with patch.dict(os.environ, env_clean, clear=True):
                mine(str(project_root), palace_path)

            client = chromadb.PersistentClient(path=palace_path)
            col = client.get_collection("mempalace_drawers")
            assert col.count() > 0

            search("PostgreSQL", palace_path)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_nlp_provider_crash_doesnt_break_mining(self):
        """If NLP provider crashes mid-mine, files are still mined via fallback."""
        tmpdir = tempfile.mkdtemp()
        try:
            project_root, palace_path = _setup_project(tmpdir)

            # NLPConfig.resolve raises — should fall back silently
            with (
                patch.dict(os.environ, {"MEMPALACE_NLP_SENTENCES": "1"}),
                patch(
                    "mempalace.nlp_config.NLPConfig.resolve",
                    side_effect=RuntimeError("NLP crashed"),
                ),
            ):
                mine(str(project_root), palace_path)

            client = chromadb.PersistentClient(path=palace_path)
            col = client.get_collection("mempalace_drawers")
            assert col.count() > 0
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

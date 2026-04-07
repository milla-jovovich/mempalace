"""Shared fixtures for mempalace tests."""

import json
import os

import chromadb
import pytest
import yaml

from mempalace.config import MempalaceConfig
from mempalace.palace_db import reset as reset_palace_cache


@pytest.fixture(autouse=True)
def _clean_palace_caches():
    """Reset palace_db singleton caches between tests."""
    reset_palace_cache()
    yield
    reset_palace_cache()


@pytest.fixture()
def palace_path(tmp_path):
    """Path to a temporary palace directory."""
    return str(tmp_path / "palace")


@pytest.fixture()
def config_dir(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    return d


@pytest.fixture()
def config(config_dir):
    return MempalaceConfig(config_dir=str(config_dir))


@pytest.fixture()
def palace_with_data(palace_path):
    """A palace pre-loaded with 5 diverse drawers."""
    os.makedirs(palace_path, exist_ok=True)
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_or_create_collection("mempalace_drawers")
    col.add(
        documents=[
            "We decided to use GraphQL because REST was too chatty for our mobile clients.",
            "Alice loves chess and plays every Tuesday with her club.",
            "The deployment pipeline uses Docker containers orchestrated by Kubernetes.",
            "Bug: the auth token expires too early. Fixed by extending TTL to 24 hours.",
            "Riley's first day at school was emotional for the whole family.",
        ],
        ids=["d1", "d2", "d3", "d4", "d5"],
        metadatas=[
            {"wing": "myapp", "room": "architecture", "source_file": "/src/api.py", "importance": 5},
            {"wing": "personal", "room": "hobbies", "source_file": "/notes/chess.txt", "importance": 4},
            {"wing": "myapp", "room": "devops", "source_file": "/docs/deploy.md", "importance": 3},
            {"wing": "myapp", "room": "bugs", "source_file": "/src/auth.py", "importance": 4},
            {"wing": "personal", "room": "family", "source_file": "/journal/day1.txt", "importance": 5},
        ],
    )
    return palace_path


@pytest.fixture()
def sample_project(tmp_path):
    """A mini project directory with mempalace.yaml and source files."""
    proj = tmp_path / "myproject"
    proj.mkdir()

    backend = proj / "backend"
    backend.mkdir()
    (backend / "app.py").write_text("def main():\n    print('hello world')\n" * 20)
    (backend / "utils.py").write_text("def helper():\n    return True\n" * 20)

    docs = proj / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("# My Project\nThis is a great project with docs.\n" * 20)

    (proj / "mempalace.yaml").write_text(yaml.dump({
        "wing": "myproject",
        "rooms": [
            {"name": "backend", "description": "Backend code"},
            {"name": "documentation", "description": "Docs"},
            {"name": "general", "description": "General"},
        ],
    }))

    return proj


@pytest.fixture()
def sample_convos(tmp_path):
    """A directory with sample conversation files."""
    d = tmp_path / "convos"
    d.mkdir()
    (d / "chat.txt").write_text(
        "> What is memory?\nMemory is persistence of information across sessions.\n\n"
        "> Why does it matter?\nIt enables continuity and context awareness.\n\n"
        "> How do we build it?\nWith structured storage and vector embeddings.\n\n"
        "> What about search?\nSemantic search finds related content by meaning.\n"
    )
    return d


@pytest.fixture()
def identity_file(tmp_path):
    """A temporary identity.txt file."""
    f = tmp_path / "identity.txt"
    f.write_text("I am Atlas, a personal AI for Alice.\nTraits: warm, direct.")
    return str(f)

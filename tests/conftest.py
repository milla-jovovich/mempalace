import hashlib
import math
import os
import shutil
import tempfile
from pathlib import Path

import pytest

TEST_HOME = Path(tempfile.mkdtemp(prefix="mempalace-home-"))
os.environ["HOME"] = str(TEST_HOME)
os.environ["XDG_CACHE_HOME"] = str(TEST_HOME / ".cache")
os.environ["CHROMA_TELEMETRY"] = "FALSE"


def _embed_text(text: str) -> list:
    vector = [0.0] * 8
    tokens = text.lower().split() or [text.lower()]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for index in range(len(vector)):
            vector[index] += digest[index] / 255.0

    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


import chromadb.api.types as chroma_types  # noqa: E402


class TestDefaultEmbeddingFunction(chroma_types.DefaultEmbeddingFunction):
    def __call__(self, input):
        return [_embed_text(document) for document in input]


chroma_types.DefaultEmbeddingFunction = TestDefaultEmbeddingFunction


@pytest.fixture(autouse=True)
def reset_global_config(monkeypatch):
    config_dir = Path.home() / ".mempalace"
    if config_dir.exists():
        shutil.rmtree(config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("MEMPALACE_PALACE_PATH", raising=False)
    monkeypatch.delenv("MEMPAL_PALACE_PATH", raising=False)

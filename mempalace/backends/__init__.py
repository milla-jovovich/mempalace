"""Storage backend implementations for MemPalace."""

import os

from .base import BaseCollection
from .chroma import ChromaBackend, ChromaCollection
from .lance import LanceBackend, LanceCollection

__all__ = [
    "BaseCollection",
    "ChromaBackend",
    "ChromaCollection",
    "LanceBackend",
    "LanceCollection",
    "detect_backend",
]


def detect_backend(palace_path: str) -> str:
    """Auto-detect the storage backend for an existing palace.

    Returns "lance" for LanceDB palaces, "chroma" for ChromaDB palaces,
    or "lance" as default for new palaces.
    """
    if not os.path.isdir(palace_path):
        return "lance"

    for entry in os.listdir(palace_path):
        if entry.endswith(".lance"):
            return "lance"

    if os.path.exists(os.path.join(palace_path, "chroma.sqlite3")):
        return "chroma"

    return "lance"

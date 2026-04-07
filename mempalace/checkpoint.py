"""
checkpoint.py — Crash-resilient checkpoint for mine operations.

Tracks which files have been fully processed so that interrupted mine runs
can resume without querying ChromaDB (which may be corrupted).
"""

import json
import os
from pathlib import Path
from datetime import datetime


class MineCheckpoint:
    """Tracks completed files across mine runs.

    Persisted as JSON at <palace_path>/mine-checkpoint.json.
    """

    def __init__(self, palace_path: str):
        self._path = os.path.join(palace_path, "mine-checkpoint.json")
        self._data = {"completed_files": {}, "last_updated": None}
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, "r") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

    def is_completed(self, filepath: str) -> bool:
        return filepath in self._data["completed_files"]

    def mark_completed(self, filepath: str, drawers_added: int):
        self._data["completed_files"][filepath] = {
            "drawers": drawers_added,
            "filed_at": datetime.now().isoformat(),
        }

    def save(self):
        self._data["last_updated"] = datetime.now().isoformat()
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        # Write to temp file first, then rename for atomicity
        tmp_path = self._path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp_path, self._path)

    @property
    def completed_count(self) -> int:
        return len(self._data["completed_files"])

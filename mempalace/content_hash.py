import hashlib
import json
import math
import os
from pathlib import Path


class BloomFilter:
    """Simple bloom filter for fast duplicate checking."""

    def __init__(self, capacity: int = 100000, false_positive_rate: float = 0.01):
        self.size = self._optimal_size(capacity, false_positive_rate)
        self.hash_count = self._optimal_hash_count(capacity, self.size)
        self.array = [False] * self.size

    def _optimal_size(self, n: int, p: float) -> int:
        return int(-n * math.log(p) / (math.log(2) ** 2))

    def _optimal_hash_count(self, n: int, m: int) -> int:
        return max(1, int((m / n) * math.log(2)))

    def _hashes(self, item: str) -> list:
        result = []
        for i in range(self.hash_count):
            h = hashlib.md5((item + str(i)).encode()).hexdigest()
            result.append(int(h, 16) % self.size)
        return result

    def add(self, item: str):
        for idx in self._hashes(item):
            self.array[idx] = True

    def __contains__(self, item: str) -> bool:
        return all(self.array[idx] for idx in self._hashes(item))

    def save(self, path: str):
        with open(path, "w") as f:
            json.dump(
                {"array_size": self.size, "hash_count": self.hash_count, "array": self.array}, f
            )

    @classmethod
    def load(cls, path: str) -> "BloomFilter":
        if not os.path.exists(path):
            return cls()
        with open(path, "r") as f:
            data = json.load(f)
        bf = cls.__new__(cls)
        bf.size = data["array_size"]
        bf.hash_count = data["hash_count"]
        bf.array = data["array"]
        return bf


class ContentHashDB:
    """Persistent hash database for file content."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.bloom_path = db_path + ".bloom"
        self.hashes = {}
        self._hash_set = set()
        self.bloom = BloomFilter()
        self._load()

    def _load(self):
        if os.path.exists(self.db_path):
            with open(self.db_path, "r") as f:
                self.hashes = json.load(f)
        self.hashes = {str(k): v for k, v in self.hashes.items()}
        self._hash_set = set(self.hashes.values())
        if self._hash_set and os.path.exists(self.bloom_path):
            self.bloom = BloomFilter.load(self.bloom_path)
        else:
            self.bloom = BloomFilter(capacity=max(1000, len(self._hash_set) * 2))
            for h in self._hash_set:
                self.bloom.add(h)

    def _save(self):
        with open(self.db_path, "w") as f:
            json.dump(self.hashes, f)

    def flush(self):
        """Persist bloom filter to disk. Call after batch operations."""
        self._save()
        self.bloom.save(self.bloom_path)

    def compute_hash(self, filepath: Path) -> str:
        """Compute SHA256 hash of file content."""
        h = hashlib.sha256()
        h.update(filepath.read_bytes())
        return h.hexdigest()

    def check_and_add(self, filepath: Path) -> bool:
        """Check if file content hash exists, add if not. Returns True if duplicate."""
        try:
            content_hash = self.compute_hash(filepath)
        except (OSError, IOError):
            return False

        filepath_str = str(filepath)

        if content_hash in self.bloom:
            if content_hash in self._hash_set:
                return True
            self._hash_set.add(content_hash)
            self.hashes[filepath_str] = content_hash
            return False
        else:
            self._hash_set.add(content_hash)
            self.hashes[filepath_str] = content_hash
            self.bloom.add(content_hash)
            return False

    def record(self, filepath: Path):
        """Record a file without checking (for fallback after storage check)."""
        try:
            content_hash = self.compute_hash(filepath)
        except (OSError, IOError):
            return
        filepath_str = str(filepath)
        self.hashes[filepath_str] = content_hash
        self._hash_set.add(content_hash)
        self.bloom.add(content_hash)

    def clear(self):
        self.hashes = {}
        self._hash_set = set()
        self.bloom = BloomFilter()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        if os.path.exists(self.bloom_path):
            os.remove(self.bloom_path)

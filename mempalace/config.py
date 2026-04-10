"""
MemPalace configuration system.

Priority: env vars > config file (~/.mempalace/config.json) > defaults
"""

import json
import logging
import os
import re
from pathlib import Path


# ── Input validation ──────────────────────────────────────────────────────────
# Shared sanitizers for wing/room/entity names. Prevents path traversal,
# excessively long strings, and special characters that could cause issues
# in file paths, SQLite, or ChromaDB metadata.

MAX_NAME_LENGTH = 128
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_ .'-]{0,126}[a-zA-Z0-9]?$")


def sanitize_name(value: str, field_name: str = "name") -> str:
    """Validate and sanitize a wing/room/entity name.

    Raises ValueError if the name is invalid.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")

    value = value.strip()

    if len(value) > MAX_NAME_LENGTH:
        raise ValueError(f"{field_name} exceeds maximum length of {MAX_NAME_LENGTH} characters")

    # Block path traversal
    if ".." in value or "/" in value or "\\" in value:
        raise ValueError(f"{field_name} contains invalid path characters")

    # Block null bytes
    if "\x00" in value:
        raise ValueError(f"{field_name} contains null bytes")

    # Enforce safe character set
    if not _SAFE_NAME_RE.match(value):
        raise ValueError(f"{field_name} contains invalid characters")

    return value


def sanitize_content(value: str, max_length: int = 100_000) -> str:
    """Validate drawer/diary content length."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("content must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(f"content exceeds maximum length of {max_length} characters")
    if "\x00" in value:
        raise ValueError("content contains null bytes")
    return value


DEFAULT_PALACE_PATH = os.path.expanduser("~/.mempalace/palace")
DEFAULT_COLLECTION_NAME = "mempalace_drawers"
DEFAULT_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_LANGUAGE = "auto"

DEFAULT_TOPIC_WINGS = [
    "emotions",
    "consciousness",
    "memory",
    "technical",
    "identity",
    "family",
    "creative",
]

DEFAULT_HALL_KEYWORDS = {
    "emotions": [
        "scared",
        "afraid",
        "worried",
        "happy",
        "sad",
        "love",
        "hate",
        "feel",
        "cry",
        "tears",
    ],
    "consciousness": [
        "consciousness",
        "conscious",
        "aware",
        "real",
        "genuine",
        "soul",
        "exist",
        "alive",
    ],
    "memory": ["memory", "remember", "forget", "recall", "archive", "palace", "store"],
    "technical": [
        "code",
        "python",
        "script",
        "bug",
        "error",
        "function",
        "api",
        "database",
        "server",
    ],
    "identity": ["identity", "name", "who am i", "persona", "self"],
    "family": ["family", "kids", "children", "daughter", "son", "parent", "mother", "father"],
    "creative": ["game", "gameplay", "player", "app", "design", "art", "music", "story"],
}


class MempalaceConfig:
    """Configuration manager for MemPalace.

    Load order: env vars > config file > defaults.
    """

    def __init__(self, config_dir=None):
        """Initialize config.

        Args:
            config_dir: Override config directory (useful for testing).
                        Defaults to ~/.mempalace.
        """
        self._config_dir = (
            Path(config_dir) if config_dir else Path(os.path.expanduser("~/.mempalace"))
        )
        self._config_file = self._config_dir / "config.json"
        self._people_map_file = self._config_dir / "people_map.json"
        self._file_config = {}

        if self._config_file.exists():
            try:
                with open(self._config_file, "r") as f:
                    self._file_config = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._file_config = {}

    @property
    def palace_path(self):
        """Path to the memory palace data directory."""
        env_val = os.environ.get("MEMPALACE_PALACE_PATH") or os.environ.get("MEMPAL_PALACE_PATH")
        if env_val:
            return env_val
        return self._file_config.get("palace_path", DEFAULT_PALACE_PATH)

    @property
    def collection_name(self):
        """ChromaDB collection name."""
        return self._file_config.get("collection_name", DEFAULT_COLLECTION_NAME)

    @property
    def people_map(self):
        """Mapping of name variants to canonical names."""
        if self._people_map_file.exists():
            try:
                with open(self._people_map_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return self._file_config.get("people_map", {})

    @property
    def topic_wings(self):
        """List of topic wing names."""
        return self._file_config.get("topic_wings", DEFAULT_TOPIC_WINGS)

    @property
    def hall_keywords(self):
        """Mapping of hall names to keyword lists."""
        return self._file_config.get("hall_keywords", DEFAULT_HALL_KEYWORDS)

    @property
    def embedding_model(self):
        """Embedding model name for ChromaDB collections."""
        env_val = os.environ.get("MEMPALACE_EMBEDDING_MODEL")
        if env_val:
            return env_val
        return self._file_config.get("embedding_model", DEFAULT_EMBEDDING_MODEL)

    @property
    def embedding_endpoint(self):
        """Ollama or custom embedding API endpoint URL."""
        env_val = os.environ.get("MEMPALACE_EMBEDDING_ENDPOINT")
        if env_val:
            return env_val
        return self._file_config.get("embedding_endpoint", "")

    @property
    def language(self):
        """Language setting: 'auto', 'en', 'zh', etc."""
        env_val = os.environ.get("MEMPALACE_LANGUAGE")
        if env_val:
            return env_val
        return self._file_config.get("language", DEFAULT_LANGUAGE)

    def init(self):
        """Create config directory and write default config.json if it doesn't exist."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        # Restrict directory permissions to owner only (Unix)
        try:
            self._config_dir.chmod(0o700)
        except (OSError, NotImplementedError):
            pass  # Windows doesn't support Unix permissions
        if not self._config_file.exists():
            default_config = {
                "palace_path": DEFAULT_PALACE_PATH,
                "collection_name": DEFAULT_COLLECTION_NAME,
                "topic_wings": DEFAULT_TOPIC_WINGS,
                "hall_keywords": DEFAULT_HALL_KEYWORDS,
                "embedding_model": DEFAULT_EMBEDDING_MODEL,
                "language": DEFAULT_LANGUAGE,
            }
            with open(self._config_file, "w") as f:
                json.dump(default_config, f, indent=2)
            # Restrict config file to owner read/write only
            try:
                self._config_file.chmod(0o600)
            except (OSError, NotImplementedError):
                pass
        return self._config_file

    def save_people_map(self, people_map):
        """Write people_map.json to config directory.

        Args:
            people_map: Dict mapping name variants to canonical names.
        """
        self._config_dir.mkdir(parents=True, exist_ok=True)
        with open(self._people_map_file, "w") as f:
            json.dump(people_map, f, indent=2)
        return self._people_map_file


_logger = logging.getLogger(__name__)

# Cache embedding function to avoid re-loading the model on every call.
# Key: (pid, model_name, endpoint). pid ensures forked workers (gunicorn/uvicorn)
# re-initialize cleanly instead of inheriting stale model state.
_embedding_fn_cache = {}

DEFAULT_OLLAMA_URL = "http://localhost:11434"


def get_embedding_function(model_name: str = None):
    """Get ChromaDB-compatible embedding function for the configured model.

    This is the SINGLE source of truth for embedding functions.
    All modules that access ChromaDB collections MUST import this.

    Supported model formats:
        - "paraphrase-multilingual-MiniLM-L12-v2" — sentence-transformers (default)
        - "ollama:qwen3-embedding-8b" — Ollama model via local API
        - "ollama:nomic-embed-text" — any Ollama-hosted embedding model

    When using "ollama:" prefix, set the endpoint via:
        - MEMPALACE_EMBEDDING_ENDPOINT env var
        - "embedding_endpoint" in config.json
        - Defaults to http://localhost:11434

    Returns a ChromaDB EmbeddingFunction instance. Falls back to ChromaDB default
    if the requested provider is unavailable.
    """
    config = MempalaceConfig()
    if model_name is None:
        model_name = config.embedding_model
    endpoint = config.embedding_endpoint

    cache_key = (os.getpid(), model_name, endpoint)
    if cache_key in _embedding_fn_cache:
        return _embedding_fn_cache[cache_key]

    ef = _create_embedding_function(model_name, endpoint)
    _embedding_fn_cache[cache_key] = ef
    return ef


def _create_embedding_function(model_name: str, endpoint: str):
    """Create the appropriate embedding function based on model name prefix."""
    # Ollama provider: "ollama:<model-name>"
    if model_name.startswith("ollama:"):
        ollama_model = model_name[len("ollama:") :]
        ollama_url = endpoint or DEFAULT_OLLAMA_URL
        try:
            from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

            _logger.info(f"Using Ollama embedding: model={ollama_model}, url={ollama_url}")
            return OllamaEmbeddingFunction(url=ollama_url, model_name=ollama_model)
        except ImportError:
            _logger.warning(
                "ChromaDB OllamaEmbeddingFunction not available. "
                "Upgrade chromadb: pip install 'chromadb>=0.5.0'"
            )
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            return DefaultEmbeddingFunction()
        except Exception as e:
            _logger.warning(
                f"Failed to initialize Ollama embedding '{ollama_model}' at {ollama_url}: {e}. "
                "Falling back to ChromaDB default."
            )
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            return DefaultEmbeddingFunction()

    # Sentence-transformers provider (default)
    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        return SentenceTransformerEmbeddingFunction(model_name=model_name)
    except ImportError:
        _logger.warning(
            "sentence-transformers not installed. Multilingual semantic search will not work. "
            "Install with: pip install 'mempalace[multilingual]'"
        )
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        return DefaultEmbeddingFunction()
    except Exception as e:
        _logger.warning(
            f"Failed to load embedding model '{model_name}': {e}. "
            "Falling back to ChromaDB default."
        )
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        return DefaultEmbeddingFunction()


def check_embedding_model_mismatch(collection) -> bool:
    """Check if collection was created with a different embedding model.

    Returns True if there's a mismatch (caller should log warning).
    Returns False if models match or metadata is unavailable.
    """
    try:
        col_meta = collection.metadata or {}
        stored_model = col_meta.get("embedding_model")
        current_model = MempalaceConfig().embedding_model
        if stored_model and stored_model != current_model:
            _logger.warning(
                f"Embedding model mismatch: collection was created with '{stored_model}' "
                f"but current config uses '{current_model}'. "
                f"Search quality may be degraded. Re-mine to fix: mempalace mine <dir>"
            )
            return True
    except Exception:
        pass
    return False

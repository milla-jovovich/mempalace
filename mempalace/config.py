"""
MemPalace configuration system.

Priority: env vars > config file (~/.mempalace/config.json) > defaults
"""

import json
import os
import re
from pathlib import Path


# ── Input validation ──────────────────────────────────────────────────────────
# Shared sanitizers for wing/room/entity names. Prevents path traversal,
# excessively long strings, and special characters that could cause issues
# in file paths, SQLite, or ChromaDB metadata.

MAX_NAME_LENGTH = 128
_SAFE_NAME_RE = re.compile(r"^(?:[^\W_]|[^\W_][\w .'-]{0,126}[^\W_])$")


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


def sanitize_kg_value(value: str, field_name: str = "value") -> str:
    """Validate a knowledge-graph entity name (subject or object).

    More permissive than sanitize_name — allows punctuation like commas,
    colons, and parentheses that are common in natural-language KG values.
    Only blocks null bytes and over-length strings.

    Not used for wing/room names (which have filesystem constraints) or
    predicates (which should be simple relationship identifiers).
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")

    value = value.strip()

    if len(value) > MAX_NAME_LENGTH:
        raise ValueError(f"{field_name} exceeds maximum length of {MAX_NAME_LENGTH} characters")

    if "\x00" in value:
        raise ValueError(f"{field_name} contains null bytes")

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

# ── Closet (index-layer) tunables ─────────────────────────────────────────────
# These defaults MUST match the current module-level constants in
# ``palace.py`` (``CLOSET_CHAR_LIMIT``, ``CLOSET_EXTRACT_WINDOW``) and
# ``searcher.py`` (``CLOSET_RANK_BOOSTS``, ``CLOSET_DISTANCE_CAP``,
# ``MAX_HYDRATION_CHARS``) so behaviour is byte-identical when
# ``config.json`` omits the ``closets`` block.
#
# Keys:
#   enabled             — master switch; when False, closet writes/reads are
#                         skipped entirely (reserved; not yet wired into all
#                         call sites — currently informational).
#   char_limit          — greedy packing cap per closet document (chars).
#   extract_window      — source-content window scanned for topic extraction.
#   rank_boosts         — per-rank cosine-distance subtraction applied to
#                         drawer hits when their source is also a closet hit.
#   distance_cap        — closet hits with cosine distance > this value are
#                         ignored as a boost signal.
#   max_hydration_chars — cap on drawer-grep-hydrated text returned per hit.
#   fallback_min_lines  — closet fallback floor; when regex produces fewer
#                         topic lines than this, Phase 3 enrichment kicks in
#                         (not yet wired — reserved for Phase 3).
DEFAULT_CLOSETS = {
    "enabled": True,
    "char_limit": 1500,
    "extract_window": 5000,
    "rank_boosts": [0.40, 0.25, 0.15, 0.08, 0.04],
    "distance_cap": 1.5,
    "max_hydration_chars": 10000,
    "fallback_min_lines": 3,
}

# Env vars honoured for closet overrides. Values are parsed by
# ``_parse_closet_env`` below; invalid values fall through to the next
# source in the precedence chain (file → default).
_CLOSET_ENV_PREFIX = "MEMPALACE_CLOSET_"
_CLOSET_ENV_KEYS = {
    "enabled": _CLOSET_ENV_PREFIX + "ENABLED",
    "char_limit": _CLOSET_ENV_PREFIX + "CHAR_LIMIT",
    "extract_window": _CLOSET_ENV_PREFIX + "EXTRACT_WINDOW",
    "rank_boosts": _CLOSET_ENV_PREFIX + "RANK_BOOSTS",
    "distance_cap": _CLOSET_ENV_PREFIX + "DISTANCE_CAP",
    "max_hydration_chars": _CLOSET_ENV_PREFIX + "MAX_HYDRATION_CHARS",
    "fallback_min_lines": _CLOSET_ENV_PREFIX + "FALLBACK_MIN_LINES",
}


def _parse_bool(raw: str):
    """Parse a permissive boolean env var. Returns None on failure so callers
    can treat it as "env var not provided" and fall through."""
    if raw is None:
        return None
    s = raw.strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return None


def _parse_float_list(raw: str):
    """Parse a comma-separated float list. Returns None on any parse error
    so the env var is treated as absent rather than silently zeroed out."""
    if raw is None:
        return None
    try:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return [float(p) for p in parts] if parts else None
    except ValueError:
        return None


def _parse_closet_env():
    """Read all closet env-var overrides. Returns a partial dict (only keys
    actually set + parseable) so it can be layered on top of file + defaults.
    """
    out = {}
    for key, env_name in _CLOSET_ENV_KEYS.items():
        raw = os.environ.get(env_name)
        if raw is None:
            continue
        if key == "enabled":
            val = _parse_bool(raw)
            if val is not None:
                out[key] = val
        elif key == "rank_boosts":
            val = _parse_float_list(raw)
            if val is not None:
                out[key] = val
        elif key == "distance_cap":
            try:
                out[key] = float(raw)
            except ValueError:
                pass
        else:  # int fields
            try:
                out[key] = int(raw)
            except ValueError:
                pass
    return out


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
            # Normalize: expand ~ and collapse .. to match the CLI --palace
            # code path (mcp_server.py:62) and prevent surprise redirection
            # when the env var contains unresolved components.
            return os.path.abspath(os.path.expanduser(env_val))
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
    def closets(self):
        """Closet (index-layer) tunables.

        Precedence: env (``MEMPALACE_CLOSET_*``) → ``config.json`` (``closets``
        block) → ``DEFAULT_CLOSETS``. Unknown or malformed env values are
        silently dropped so a bad env doesn't hide a valid file override.

        Returns a fresh dict with every documented key present — callers never
        need to guard against missing keys.
        """
        merged = dict(DEFAULT_CLOSETS)
        file_block = self._file_config.get("closets")
        if isinstance(file_block, dict):
            for key in DEFAULT_CLOSETS:
                if key in file_block:
                    merged[key] = file_block[key]
        env_block = _parse_closet_env()
        merged.update(env_block)
        # Defensive normalization — a hand-edited file could provide the wrong
        # type; coerce to the shape callers expect or fall back to default.
        if not isinstance(merged.get("rank_boosts"), list):
            merged["rank_boosts"] = list(DEFAULT_CLOSETS["rank_boosts"])
        else:
            try:
                merged["rank_boosts"] = [float(x) for x in merged["rank_boosts"]]
            except (TypeError, ValueError):
                merged["rank_boosts"] = list(DEFAULT_CLOSETS["rank_boosts"])
        return merged

    def closets_source(self):
        """Where did each closet value come from? For ``mempalace config show-closets``.

        Returns ``{key: "env" | "file" | "default"}`` using the same precedence
        chain as ``closets``.
        """
        env_block = _parse_closet_env()
        file_block = self._file_config.get("closets") or {}
        sources = {}
        for key in DEFAULT_CLOSETS:
            if key in env_block:
                sources[key] = "env"
            elif isinstance(file_block, dict) and key in file_block:
                sources[key] = "file"
            else:
                sources[key] = "default"
        return sources

    @property
    def entity_languages(self):
        """Languages whose entity-detection patterns should be applied.

        Reads from env var ``MEMPALACE_ENTITY_LANGUAGES`` (comma-separated)
        first, then the ``entity_languages`` field in ``config.json``,
        defaulting to ``["en"]``.
        """
        env_val = os.environ.get("MEMPALACE_ENTITY_LANGUAGES") or os.environ.get(
            "MEMPAL_ENTITY_LANGUAGES"
        )
        if env_val:
            return [s.strip() for s in env_val.split(",") if s.strip()] or ["en"]
        cfg = self._file_config.get("entity_languages")
        if isinstance(cfg, list) and cfg:
            return [str(s) for s in cfg]
        return ["en"]

    def set_entity_languages(self, languages):
        """Persist the entity-detection language list to ``config.json``."""
        normalized = [s.strip() for s in languages if s and s.strip()]
        if not normalized:
            normalized = ["en"]
        self._file_config["entity_languages"] = normalized
        self._config_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._config_file, "w", encoding="utf-8") as f:
                json.dump(self._file_config, f, indent=2, ensure_ascii=False)
        except OSError:
            pass
        try:
            self._config_file.chmod(0o600)
        except (OSError, NotImplementedError):
            pass
        return normalized

    @property
    def embedding_device(self):
        """Hardware device for the ONNX embedding model.

        Values: ``"auto"`` (default), ``"cpu"``, ``"cuda"``, ``"coreml"``,
        ``"dml"``. Read from env ``MEMPALACE_EMBEDDING_DEVICE`` first, then
        ``embedding_device`` in ``config.json``, then ``"auto"``.

        ``auto`` resolves to the first available accelerator at runtime via
        :mod:`mempalace.embedding`; requesting an unavailable accelerator
        logs a warning and falls back to CPU.
        """
        env_val = os.environ.get("MEMPALACE_EMBEDDING_DEVICE")
        if env_val:
            return env_val.strip().lower()
        return str(self._file_config.get("embedding_device", "auto")).strip().lower()

    @property
    def topic_tunnel_min_count(self):
        """Minimum number of overlapping confirmed topics required to create
        a cross-wing tunnel between two wings.

        Default is ``1`` — any single shared topic produces a tunnel. Bump
        to ``2+`` if your projects share lots of common-tech labels (Python,
        Docker, Git) and you want only meaningfully overlapping wings to
        link. Reads ``MEMPALACE_TOPIC_TUNNEL_MIN_COUNT`` env first, then the
        config-file value, then ``1``.
        """
        env_val = os.environ.get("MEMPALACE_TOPIC_TUNNEL_MIN_COUNT")
        if env_val:
            try:
                parsed = int(env_val)
                if parsed >= 1:
                    return parsed
            except ValueError:
                pass
        cfg_val = self._file_config.get("topic_tunnel_min_count")
        try:
            parsed = int(cfg_val) if cfg_val is not None else 1
        except (TypeError, ValueError):
            parsed = 1
        return max(1, parsed)

    @property
    def hook_silent_save(self):
        """Whether the stop hook saves directly (True) or blocks for MCP calls (False)."""
        return self._file_config.get("hooks", {}).get("silent_save", True)

    @property
    def hook_desktop_toast(self):
        """Whether the stop hook shows a desktop notification via notify-send."""
        return self._file_config.get("hooks", {}).get("desktop_toast", False)

    def set_hook_setting(self, key: str, value: bool):
        """Update a hook setting and write config to disk."""
        if "hooks" not in self._file_config:
            self._file_config["hooks"] = {}
        self._file_config["hooks"][key] = value
        try:
            with open(self._config_file, "w", encoding="utf-8") as f:
                json.dump(self._file_config, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

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
                "closets": dict(DEFAULT_CLOSETS),
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
        try:
            self._people_map_file.chmod(0o600)
        except (OSError, NotImplementedError):
            pass
        return self._people_map_file

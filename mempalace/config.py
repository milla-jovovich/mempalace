"""
MemPalace configuration system.

Priority: env vars > config file (~/.mempalace/config.json) > defaults
"""

import json
import os
from pathlib import Path

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
    def synapse_enabled(self):
        """Synapse master switch — false disables scoring and retrieval logging."""
        return self._file_config.get("synapse_enabled", False)

    @property
    def synapse_ltp_enabled(self):
        return self._file_config.get("synapse_ltp_enabled", True)

    @property
    def synapse_tagging_enabled(self):
        return self._file_config.get("synapse_tagging_enabled", True)

    @property
    def synapse_association_enabled(self):
        return self._file_config.get("synapse_association_enabled", False)

    @property
    def synapse_association_max_boost(self):
        return self._file_config.get("synapse_association_max_boost", 1.5)

    @property
    def synapse_association_coefficient(self):
        return self._file_config.get("synapse_association_coefficient", 0.15)

    @property
    def synapse_ltp_window_days(self):
        return self._file_config.get("synapse_ltp_window_days", 30)

    @property
    def synapse_ltp_max_boost(self):
        return self._file_config.get("synapse_ltp_max_boost", 2.0)

    @property
    def synapse_tagging_window_hours(self):
        return self._file_config.get("synapse_tagging_window_hours", 24)

    @property
    def synapse_tagging_max_boost(self):
        return self._file_config.get("synapse_tagging_max_boost", 1.5)

    @property
    def synapse_log_retrievals(self):
        return self._file_config.get("synapse_log_retrievals", True)

    @property
    def synapse_log_retention_days(self):
        return self._file_config.get("synapse_log_retention_days", 90)

    @property
    def synapse_consolidation_inactive_days(self):
        """Days without retrieval before a drawer is a consolidation candidate."""
        return self._file_config.get("synapse_consolidation_inactive_days", 180)

    @property
    def synapse_soft_archive_suggestions_enabled(self):
        """Surface soft-archive move suggestions for inactive drawers (#336)."""
        return self._file_config.get("synapse_soft_archive_suggestions_enabled", True)

    @property
    def synapse_soft_archive_target_wing(self):
        """Suggested wing name for cold-storage moves (nudge only)."""
        return self._file_config.get("synapse_soft_archive_target_wing", "archive")

    def init(self):
        """Create config directory and write default config.json if it doesn't exist."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        if not self._config_file.exists():
            default_config = {
                "palace_path": DEFAULT_PALACE_PATH,
                "collection_name": DEFAULT_COLLECTION_NAME,
                "topic_wings": DEFAULT_TOPIC_WINGS,
                "hall_keywords": DEFAULT_HALL_KEYWORDS,
            }
            with open(self._config_file, "w") as f:
                json.dump(default_config, f, indent=2)
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

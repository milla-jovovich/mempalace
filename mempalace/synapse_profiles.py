"""
RetrievalProfile: named Synapse parameter sets with inheritance.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

HARDCODED_DEFAULTS: Dict[str, Any] = {
    "half_life_days": 90,
    "ltp_enabled": True,
    "ltp_window_days": 30,
    "ltp_max_boost": 2.0,
    "tagging_enabled": True,
    "tagging_window_hours": 24,
    "tagging_max_boost": 1.5,
    "association_enabled": False,
    "association_max_boost": 1.5,
    "association_coefficient": 0.15,
    "axes_enabled": ["ltp", "tagging", "association"],
}


def global_merged_from_mempalace_config(cfg: Any) -> Dict[str, Any]:
    """Map ~/.mempalace config.json synapse_* keys into profile field names."""
    return {
        "ltp_enabled": cfg.synapse_ltp_enabled,
        "tagging_enabled": cfg.synapse_tagging_enabled,
        "association_enabled": cfg.synapse_association_enabled,
        "ltp_window_days": cfg.synapse_ltp_window_days,
        "ltp_max_boost": cfg.synapse_ltp_max_boost,
        "tagging_window_hours": cfg.synapse_tagging_window_hours,
        "tagging_max_boost": cfg.synapse_tagging_max_boost,
        "association_max_boost": cfg.synapse_association_max_boost,
        "association_coefficient": cfg.synapse_association_coefficient,
    }


def hit_filed_age_days(filed_at: Optional[str]) -> float:
    """Days since filed_at (ISO), or 0.0 if missing / invalid."""
    if not filed_at:
        return 0.0
    try:
        s = filed_at.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        filed = datetime.fromisoformat(s)
        if filed.tzinfo is None:
            filed = filed.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        secs = (now - filed.astimezone(timezone.utc)).total_seconds()
        return max(0.0, secs / 86400.0)
    except (ValueError, TypeError, OSError):
        return 0.0


def compute_decay(age_days: float, half_life_days: int) -> float:
    """Exponential half-life decay: 0.5 at age == half_life_days."""
    if half_life_days <= 0:
        return 1.0
    if age_days <= 0:
        return 1.0
    return math.exp(-math.log(2.0) * age_days / float(half_life_days))


class RetrievalProfile:
    """Resolved Synapse profile with all values populated."""

    def __init__(self, name: str, values: Dict[str, Any]):
        self.name = name
        self._values = values

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_") or key == "name":
            raise AttributeError(key)
        if key in self._values:
            return self._values[key]
        raise AttributeError(f"RetrievalProfile has no key '{key}'")

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, **self._values}


class ProfileManager:
    """
    Loads, merges, and resolves Synapse profiles.

    Merge chain (later wins):
      hardcoded defaults → global_merged (caller: ~/.mempalace synapse_* )
        → palace config.json["synapse_profiles"]["default"]
        → palace synapse_profiles.json["default"]
        → palace config.json[profile_name]
        → palace synapse_profiles.json[profile_name]
        → per_query_overrides

    Inheritance: depth-1 only (named profiles merge on top of default layers).
    """

    def __init__(self, palace_path: str):
        self._palace_path = palace_path
        self._config_profiles: Dict[str, Dict[str, Any]] = {}
        self._file_profiles: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        self._config_profiles = {}
        self._file_profiles = {}

        config_path = os.path.join(self._palace_path, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                raw = data.get("synapse_profiles", {})
                if isinstance(raw, dict):
                    self._config_profiles = raw
            except (json.JSONDecodeError, OSError, TypeError) as e:
                logger.warning("Failed to load config.json profiles: %s", e)

        profiles_path = os.path.join(self._palace_path, "synapse_profiles.json")
        if os.path.exists(profiles_path):
            try:
                with open(profiles_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self._file_profiles = loaded
            except (json.JSONDecodeError, OSError, TypeError) as e:
                logger.warning("Failed to load synapse_profiles.json: %s", e)

    def get_known_profiles(self) -> List[str]:
        names: set[str] = set()
        names.update(self._config_profiles.keys())
        names.update(self._file_profiles.keys())
        names.add("default")
        return sorted(names)

    def resolve(
        self,
        profile_name: Optional[str] = None,
        per_query_overrides: Optional[Dict[str, Any]] = None,
        global_merged: Optional[Dict[str, Any]] = None,
    ) -> RetrievalProfile:
        if profile_name is None:
            profile_name = "default"

        known = self.get_known_profiles()
        actual_name = profile_name
        if profile_name != "default" and profile_name not in known:
            logger.warning(
                "synapse_profile '%s' not found — falling back to 'default'",
                profile_name,
            )
            actual_name = "default"

        merged: Dict[str, Any] = dict(HARDCODED_DEFAULTS)
        if global_merged:
            merged.update(global_merged)

        if "default" in self._config_profiles and isinstance(
            self._config_profiles["default"], dict
        ):
            merged.update(self._config_profiles["default"])

        if "default" in self._file_profiles and isinstance(
            self._file_profiles["default"], dict
        ):
            merged.update(self._file_profiles["default"])

        if actual_name != "default" and actual_name in self._config_profiles:
            layer = self._config_profiles[actual_name]
            if isinstance(layer, dict):
                merged.update(layer)

        if actual_name != "default" and actual_name in self._file_profiles:
            layer = self._file_profiles[actual_name]
            if isinstance(layer, dict):
                merged.update(layer)

        if per_query_overrides:
            for k, v in per_query_overrides.items():
                if v is not None:
                    merged[k] = v

        axes = merged.get("axes_enabled", [])
        if isinstance(axes, list):
            if "ltp" not in axes:
                merged["ltp_enabled"] = False
            if "tagging" not in axes:
                merged["tagging_enabled"] = False
            if "association" not in axes:
                merged["association_enabled"] = False

        return RetrievalProfile(actual_name, merged)

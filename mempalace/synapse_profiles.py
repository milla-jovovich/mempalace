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

VALID_AXES = frozenset({"ltp", "tagging", "association", "similarity", "decay", "recency", "mmr"})

HARDCODED_DEFAULTS: Dict[str, Any] = {
    "description": "",
    "half_life_days": 90,
    "ltp_enabled": True,
    "ltp_window_days": 30,
    "ltp_max_boost": 2.0,
    "tagging_enabled": True,
    "tagging_window_hours": 24,
    "tagging_max_boost": 1.5,
    "association_enabled": True,
    "association_max_boost": 1.4,
    "association_coefficient": 0.2,
    "axes_enabled": ["ltp", "tagging", "association"],
    # Phase 5 — MMR (opt-in)
    "mmr_enabled": False,
    "mmr_lambda": 0.7,
    "mmr_final_k": 5,
    # Phase 6 — Pinned memory (opt-in)
    "pinned_memory_enabled": False,
    "pinned_max_tokens": 2000,
    "pinned_max_items": 5,
    "pinned_ltp_threshold": 1.5,
    "pinned_include_tagged": True,
    "pinned_tagged_window_hours": 48,
    # Phase 7 — Query expansion (opt-in)
    "query_expansion_enabled": False,
    "query_expansion_max_terms": 3,
    "query_expansion_similarity_threshold": 0.65,
    "query_expansion_boost": 0.7,
    "query_expansion_lookback_days": 60,
    # Phase 8 — Supersede detection (opt-in)
    "supersede_filter_enabled": False,
    "supersede_similarity_threshold": 0.86,
    "supersede_min_age_gap_days": 7,
    "supersede_action": "filter",
    "supersede_max_candidates": 10,
    # Phase 9 — Consolidation in search results
    "include_consolidated_summaries": True,
    "include_consolidated_sources": False,
    "consolidation_suggestions_in_status": True,
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

    def __init__(
        self,
        name: str,
        values: Dict[str, Any],
        sources: Optional[Dict[str, str]] = None,
    ):
        self.name = name
        self._values = values
        self._sources = sources or {}

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_") or key == "name":
            raise AttributeError(key)
        if key in self._values:
            return self._values[key]
        raise AttributeError(f"RetrievalProfile has no key '{key}'")

    def get_source(self, key: str) -> str:
        return self._sources.get(key, "unknown")

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, **self._values}

    def to_annotated_dict(self) -> Dict[str, Dict[str, Any]]:
        """Each resolved value paired with the merge layer that last set it."""
        return {
            k: {"value": v, "source": self._sources.get(k, "unknown")}
            for k, v in self._values.items()
        }


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

    def _validate(self, merged: Dict[str, Any], profile_name: str) -> None:
        """Fail fast with clear error messages on invalid profile values."""
        errors: List[str] = []

        axes = merged.get("axes_enabled", [])
        if isinstance(axes, list):
            for ax in axes:
                if ax not in VALID_AXES:
                    errors.append(
                        f"Unknown axis '{ax}' in axes_enabled. Valid: {sorted(VALID_AXES)}"
                    )

        hld = merged.get("half_life_days")
        if hld is not None and hld <= 0:
            errors.append(f"half_life_days must be > 0 or null, got {hld}")

        lmb = merged.get("ltp_max_boost")
        if lmb is not None and lmb < 1.0:
            errors.append(f"ltp_max_boost must be >= 1.0, got {lmb}")

        tmb = merged.get("tagging_max_boost")
        if tmb is not None and tmb < 1.0:
            errors.append(f"tagging_max_boost must be >= 1.0, got {tmb}")

        amb = merged.get("association_max_boost")
        if amb is not None and amb < 1.0:
            errors.append(f"association_max_boost must be >= 1.0, got {amb}")

        lwd = merged.get("ltp_window_days")
        if lwd is not None and lwd <= 0:
            errors.append(f"ltp_window_days must be > 0, got {lwd}")

        twh = merged.get("tagging_window_hours")
        if twh is not None and twh <= 0:
            errors.append(f"tagging_window_hours must be > 0, got {twh}")

        mlam = merged.get("mmr_lambda")
        if mlam is not None and (mlam < 0.0 or mlam > 1.0):
            errors.append(f"mmr_lambda must be between 0.0 and 1.0, got {mlam}")

        mmfk = merged.get("mmr_final_k")
        if mmfk is not None and (not isinstance(mmfk, int) or isinstance(mmfk, bool) or mmfk < 1):
            errors.append(f"mmr_final_k must be an integer >= 1, got {mmfk}")

        pmt = merged.get("pinned_max_tokens")
        if pmt is not None and (not isinstance(pmt, int) or pmt < 1):
            errors.append(f"pinned_max_tokens must be an integer >= 1, got {pmt}")

        pmi = merged.get("pinned_max_items")
        if pmi is not None and (not isinstance(pmi, int) or pmi < 1):
            errors.append(f"pinned_max_items must be an integer >= 1, got {pmi}")

        plt = merged.get("pinned_ltp_threshold")
        if plt is not None and plt < 0.0:
            errors.append(f"pinned_ltp_threshold must be >= 0.0, got {plt}")

        ptwh = merged.get("pinned_tagged_window_hours")
        if ptwh is not None and ptwh <= 0:
            errors.append(f"pinned_tagged_window_hours must be > 0, got {ptwh}")

        qemt = merged.get("query_expansion_max_terms")
        if qemt is not None and (not isinstance(qemt, int) or qemt < 1):
            errors.append(f"query_expansion_max_terms must be an integer >= 1, got {qemt}")

        qest = merged.get("query_expansion_similarity_threshold")
        if qest is not None and (qest < 0.0 or qest > 1.0):
            errors.append(
                f"query_expansion_similarity_threshold must be between 0.0 and 1.0, got {qest}"
            )

        qeb = merged.get("query_expansion_boost")
        if qeb is not None and (qeb < 0.0 or qeb > 1.0):
            errors.append(f"query_expansion_boost must be between 0.0 and 1.0, got {qeb}")

        qel = merged.get("query_expansion_lookback_days")
        if qel is not None and qel < 1:
            errors.append(f"query_expansion_lookback_days must be >= 1, got {qel}")

        sst = merged.get("supersede_similarity_threshold")
        if sst is not None and (sst < 0.0 or sst > 1.0):
            errors.append(f"supersede_similarity_threshold must be between 0.0 and 1.0, got {sst}")

        smag = merged.get("supersede_min_age_gap_days")
        if smag is not None and (not isinstance(smag, int) or smag < 0):
            errors.append(f"supersede_min_age_gap_days must be an integer >= 0, got {smag}")

        sa = merged.get("supersede_action")
        if sa is not None and sa not in ("filter", "annotate"):
            errors.append(f'supersede_action must be "filter" or "annotate", got {sa!r}')

        smc = merged.get("supersede_max_candidates")
        if smc is not None and (not isinstance(smc, int) or smc < 1):
            errors.append(f"supersede_max_candidates must be an integer >= 1, got {smc}")

        if errors:
            raise ValueError(f"Invalid profile '{profile_name}': " + "; ".join(errors))

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

        merged: Dict[str, Any] = {}
        sources: Dict[str, str] = {}

        for k, v in HARDCODED_DEFAULTS.items():
            merged[k] = v
            sources[k] = "hardcoded"

        if global_merged:
            for k, v in global_merged.items():
                if v is not None:
                    merged[k] = v
                    sources[k] = "global config.json"

        if "default" in self._config_profiles and isinstance(
            self._config_profiles["default"], dict
        ):
            for k, v in self._config_profiles["default"].items():
                merged[k] = v
                sources[k] = "default (config.json)"

        if "default" in self._file_profiles and isinstance(self._file_profiles["default"], dict):
            for k, v in self._file_profiles["default"].items():
                merged[k] = v
                sources[k] = "default (synapse_profiles.json)"

        if actual_name != "default" and actual_name in self._config_profiles:
            layer = self._config_profiles[actual_name]
            if isinstance(layer, dict):
                for k, v in layer.items():
                    merged[k] = v
                    sources[k] = "profile (config.json)"

        if actual_name != "default" and actual_name in self._file_profiles:
            layer = self._file_profiles[actual_name]
            if isinstance(layer, dict):
                for k, v in layer.items():
                    merged[k] = v
                    sources[k] = "profile (synapse_profiles.json)"

        if per_query_overrides:
            for k, v in per_query_overrides.items():
                if v is not None:
                    merged[k] = v
                    sources[k] = "per-query override"

        axes = merged.get("axes_enabled", [])
        if isinstance(axes, list):
            ax_src = sources.get("axes_enabled", "hardcoded")
            if "ltp" not in axes:
                merged["ltp_enabled"] = False
                sources["ltp_enabled"] = f"axes_enabled ({ax_src})"
            if "tagging" not in axes:
                merged["tagging_enabled"] = False
                sources["tagging_enabled"] = f"axes_enabled ({ax_src})"
            if "association" not in axes:
                merged["association_enabled"] = False
                sources["association_enabled"] = f"axes_enabled ({ax_src})"

        self._validate(merged, actual_name)

        return RetrievalProfile(actual_name, merged, sources=sources)

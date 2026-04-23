"""
nlp_config.py -- Feature gate system for NLP backends.

ALL features are OFF by default. Nothing activates implicitly.
Priority: per-feature env var > backend env var > CLI flag > yaml > default (legacy).
"""

import os
from dataclasses import dataclass, field
from typing import Optional, Dict


BACKEND_LEVELS = ("legacy", "pysbd", "spacy", "gliner", "full")

ALL_CAPABILITIES = ("sentences", "negation", "ner", "coref", "triples", "classify", "slm")

# What each backend level enables (cumulative)
LEVEL_CAPABILITIES = {
    "legacy": set(),
    "pysbd": {"sentences", "negation"},
    "spacy": {"sentences", "negation", "ner", "coref"},
    "gliner": {"sentences", "negation", "ner", "coref", "triples", "classify"},
    "full": {"sentences", "negation", "ner", "coref", "triples", "classify"},
}

# Per-feature env var names
FEATURE_ENV_VARS = {
    "sentences": "MEMPALACE_NLP_SENTENCES",
    "negation": "MEMPALACE_NLP_NEGATION",
    "ner": "MEMPALACE_NLP_NER",
    "coref": "MEMPALACE_NLP_COREF",
    "triples": "MEMPALACE_NLP_TRIPLES",
    "classify": "MEMPALACE_NLP_CLASSIFY",
    "slm": "MEMPALACE_NLP_SLM",
}

# What each capability requires to be installed
CAPABILITY_PACKAGES = {
    "sentences": [("pysbd", "pysbd")],
    "negation": [],  # pure Python
    "ner": [("spacy", "spaCy")],
    "coref": [("coreferee", "coreferee"), ("spacy", "spaCy")],
    "triples": [("gliner", "GLiNER")],
    "classify": [("gliner", "GLiNER")],
    "slm": [("onnxruntime_genai", "onnxruntime-genai")],
}


@dataclass
class NLPConfig:
    """Resolved NLP configuration. All capabilities default to False."""

    backend: str = "legacy"
    source: str = "default"  # where the backend was set: "env", "cli", "yaml", "default"
    capabilities: Dict[str, bool] = field(default_factory=dict)

    @classmethod
    def resolve(
        cls,
        cli_backend: Optional[str] = None,
        yaml_config: Optional[dict] = None,
    ) -> "NLPConfig":
        """
        Resolve NLP configuration from all sources.

        Resolution order:
        1. Start with everything OFF
        2. Apply backend level (from CLI > env > yaml > default=legacy)
        3. Apply yaml fine-grained overrides
        4. Apply per-feature env vars (highest priority, for tests)
        5. Verify that required packages are actually installed
        """
        yaml_config = yaml_config or {}

        # -- Step 1: Determine backend level --
        backend = None
        source = "default"

        if cli_backend and cli_backend in BACKEND_LEVELS:
            backend = cli_backend
            source = "cli"

        if backend is None:
            env_backend = os.environ.get("MEMPALACE_NLP_BACKEND")
            if env_backend and env_backend in BACKEND_LEVELS:
                backend = env_backend
                source = "env"

        if backend is None:
            yaml_backend = yaml_config.get("nlp_backend")
            if yaml_backend and yaml_backend in BACKEND_LEVELS:
                backend = yaml_backend
                source = "yaml"

        if backend is None:
            backend = "legacy"
            source = "default"

        # -- Step 2: Start with all capabilities OFF --
        caps = dict.fromkeys(ALL_CAPABILITIES, False)

        # -- Step 3: Enable capabilities from backend level --
        level_caps = LEVEL_CAPABILITIES.get(backend, set())
        for cap in level_caps:
            caps[cap] = True

        # -- Step 4: Apply yaml fine-grained overrides --
        nlp_overrides = yaml_config.get("nlp", {})
        for cap in ALL_CAPABILITIES:
            if cap in nlp_overrides:
                caps[cap] = bool(nlp_overrides[cap])

        # -- Step 5: Apply per-feature env vars (HIGHEST PRIORITY) --
        for cap, env_var in FEATURE_ENV_VARS.items():
            env_val = os.environ.get(env_var)
            if env_val is not None:
                caps[cap] = env_val in ("1", "true", "yes", "on")
                if caps[cap]:
                    source = "env"  # at least one feature forced via env

        # -- Step 6: Verify packages are actually installed --
        for cap, enabled in caps.items():
            if enabled and not _capability_available(cap):
                caps[cap] = False

        return cls(backend=backend, source=source, capabilities=caps)

    def has(self, capability: str) -> bool:
        """Check if a specific NLP capability is active."""
        return self.capabilities.get(capability, False)

    def any_active(self) -> bool:
        """Check if any NLP capability is enabled."""
        return any(self.capabilities.values())


def _capability_available(cap: str) -> bool:
    """Check if the packages for a capability are installed."""
    packages = CAPABILITY_PACKAGES.get(cap, [])
    for module_name, _ in packages:
        try:
            __import__(module_name)
        except ImportError:
            return False
    return True


def installed_providers() -> dict:
    """Return dict of provider -> installed status for `nlp status` command."""
    providers = {}
    checks = {
        "pysbd": "pysbd",
        "spacy": "spacy",
        "coreferee": "coreferee",
        "gliner": "gliner",
        "wtpsplit": "wtpsplit",
        "onnxruntime": "onnxruntime",
        "onnxruntime-genai": "onnxruntime_genai",
    }
    for name, module in checks.items():
        try:
            mod = __import__(module)
            version = getattr(mod, "__version__", "installed")
            providers[name] = {"installed": True, "version": version}
        except ImportError:
            providers[name] = {"installed": False, "version": None}
    return providers

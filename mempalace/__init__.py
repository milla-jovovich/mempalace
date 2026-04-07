"""MemPalace — Give your AI a memory. No API key required."""

import os

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

# ChromaDB's bundled posthog telemetry is incompatible with posthog>=7.0
# (capture() switched to keyword-only args). Neutralize it early so every
# command doesn't print "Failed to send telemetry event" to stderr.
try:
    import posthog

    posthog.capture = lambda *_args, **_kwargs: None
except ImportError:
    pass

__version__ = "2.0.0"

from .cli import main

__all__ = ["main", "__version__"]

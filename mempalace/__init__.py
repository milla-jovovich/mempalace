"""MemPalace — Give your AI a memory. No API key required."""

from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("mempalace")
except Exception:
    __version__ = "3.0.0"

from .cli import main

__all__ = ["main", "__version__"]

"""MemPalace — Give your AI a memory. No API key required."""

import logging

from .cli import main  # noqa: E402
from .version import __version__  # noqa: E402

# Silence noisy loggers from dependencies.
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)
try:
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
except Exception:
    pass

# NOTE: the previous block set ``ORT_DISABLE_COREML=1`` on macOS arm64 as a
# supposed workaround for the #74 ARM64 segfault.  Two problems:
#
# 1. ONNX Runtime does not read that env var -- it has no global way to
#    disable a single execution provider, so the setdefault was a no-op.
# 2. #74 is a null-pointer crash in ``chromadb_rust_bindings.abi3.so``, not
#    an ONNX issue, so disabling CoreML would not have fixed it anyway.
#
# #521 has since traced the actual macOS arm64 crashes (both in mine and
# search paths) to the 0.x chromadb hnswlib binding.  Filtering
# CoreMLExecutionProvider at the ONNX layer leaves the hnswlib C++ crash
# intact, so the real fix is upgrading chromadb to 1.5.4+, which #581
# proposes.  See #397 for the history of this line.

__all__ = ["main", "__version__"]

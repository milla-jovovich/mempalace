#!/usr/bin/env bash
# taurus-setup.sh — MemPalace setup for Taurus agents.
#
# Source from .shell-init.sh:
#   source /shared/mempalace-agi/integrations/mempalace-taurus/scripts/taurus-setup.sh
#
# Idempotent — safe to run on every shell start.  Prints minimal output.

_PALACE_HELPER="/shared/mempalace-agi/integrations/mempalace-taurus/scripts/palace-helper.py"

# ── 1. Choose palace location ────────────────────────────────────────────────
#   MEMPALACE_PATH can be pre-set by the agent's .shell-init.sh.
#   Defaults: /shared/palace (multi-agent) or /workspace/palace (single-agent).

if [ -z "${MEMPALACE_PATH:-}" ]; then
    if [ -d "/shared" ]; then
        export MEMPALACE_PATH="/shared/palace"
    else
        export MEMPALACE_PATH="/workspace/palace"
    fi
fi
export MEMPALACE_PALACE_PATH="${MEMPALACE_PATH}"

# ── 2. Create palace directory if needed ─────────────────────────────────────

if [ ! -d "${MEMPALACE_PATH}" ]; then
    mkdir -p "${MEMPALACE_PATH}" 2>/dev/null
    echo "[mempalace] Created palace at ${MEMPALACE_PATH}"
fi

# ── 3. Install mempalace if missing ──────────────────────────────────────────
#   Try uv first (faster), fall back to pip.

if ! python3 -c "import mempalace" 2>/dev/null; then
    echo "[mempalace] Installing mempalace..."
    if command -v uv &>/dev/null; then
        uv pip install --quiet mempalace 2>/dev/null
    else
        pip install --quiet mempalace 2>/dev/null
    fi

    if python3 -c "import mempalace" 2>/dev/null; then
        echo "[mempalace] Installed mempalace $(python3 -c 'import mempalace; print(mempalace.__version__)')"
    else
        echo "[mempalace] WARNING: Failed to install mempalace"
    fi
fi

# ── 4. Install chromadb if missing (MemPalace dependency) ────────────────────

if ! python3 -c "import chromadb" 2>/dev/null; then
    echo "[mempalace] Installing chromadb..."
    if command -v uv &>/dev/null; then
        uv pip install --quiet chromadb 2>/dev/null
    else
        pip install --quiet chromadb 2>/dev/null
    fi
fi

# ── 5. Initialize ChromaDB collection if palace exists but has no DB ─────────

if [ -d "${MEMPALACE_PATH}" ] && [ ! -d "${MEMPALACE_PATH}/chroma.sqlite3" ] && [ ! -f "${MEMPALACE_PATH}/chroma.sqlite3" ]; then
    # Initialise by creating and immediately verifying the collection
    python3 -c "
import chromadb, sys
try:
    c = chromadb.PersistentClient(path='${MEMPALACE_PATH}')
    c.get_or_create_collection('mempalace_drawers')
except Exception as e:
    print(f'[mempalace] ChromaDB init warning: {e}', file=sys.stderr)
" 2>/dev/null
fi

# ── 6. Set up alias ─────────────────────────────────────────────────────────

alias palace="python3 ${_PALACE_HELPER}"

# ── 7. Verify ────────────────────────────────────────────────────────────────
#   Quick sanity check on first run (presence of helper script).

if [ ! -f "${_PALACE_HELPER}" ]; then
    echo "[mempalace] WARNING: palace-helper.py not found at ${_PALACE_HELPER}"
else
    echo "[mempalace] Ready — palace at ${MEMPALACE_PATH}"
fi

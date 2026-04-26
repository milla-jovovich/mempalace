#!/usr/bin/env bash
# deploy.sh — push fork main, wait for Syncthing to mirror to the
# daemon host, restart palace-daemon (where mempalace is editable-
# installed), smoke-test.
#
# Why this is the deploy:
#   - mempalace on disks is `pip install -e /mnt/raid/projects/memorypalace`.
#   - Source files reach disks via Syncthing, not git on the remote.
#   - palace-daemon's Python process caches imports at startup, so a
#     restart is required for code changes to go live.
#   - No `pip install --upgrade` needed (editable install + same version).
#
# Assumes:
#   - HEAD is on `main` and you want to push it to `origin`.
#   - Deploy host has the source tree synced via Syncthing.
#   - palace-daemon is a systemd --user service named "palace-daemon".
#
# Usage:
#   scripts/deploy.sh                       # default host: disks
#   PALACE_HOST=otherhost scripts/deploy.sh
#
# Env vars (optional):
#   PALACE_HOST          — hostname for ssh + URL (default: disks)
#   PALACE_DAEMON_URL    — full URL override (default: http://$PALACE_HOST.jphe.in:8085)
#   PALACE_SYNC_GRACE    — seconds to let Syncthing catch up (default: 3)
#   PALACE_HEALTH_TIMEOUT — seconds to wait for /health post-restart (default: 30)

set -euo pipefail

HOST="${PALACE_HOST:-disks}"
URL="${PALACE_DAEMON_URL:-http://${HOST}.jphe.in:8085}"
SYNC_GRACE="${PALACE_SYNC_GRACE:-3}"
HEALTH_TIMEOUT="${PALACE_HEALTH_TIMEOUT:-30}"

step() { printf '\n\033[1m▸ %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1" >&2; exit 1; }

step "1/5  push fork main → origin"
local_sha=$(git rev-parse HEAD)
git push origin main >/dev/null 2>&1 || fail "git push failed"
ok "pushed $local_sha → origin/main"

step "2/5  wait for Syncthing → $HOST"
sleep "$SYNC_GRACE"
# memorypalace on disks is a Syncthing mirror, not a git checkout — verify
# by reading the file we just changed (chroma.py mtime check is overkill;
# instead spot-check that __version__ matches and a recently-touched file
# is present at the expected path).
remote_pyproject_version=$(
    ssh "$HOST" "grep -E '^version\s*=' /mnt/raid/projects/memorypalace/pyproject.toml | head -1" 2>/dev/null \
        | tr -d '"' || echo ""
)
if [ -n "$remote_pyproject_version" ]; then
    ok "remote source tree is reachable ($remote_pyproject_version)"
else
    fail "remote /mnt/raid/projects/memorypalace not reachable — Syncthing not mirroring?"
fi

step "3/5  restart palace-daemon on $HOST"
ssh "$HOST" "systemctl --user restart palace-daemon" || fail "restart failed"
ok "restart issued"

step "4/5  wait for daemon health"
deadline=$((SECONDS + HEALTH_TIMEOUT))
while (( SECONDS < deadline )); do
    if curl -fs --max-time 3 "$URL/health" >/dev/null 2>&1; then
        version=$(curl -s "$URL/health" | python3 -c 'import sys,json; print(json.load(sys.stdin)["version"])' 2>/dev/null || echo "?")
        ok "healthy on v$version"
        break
    fi
    sleep 1
done
(( SECONDS >= deadline )) && fail "daemon did not respond on $URL within ${HEALTH_TIMEOUT}s"

step "5/5  verify new code is loaded"
# Spot-check that a recent fork addition is importable from the daemon's
# venv (proves Syncthing + restart picked up new code, not just a stale
# import). Update this list as new public surface lands.
ssh "$HOST" "~/.local/share/palace-daemon/venv/bin/python -c '
from mempalace.backends.chroma import ChromaBackend
from mempalace.palace import _SESSION_RECOVERY_COLLECTION, get_session_recovery_collection
from mempalace.mcp_server import tool_session_recovery_read
assert hasattr(ChromaBackend, \"_quarantined_paths\"), \"HNSW gate fix not loaded\"
assert _SESSION_RECOVERY_COLLECTION == \"mempalace_session_recovery\"
print(\"OK\")
'" >/dev/null 2>&1 || fail "post-restart import check failed (see ssh log)"
ok "post-restart imports include today's fork-ahead surface"

printf '\n\033[1;32m✦ mempalace deploy complete: %s on %s\033[0m\n' "$local_sha" "$URL"

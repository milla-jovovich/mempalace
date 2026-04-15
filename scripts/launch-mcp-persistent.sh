#!/usr/bin/env bash
# launch-mcp-persistent.sh — stdio MCP launcher for mempalace with
# startup retry + exponential backoff, to work around the known
# Claude Code "Failed to reconnect to mempalace" race at session start.
#
# Phase 3 Part 3 of workspace-redesign-phase-2.
#
# Why wrapper-at-startup only (not mid-session respawn):
# stdio MCP is a one-shot JSON-RPC session over stdin/stdout. If the child
# dies mid-session, the parent (Claude Code) has already lost the handshake;
# respawning a fresh child can't restore the session. The only race this
# tool can fix is the ONE at launch time — a flaky import or venv init on
# cold start. We retry the preflight check up to 5 times (1s, 2s, 4s, 8s,
# 16s), and when preflight succeeds we `exec` the real server so stdin/stdout
# pass through to the child without an extra proxy layer.
#
# Observability: every attempt is logged to ~/.claude/backups/mempalace-launcher.log
# and a sentinel ~/.claude/backups/mempalace-launcher.ready is touched on
# successful handoff (cleared on EXIT).

set -u

MEMPAL_DIR="${MEMPAL_DIR:-$HOME/Development/platform/mempalace}"
MEMPAL_PY="${MEMPAL_PY:-$MEMPAL_DIR/.venv/bin/python}"
LOG_DIR="$HOME/.claude/backups"
LOG="$LOG_DIR/mempalace-launcher.log"
READY="$LOG_DIR/mempalace-launcher.ready"
PIDFILE="$LOG_DIR/mempalace-launcher.pid"

mkdir -p "$LOG_DIR"

log() {
    printf '[%s] [pid=%d] %s\n' "$(date +%Y-%m-%dT%H:%M:%S%z)" "$$" "$*" >> "$LOG"
}

cleanup() {
    rm -f "$READY" "$PIDFILE"
    log "launcher EXIT pid=$$"
}
trap cleanup EXIT
trap 'log "SIGINT received"; exit 130' INT
trap 'log "SIGTERM received"; exit 143' TERM

log "launcher START argv=[$*] MEMPAL_PY=$MEMPAL_PY"
echo "$$" > "$PIDFILE"

preflight() {
    if [[ ! -x "$MEMPAL_PY" ]]; then
        log "preflight FAIL: python not executable at $MEMPAL_PY"
        return 1
    fi
    local out
    if ! out=$("$MEMPAL_PY" -c "import mempalace.mcp_server; print('ok')" 2>&1); then
        log "preflight FAIL: import mempalace.mcp_server: $out"
        return 1
    fi
    return 0
}

backoff=1
max_attempts=5
attempt=0
while (( attempt < max_attempts )); do
    attempt=$((attempt + 1))
    if preflight; then
        log "preflight OK (attempt=$attempt)"
        touch "$READY"
        log "exec $MEMPAL_PY -m mempalace.mcp_server $*"
        # replace ourselves with the real server — stdin/stdout/stderr pass through
        exec "$MEMPAL_PY" -m mempalace.mcp_server "$@"
        # unreachable
    fi
    log "preflight failed (attempt=$attempt), sleeping ${backoff}s"
    sleep "$backoff"
    backoff=$((backoff * 2))
    if (( backoff > 16 )); then
        backoff=16
    fi
done

log "GAVE UP after $max_attempts attempts — mempalace MCP will not start"
exit 1

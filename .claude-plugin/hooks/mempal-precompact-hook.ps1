# MemPalace PreCompact Hook (Windows) — thin wrapper calling Python CLI
# All logic lives in mempalace.hooks_cli for cross-harness extensibility
$INPUT = $input | Out-String
$INPUT | py -m mempalace hook run --hook precompact --harness claude-code

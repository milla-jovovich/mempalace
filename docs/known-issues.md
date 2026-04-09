# Known Issues

## Mining hangs / D-state on repositories with large binary files in .gitignore

**Symptoms:** `mempalace mine` enters an uninterruptible D-state (unkillable even with `kill -9`) when the repository contains large binary files (100MB+) that are excluded via `.gitignore` but not excluded from MemPalace's file scanning. The process blocks on I/O indefinitely.

**Trigger condition:** Repositories using Terraform that have a `.terraform/providers/` directory with provider binaries (for example `terraform-provider-aws_v5.x_x5`, roughly 100MB). This directory is in `.gitignore`, but MemPalace processes it anyway.

**Root cause:** MemPalace's file walker does not fully respect `.gitignore` exclusions when scanning for files to embed. Large binary files cause the embedding pipeline to block on I/O.

**Impact:** The mining process cannot be killed without a system reboot. Other `mempalace` commands such as `mempalace search` and `mempalace status` can also hang if ChromaDB is locked by the stuck process.

**Workaround:** Before running `mempalace mine`, create a `.mempalaceignore` file in the project root (same format as `.gitignore`) explicitly excluding binary/vendor directories:

```gitignore
.terraform/
node_modules/
*.egg-info/
__pycache__/
dist/
build/
vendor/
```

**Affected versions:** Confirmed on mempalace 3.0.0 with ChromaDB 1.5.6.

**Tracking:** This issue was discovered during real-world use on repositories with Terraform infrastructure code. The fix was to skip files larger than 10 MB during scanning and add `.mempalaceignore` support so MemPalace can explicitly exclude problematic paths before attempting to embed them.

**Status:** Fixed on branch `docs/gitignore-binary-mining-bug` by adding the large-file scan guard and `.mempalaceignore` overrides in the miner.

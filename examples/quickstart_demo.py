#!/usr/bin/env python3
"""
Run the bundled examples/demo_project through mine + search + status.

Usage (from repository root, with package installed):
  pip install -e .
  python examples/quickstart_demo.py --isolated

--isolated uses a temporary palace via MEMPALACE_PALACE_PATH (safe for first try).
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

if importlib.util.find_spec("chromadb") is None:
    print(
        "chromadb is not installed for this Python. Run: pip install mempalace\n"
        "Then re-run this script (use the same interpreter you installed into).",
        file=sys.stderr,
    )
    sys.exit(1)


def run(cmd: list[str], env: dict) -> None:
    print("$", " ".join(cmd))
    r = subprocess.run(cmd, env=env)
    if r.returncode != 0:
        sys.exit(r.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--isolated",
        action="store_true",
        help="Set MEMPALACE_PALACE_PATH to a new temp directory for this run",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    demo = repo_root / "examples" / "demo_project"
    if not (demo / "mempalace.yaml").exists():
        print(f"Missing {demo / 'mempalace.yaml'} — run from a full checkout.", file=sys.stderr)
        sys.exit(1)

    env = os.environ.copy()
    if args.isolated:
        palace = tempfile.mkdtemp(prefix="mempalace_quickstart_")
        env["MEMPALACE_PALACE_PATH"] = palace
        print(f"Isolated palace: {palace}\n")

    exe = sys.executable
    run([exe, "-m", "mempalace", "mine", str(demo)], env=env)
    print()
    run([exe, "-m", "mempalace", "status"], env=env)
    print()
    run([exe, "-m", "mempalace", "search", "cabin", "--results", "2"], env=env)


if __name__ == "__main__":
    main()

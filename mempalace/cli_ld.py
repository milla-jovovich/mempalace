from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from . import cli as legacy_cli
from .integration_profile import mcp_command, server_command
from .operation_registry import cli_registry_view, mcp_tool_registry_view, projected_registry


def _mcp_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mempalace mcp")
    parser.add_argument("--palace", default=None)
    return parser


def _registry_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mempalace registry")
    parser.add_argument("view", nargs="?", choices=["runtime", "cli", "mcp"], default="runtime")
    return parser


def _run_mcp(argv: list[str]) -> int:
    args = _mcp_parser().parse_args(argv)
    quick_add_parts = [mcp_command()]
    if args.palace:
        quick_add_parts.extend(["--palace", str(Path(args.palace).expanduser())])
    quick_add = " ".join(shlex.quote(part) for part in quick_add_parts)
    direct_server_cmd = server_command(args.palace)

    print("MemPalace MCP quick setup:")
    print(f"  claude mcp add mempalace -- {quick_add}")
    print("\nRun the server directly:")
    print(f"  {direct_server_cmd}")
    if not args.palace:
        print("\nOptional custom palace:")
        print("  claude mcp add mempalace -- mempalace-mcp --palace /path/to/palace")
        print("  mempalace-mcp --palace /path/to/palace")
    return 0


def _run_registry(argv: list[str]) -> int:
    args = _registry_parser().parse_args(argv)
    if args.view == "cli":
        payload = cli_registry_view()
    elif args.view == "mcp":
        payload = mcp_tool_registry_view()
    else:
        payload = projected_registry()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def main() -> None:
    argv = sys.argv[1:]
    if argv:
        if argv[0] == "registry":
            raise SystemExit(_run_registry(argv[1:]))
        if argv[0] == "mcp":
            raise SystemExit(_run_mcp(argv[1:]))
    legacy_cli.main()


if __name__ == "__main__":
    main()

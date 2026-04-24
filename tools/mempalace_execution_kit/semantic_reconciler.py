#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


@dataclass(frozen=True)
class ClassifiedPath:
    path: str
    path_class: str
    action: str
    changed_in_base: bool
    changed_in_incoming: bool


def run_git(args: list[str], cwd: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=str(cwd), text=True).strip()


def load_policy(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def changed_files(repo_root: Path, ancestor: str, ref: str) -> set[str]:
    out = run_git(["diff", "--name-only", f"{ancestor}..{ref}"], repo_root)
    return {line for line in out.splitlines() if line}


def merge_base(repo_root: Path, base_ref: str, incoming_ref: str) -> str:
    return run_git(["merge-base", base_ref, incoming_ref], repo_root)


def classify_path(path: str, policy: dict) -> tuple[str, str]:
    classes = policy.get("classes", {})
    for class_name, body in classes.items():
        for pattern in body.get("paths", []) or []:
            if fnmatch.fnmatch(path, pattern):
                return class_name, body.get("action", "manual")
    return "foreign_or_unknown", "manual"


def classify_all(paths: Iterable[str], base_changed: set[str], incoming_changed: set[str], policy: dict) -> list[ClassifiedPath]:
    out: list[ClassifiedPath] = []
    for path in sorted(set(paths)):
        path_class, action = classify_path(path, policy)
        out.append(
            ClassifiedPath(
                path=path,
                path_class=path_class,
                action=action,
                changed_in_base=path in base_changed,
                changed_in_incoming=path in incoming_changed,
            )
        )
    return out


def build_plan(entries: list[ClassifiedPath], mode: str, policy: dict, base_ref: str, incoming_ref: str, ancestor: str) -> dict:
    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        grouped.setdefault(entry.path_class, []).append(
            {
                "path": entry.path,
                "action": entry.action,
                "changed_in_base": entry.changed_in_base,
                "changed_in_incoming": entry.changed_in_incoming,
            }
        )

    counts = {
        class_name: len(items)
        for class_name, items in grouped.items()
    }

    return {
        "mode": mode,
        "base_ref": base_ref,
        "incoming_ref": incoming_ref,
        "ancestor_ref": ancestor,
        "policy_repo": policy.get("repo"),
        "counts_by_class": counts,
        "generators": policy.get("generators", []),
        "verifiers": policy.get("verifiers", []),
        "classes": grouped,
    }


def write_outputs(repo_root: Path, plan: dict) -> tuple[Path, Path]:
    out_dir = repo_root / ".codespaces"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "reconciliation-report.json"
    md_path = out_dir / "reconciliation-plan.md"
    json_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Reconciliation plan",
        "",
        f"- mode: `{plan['mode']}`",
        f"- base_ref: `{plan['base_ref']}`",
        f"- incoming_ref: `{plan['incoming_ref']}`",
        f"- ancestor_ref: `{plan['ancestor_ref']}`",
        "",
        "## Counts by class",
        "",
    ]
    for class_name, count in sorted(plan.get("counts_by_class", {}).items()):
        lines.append(f"- `{class_name}`: {count}")
    lines.extend(["", "## Actions", ""])
    for class_name, items in sorted(plan.get("classes", {}).items()):
        lines.append(f"### {class_name}")
        lines.append("")
        for item in items:
            lines.append(
                f"- `{item['path']}` — `{item['action']}` (base={item['changed_in_base']}, incoming={item['changed_in_incoming']})"
            )
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Policy-driven semantic branch reconciler")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--mode", choices=["internal", "external"], default="internal")
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--incoming-ref", required=True)
    parser.add_argument("--ancestor-ref", default=None)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    policy = load_policy(Path(args.policy).expanduser().resolve())
    ancestor = args.ancestor_ref or merge_base(repo_root, args.base_ref, args.incoming_ref)
    base_changed = changed_files(repo_root, ancestor, args.base_ref)
    incoming_changed = changed_files(repo_root, ancestor, args.incoming_ref)
    entries = classify_all(base_changed | incoming_changed, base_changed, incoming_changed, policy)
    plan = build_plan(entries, args.mode, policy, args.base_ref, args.incoming_ref, ancestor)
    json_path, md_path = write_outputs(repo_root, plan)
    print(json.dumps({"report": str(json_path), "plan": str(md_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

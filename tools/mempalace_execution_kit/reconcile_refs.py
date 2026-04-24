#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]


class ReconcileError(RuntimeError):
    pass


@dataclass
class Rule:
    name: str
    policy: str
    include: list[str]
    exclude: list[str]
    notes: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rule":
        return cls(
            name=str(data.get("name", "unnamed-rule")),
            policy=str(data.get("policy", "manual")),
            include=[str(v) for v in data.get("include", [])],
            exclude=[str(v) for v in data.get("exclude", [])],
            notes=data.get("notes"),
        )

    def matches(self, path: str) -> bool:
        if self.include and not any(fnmatch.fnmatch(path, pattern) for pattern in self.include):
            return False
        if self.exclude and any(fnmatch.fnmatch(path, pattern) for pattern in self.exclude):
            return False
        return bool(self.include)


@dataclass
class PlanEntry:
    path: str
    status: str
    rule: str
    policy: str
    action: str
    notes: str | None = None


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT_DIR,
        check=check,
        text=True,
        capture_output=True,
    )


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    merged_rules: list[dict[str, Any]] = []
    for parent in data.get("extends", []) or []:
        parent_path = (path.parent / parent).resolve()
        parent_data = load_manifest(parent_path)
        merged_rules.extend(parent_data.get("rules", []))
    merged_rules.extend(data.get("rules", []))
    data["rules"] = merged_rules
    return data


def parse_diff(current_ref: str, incoming_ref: str) -> list[tuple[str, str]]:
    proc = run_git("diff", "--name-status", f"{current_ref}..{incoming_ref}")
    out: list[tuple[str, str]] = []
    for raw_line in proc.stdout.splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split("\t")
        status = parts[0]
        path = parts[-1]
        out.append((status, path))
    return out


def classify(path: str, rules: list[Rule], default_policy: str) -> Rule:
    for rule in rules:
        if rule.matches(path):
            return rule
    return Rule(name="default", policy=default_policy, include=["**"], exclude=[])


def action_for(status: str, policy: str) -> str:
    if policy == "keep_current":
        return "checkout-current"
    if policy == "prefer_incoming":
        return "checkout-incoming"
    if policy == "regenerate":
        return "regenerate"
    if policy == "drop_incoming":
        return "drop-incoming"
    return "manual"


def path_exists_in_ref(ref: str, path: str) -> bool:
    proc = run_git("cat-file", "-e", f"{ref}:{path}", check=False)
    return proc.returncode == 0


def checkout_path(ref: str, path: str) -> None:
    if path_exists_in_ref(ref, path):
        run_git("checkout", ref, "--", path)
    else:
        target = ROOT_DIR / path
        if target.exists():
            if target.is_dir():
                raise ReconcileError(f"Ref {ref} does not contain directory target {path}")
            target.unlink()


def remove_path(path: str) -> None:
    target = ROOT_DIR / path
    if target.exists() and target.is_file():
        target.unlink()


def run_commands(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for command in commands:
        name = str(command.get("name", command.get("run", "unnamed")))
        run_spec = str(command["run"])
        proc = subprocess.run(
            run_spec,
            cwd=ROOT_DIR,
            shell=True,
            text=True,
            capture_output=True,
        )
        result = {
            "name": name,
            "run": run_spec,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        results.append(result)
        if proc.returncode != 0:
            raise ReconcileError(f"Command failed: {name}\n{proc.stderr or proc.stdout}")
    return results


def build_plan(manifest: dict[str, Any], current_ref: str, incoming_ref: str) -> list[PlanEntry]:
    rules = [Rule.from_dict(item) for item in manifest.get("rules", [])]
    default_policy = str(manifest.get("defaults", {}).get("policy", "manual"))
    plan: list[PlanEntry] = []
    for status, path in parse_diff(current_ref, incoming_ref):
        rule = classify(path, rules, default_policy)
        plan.append(
            PlanEntry(
                path=path,
                status=status,
                rule=rule.name,
                policy=rule.policy,
                action=action_for(status, rule.policy),
                notes=rule.notes,
            )
        )
    return plan


def apply_plan(plan: list[PlanEntry], current_ref: str, incoming_ref: str) -> None:
    for entry in plan:
        if entry.action in {"manual", "regenerate"}:
            continue
        if entry.action in {"checkout-current", "drop-incoming"}:
            checkout_path(current_ref, entry.path)
            continue
        if entry.action == "checkout-incoming":
            checkout_path(incoming_ref, entry.path)
            continue
        raise ReconcileError(f"Unsupported action: {entry.action}")


def summarize(plan: list[PlanEntry]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for entry in plan:
        counts[entry.action] = counts.get(entry.action, 0) + 1
    return {
        "entries": [entry.__dict__ for entry in plan],
        "counts": counts,
        "manual_paths": [entry.path for entry in plan if entry.action == "manual"],
        "regenerate_paths": [entry.path for entry in plan if entry.action == "regenerate"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manifest-driven branch reconciliation engine")
    parser.add_argument("--manifest", required=True, help="Path to reconciliation manifest JSON")
    parser.add_argument("--current-ref", required=True, help="Current/ref authority to preserve")
    parser.add_argument("--incoming-ref", required=True, help="Incoming/upstream ref to fold in")
    parser.add_argument("--apply", action="store_true", help="Apply non-manual decisions to the worktree")
    parser.add_argument("--report", default=".codespaces/reconcile-report.json", help="Path to JSON report")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = load_manifest(manifest_path)
    plan = build_plan(manifest, args.current_ref, args.incoming_ref)

    if args.apply:
        apply_plan(plan, args.current_ref, args.incoming_ref)
        post_actions = manifest.get("post_actions", []) or []
        verifications = manifest.get("verification", []) or []
        command_results = {
            "post_actions": run_commands(post_actions) if post_actions else [],
            "verification": run_commands(verifications) if verifications else [],
        }
    else:
        command_results = {"post_actions": [], "verification": []}

    report = {
        "manifest": str(manifest_path),
        "current_ref": args.current_ref,
        "incoming_ref": args.incoming_ref,
        "applied": bool(args.apply),
        **summarize(plan),
        **command_results,
    }
    report_path = Path(args.report).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

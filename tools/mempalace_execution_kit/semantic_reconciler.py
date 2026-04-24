#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from dataclasses import asdict, dataclass
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


@dataclass(frozen=True)
class Resolution:
    path: str
    path_class: str
    action: str
    decision: str
    changed_in_base: bool
    changed_in_incoming: bool
    base_blob: str | None
    incoming_blob: str | None
    reason: str


@dataclass(frozen=True)
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str


def run_git(args: list[str], cwd: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=str(cwd), text=True).strip()


def run_git_bytes(args: list[str], cwd: Path) -> bytes:
    return subprocess.check_output(["git", *args], cwd=str(cwd))


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


def classify_all(
    paths: Iterable[str],
    base_changed: set[str],
    incoming_changed: set[str],
    policy: dict,
) -> list[ClassifiedPath]:
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


def ref_blob(repo_root: Path, ref: str, path: str) -> str | None:
    try:
        return run_git(["rev-parse", f"{ref}:{path}"], repo_root)
    except subprocess.CalledProcessError:
        return None


def checkout_path_from_ref(repo_root: Path, ref: str, path: str) -> None:
    blob = ref_blob(repo_root, ref, path)
    target = repo_root / path
    if blob is None:
        if target.exists():
            target.unlink()
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(run_git_bytes(["show", f"{ref}:{path}"], repo_root))


def ensure_clean_worktree(repo_root: Path) -> None:
    status = run_git(["status", "--porcelain"], repo_root)
    if status:
        raise RuntimeError("Working tree is not clean; refuse apply mode without a clean checkout")


def decide_resolution(repo_root: Path, entry: ClassifiedPath, base_ref: str, incoming_ref: str) -> Resolution:
    base_blob = ref_blob(repo_root, base_ref, entry.path)
    incoming_blob = ref_blob(repo_root, incoming_ref, entry.path)
    same_blob = base_blob == incoming_blob

    if entry.action == "regenerate":
        return Resolution(
            path=entry.path,
            path_class=entry.path_class,
            action=entry.action,
            decision="regenerate",
            changed_in_base=entry.changed_in_base,
            changed_in_incoming=entry.changed_in_incoming,
            base_blob=base_blob,
            incoming_blob=incoming_blob,
            reason="Derived artifacts must be regenerated from resolved authority.",
        )

    if entry.action == "prefer_incoming":
        return Resolution(
            path=entry.path,
            path_class=entry.path_class,
            action=entry.action,
            decision="checkout_incoming",
            changed_in_base=entry.changed_in_base,
            changed_in_incoming=entry.changed_in_incoming,
            base_blob=base_blob,
            incoming_blob=incoming_blob,
            reason="Policy prefers incoming content for this surface.",
        )

    if same_blob:
        return Resolution(
            path=entry.path,
            path_class=entry.path_class,
            action=entry.action,
            decision="keep_base",
            changed_in_base=entry.changed_in_base,
            changed_in_incoming=entry.changed_in_incoming,
            base_blob=base_blob,
            incoming_blob=incoming_blob,
            reason="Both refs resolve to the same blob.",
        )

    if entry.action in {"semantic_merge", "structured_merge"}:
        if entry.changed_in_incoming and not entry.changed_in_base:
            return Resolution(
                path=entry.path,
                path_class=entry.path_class,
                action=entry.action,
                decision="checkout_incoming",
                changed_in_base=entry.changed_in_base,
                changed_in_incoming=entry.changed_in_incoming,
                base_blob=base_blob,
                incoming_blob=incoming_blob,
                reason="Only incoming changed this path.",
            )
        if entry.changed_in_base and not entry.changed_in_incoming:
            return Resolution(
                path=entry.path,
                path_class=entry.path_class,
                action=entry.action,
                decision="keep_base",
                changed_in_base=entry.changed_in_base,
                changed_in_incoming=entry.changed_in_incoming,
                base_blob=base_blob,
                incoming_blob=incoming_blob,
                reason="Only base changed this path.",
            )
        return Resolution(
            path=entry.path,
            path_class=entry.path_class,
            action=entry.action,
            decision="manual",
            changed_in_base=entry.changed_in_base,
            changed_in_incoming=entry.changed_in_incoming,
            base_blob=base_blob,
            incoming_blob=incoming_blob,
            reason="Both refs changed this path and no safe automatic merge policy exists.",
        )

    return Resolution(
        path=entry.path,
        path_class=entry.path_class,
        action=entry.action,
        decision="manual",
        changed_in_base=entry.changed_in_base,
        changed_in_incoming=entry.changed_in_incoming,
        base_blob=base_blob,
        incoming_blob=incoming_blob,
        reason="Unknown path class or manual-only policy.",
    )


def run_command(command: str, cwd: Path) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        shell=True,
        capture_output=True,
        check=False,
    )
    return CommandResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def build_report(
    entries: list[ClassifiedPath],
    resolutions: list[Resolution],
    mode: str,
    policy: dict,
    base_ref: str,
    incoming_ref: str,
    ancestor: str,
    command_results: list[CommandResult],
    manual_conflicts: list[Resolution],
) -> dict:
    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        grouped.setdefault(entry.path_class, []).append(asdict(entry))

    counts = {class_name: len(items) for class_name, items in grouped.items()}
    decision_counts: dict[str, int] = {}
    for resolution in resolutions:
        decision_counts[resolution.decision] = decision_counts.get(resolution.decision, 0) + 1

    return {
        "mode": mode,
        "base_ref": base_ref,
        "incoming_ref": incoming_ref,
        "ancestor_ref": ancestor,
        "policy_repo": policy.get("repo"),
        "counts_by_class": counts,
        "decision_counts": decision_counts,
        "generators": policy.get("generators", []),
        "verifiers": policy.get("verifiers", []),
        "classes": grouped,
        "resolutions": [asdict(item) for item in resolutions],
        "manual_conflicts": [asdict(item) for item in manual_conflicts],
        "executions": [asdict(item) for item in command_results],
    }


def write_outputs(repo_root: Path, report: dict) -> tuple[Path, Path, Path]:
    out_dir = repo_root / ".codespaces"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "reconciliation-report.json"
    md_path = out_dir / "reconciliation-plan.md"
    conflicts_path = out_dir / "manual-conflicts.json"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    conflicts_path.write_text(json.dumps(report.get("manual_conflicts", []), indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Reconciliation plan",
        "",
        f"- mode: `{report['mode']}`",
        f"- base_ref: `{report['base_ref']}`",
        f"- incoming_ref: `{report['incoming_ref']}`",
        f"- ancestor_ref: `{report['ancestor_ref']}`",
        "",
        "## Counts by class",
        "",
    ]
    for class_name, count in sorted(report.get("counts_by_class", {}).items()):
        lines.append(f"- `{class_name}`: {count}")
    lines.extend(["", "## Decisions", ""])
    for decision, count in sorted(report.get("decision_counts", {}).items()):
        lines.append(f"- `{decision}`: {count}")
    lines.extend(["", "## Actions", ""])
    for class_name, items in sorted(report.get("classes", {}).items()):
        lines.append(f"### {class_name}")
        lines.append("")
        for item in items:
            lines.append(
                f"- `{item['path']}` — `{item['action']}` (base={item['changed_in_base']}, incoming={item['changed_in_incoming']})"
            )
        lines.append("")
    if report.get("manual_conflicts"):
        lines.extend(["## Manual conflicts", ""])
        for item in report["manual_conflicts"]:
            lines.append(f"- `{item['path']}` — {item['reason']}")
        lines.append("")
    if report.get("executions"):
        lines.extend(["## Executions", ""])
        for item in report["executions"]:
            lines.append(f"- `{item['command']}` -> `{item['returncode']}`")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path, conflicts_path


def apply_resolutions(
    repo_root: Path,
    resolutions: list[Resolution],
    incoming_ref: str,
) -> list[Resolution]:
    manual_conflicts: list[Resolution] = []
    for resolution in resolutions:
        if resolution.decision == "checkout_incoming":
            checkout_path_from_ref(repo_root, incoming_ref, resolution.path)
        elif resolution.decision == "manual":
            manual_conflicts.append(resolution)
    return manual_conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description="Policy-driven semantic branch reconciler")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--mode", choices=["internal", "external"], default="internal")
    parser.add_argument("--action", choices=["plan", "apply"], default="plan")
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--incoming-ref", required=True)
    parser.add_argument("--ancestor-ref", default=None)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--run-verifiers-with-manual-conflicts", action="store_true")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    policy = load_policy(Path(args.policy).expanduser().resolve())
    ancestor = args.ancestor_ref or merge_base(repo_root, args.base_ref, args.incoming_ref)
    base_changed = changed_files(repo_root, ancestor, args.base_ref)
    incoming_changed = changed_files(repo_root, ancestor, args.incoming_ref)
    entries = classify_all(base_changed | incoming_changed, base_changed, incoming_changed, policy)
    resolutions = [
        decide_resolution(repo_root, entry, args.base_ref, args.incoming_ref)
        for entry in entries
    ]

    command_results: list[CommandResult] = []
    manual_conflicts: list[Resolution] = []

    if args.action == "apply":
        if not args.allow_dirty:
            ensure_clean_worktree(repo_root)
        manual_conflicts = apply_resolutions(repo_root, resolutions, args.incoming_ref)
        for command in policy.get("generators", []):
            result = run_command(command, repo_root)
            command_results.append(result)
            if result.returncode != 0:
                report = build_report(
                    entries,
                    resolutions,
                    args.mode,
                    policy,
                    args.base_ref,
                    args.incoming_ref,
                    ancestor,
                    command_results,
                    manual_conflicts,
                )
                json_path, md_path, conflicts_path = write_outputs(repo_root, report)
                print(json.dumps({"report": str(json_path), "plan": str(md_path), "manual_conflicts": str(conflicts_path)}, indent=2))
                return 1
        if not manual_conflicts or args.run_verifiers_with_manual_conflicts:
            for command in policy.get("verifiers", []):
                result = run_command(command, repo_root)
                command_results.append(result)
                if result.returncode != 0:
                    report = build_report(
                        entries,
                        resolutions,
                        args.mode,
                        policy,
                        args.base_ref,
                        args.incoming_ref,
                        ancestor,
                        command_results,
                        manual_conflicts,
                    )
                    json_path, md_path, conflicts_path = write_outputs(repo_root, report)
                    print(json.dumps({"report": str(json_path), "plan": str(md_path), "manual_conflicts": str(conflicts_path)}, indent=2))
                    return 1

    report = build_report(
        entries,
        resolutions,
        args.mode,
        policy,
        args.base_ref,
        args.incoming_ref,
        ancestor,
        command_results,
        manual_conflicts,
    )
    json_path, md_path, conflicts_path = write_outputs(repo_root, report)
    print(json.dumps({"report": str(json_path), "plan": str(md_path), "manual_conflicts": str(conflicts_path)}, indent=2))

    if args.action == "apply" and manual_conflicts and not args.run_verifiers_with_manual_conflicts:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

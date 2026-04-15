"""Phase 0 go/no-go gate aggregator.

Checks all 9 Phase 0 gates and exits 0 if all green, 1 if any red.
Gates 6-9 require A5000 hardware and completed benchmark runs.

Usage:
    python benchmarks/phase0_gate_check.py
    python benchmarks/phase0_gate_check.py --skip-hardware
"""

from __future__ import annotations

import argparse
import importlib
import json
import sqlite3
import sys
from pathlib import Path


def check_gate_1_schema_migration() -> tuple[bool, str]:
    """Gate 1: schema migration adds source_drawer_ids and source."""
    try:
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            from mempalace.knowledge_graph import KnowledgeGraph
            kg = KnowledgeGraph(os.path.join(tmp, "kg.db"))
            cols = {r[1] for r in kg._conn().execute("PRAGMA table_info(triples)")}
            if "source_drawer_ids" in cols and "source" in cols:
                return True, "source_drawer_ids and source columns present"
            return False, f"Missing columns. Got: {cols}"
    except Exception as e:
        return False, str(e)


def check_gate_2_fts5() -> tuple[bool, str]:
    """Gate 2: FTS5 trigram index and find_entities_by_name_trigram work."""
    try:
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            from mempalace.knowledge_graph import KnowledgeGraph
            kg = KnowledgeGraph(os.path.join(tmp, "kg.db"))
            kg.add_entity("Alice Smith", entity_type="person")
            results = kg.find_entities_by_name_trigram("alice")
            if results and results[0]["name"] == "Alice Smith":
                return True, "FTS5 trigram substring lookup works"
            return False, f"Expected Alice Smith, got: {results}"
    except Exception as e:
        return False, str(e)


def check_gate_3_upsert_triple() -> tuple[bool, str]:
    """Gate 3: upsert_triple inserts and updates correctly."""
    try:
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            from mempalace.knowledge_graph import KnowledgeGraph
            kg = KnowledgeGraph(os.path.join(tmp, "kg.db"))
            r1 = kg.upsert_triple("Alice", "knows", "Ben", confidence=0.5)
            r2 = kg.upsert_triple("Alice", "knows", "Ben", confidence=0.9)
            if r1.inserted and r2.updated and r1.triple_id == r2.triple_id:
                return True, "upsert_triple inserts and updates correctly"
            return False, f"r1={r1}, r2={r2}"
    except Exception as e:
        return False, str(e)


def check_gate_4_lock_scope() -> tuple[bool, str]:
    """Gate 4: _write_lock exists, no _lock references."""
    try:
        import inspect
        from mempalace.knowledge_graph import KnowledgeGraph
        src = inspect.getsource(KnowledgeGraph)
        has_write_lock = "_write_lock" in src
        no_plain_lock = "self._lock" not in src
        if has_write_lock and no_plain_lock:
            return True, "_write_lock present, _lock removed"
        issues = []
        if not has_write_lock:
            issues.append("_write_lock not found")
        if not no_plain_lock:
            issues.append("self._lock still present")
        return False, "; ".join(issues)
    except Exception as e:
        return False, str(e)


def check_gate_5_walker_cli() -> tuple[bool, str]:
    """Gate 5: mempalace walker subcommand group registered."""
    try:
        from mempalace import cli
        import inspect
        src = inspect.getsource(cli)
        if "walker" in src and "cmd_walker_init" in src:
            return True, "walker subcommand group present"
        return False, "walker subcommand not found in cli.py"
    except Exception as e:
        return False, str(e)


def check_gate_6_vllm_bench(benchmarks_md: Path) -> tuple[bool, str]:
    """Gate 6: vLLM benchmark results present in phase0_benchmarks.md."""
    if not benchmarks_md.exists():
        return False, f"{benchmarks_md} not found — run phase0_vllm_bench.py on A5000"
    content = benchmarks_md.read_text()
    if "vLLM walker benchmark" in content and "Prefill p50" in content:
        return True, "vLLM benchmark results present"
    return False, "vLLM benchmark section missing or incomplete"


def check_gate_7_gliner_bench(benchmarks_md: Path) -> tuple[bool, str]:
    """Gate 7: GLiNER benchmark results present."""
    if not benchmarks_md.exists():
        return False, f"{benchmarks_md} not found"
    content = benchmarks_md.read_text()
    if "GLiNER entity extraction benchmark" in content and "Throughput p50" in content:
        return True, "GLiNER benchmark results present"
    return False, "GLiNER benchmark section missing"


def check_gate_8_locomo_results() -> tuple[bool, str]:
    """Gate 8: LoCoMo baseline results file exists."""
    p = Path("benchmarks/results_walk_locomo_baseline.jsonl")
    if p.exists() and p.stat().st_size > 0:
        return True, f"{p} exists with data"
    return False, f"{p} missing — run walk_bench.py against LoCoMo data"


def check_gate_9_walker_init() -> tuple[bool, str]:
    """Gate 9: walker init succeeds on FULL-tier hardware (simulated)."""
    try:
        import tempfile
        from unittest.mock import patch
        from mempalace import cli
        from mempalace.walker.gpu_detect import HardwareTier, WalkerHardware

        fake_hw = WalkerHardware(HardwareTier.FULL, "NVIDIA RTX A5000", 24.0)
        with tempfile.TemporaryDirectory() as tmp:
            import os
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = tmp
            try:
                with patch("mempalace.walker.gpu_detect.detect_hardware", return_value=fake_hw):
                    rc = cli.main(["walker", "init"])
            finally:
                if old_home:
                    os.environ["HOME"] = old_home
                else:
                    del os.environ["HOME"]
        if rc == 0:
            return True, "walker init exits 0 on FULL-tier hardware"
        return False, f"walker init returned {rc}"
    except Exception as e:
        return False, str(e)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-hardware", action="store_true",
        help="Skip gates 6-9 (require A5000 hardware or completed benchmark runs)",
    )
    parser.add_argument(
        "--benchmarks-md",
        type=Path,
        default=Path("benchmarks/phase0_benchmarks.md"),
    )
    args = parser.parse_args(argv)

    gates = [
        ("Gate 1", "Schema migration", check_gate_1_schema_migration),
        ("Gate 2", "FTS5 trigram index", check_gate_2_fts5),
        ("Gate 3", "upsert_triple", check_gate_3_upsert_triple),
        ("Gate 4", "Lock scope reduction", check_gate_4_lock_scope),
        ("Gate 5", "Walker CLI", check_gate_5_walker_cli),
    ]

    hardware_gates = [
        ("Gate 6", "vLLM benchmark", lambda: check_gate_6_vllm_bench(args.benchmarks_md)),
        ("Gate 7", "GLiNER benchmark", lambda: check_gate_7_gliner_bench(args.benchmarks_md)),
        ("Gate 8", "LoCoMo results", check_gate_8_locomo_results),
        ("Gate 9", "walker init (simulated)", check_gate_9_walker_init),
    ]

    if not args.skip_hardware:
        gates.extend(hardware_gates)

    print(f"{'Gate':<10} {'Name':<30} {'Status':<10} Notes")
    print("─" * 80)

    all_green = True
    for gate_id, name, check_fn in gates:
        ok, note = check_fn()
        status = "✅ GREEN" if ok else "❌ RED"
        print(f"{gate_id:<10} {name:<30} {status:<10} {note}")
        if not ok:
            all_green = False

    print("─" * 80)
    if all_green:
        print("All gates GREEN — Phase 0 complete.")
    else:
        print("Some gates RED — Phase 0 not complete.")

    return 0 if all_green else 1


if __name__ == "__main__":
    raise SystemExit(main())

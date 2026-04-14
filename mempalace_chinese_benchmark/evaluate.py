#!/usr/bin/env python3
"""
评估工具：对比基准线，生成报告

使用方法:
    python evaluate.py <result_file.json> [--baseline <baseline>]
"""

import json
import argparse
from pathlib import Path
from typing import Dict, Any


def compare_with_baseline(result: Dict, baseline: Dict) -> Dict:
    """将测试结果与基准线对比"""
    summary = result["summary"]
    baseline_summary = baseline["avg_keywords_recall"]

    comparison = {
        "avg_recall": {
            "actual": summary["avg_recall"],
            "baseline": baseline_summary,
            "diff": summary["avg_recall"] - baseline_summary,
            "relative": (summary["avg_recall"] / baseline_summary - 1) * 100 if baseline_summary > 0 else 0
        },
        "success_rate": {
            "actual": summary["success_rate"]
        },
        "ndcg": {
            "actual": summary["avg_ndcg"],
            "baseline": baseline.get("avg_ndcg", 0),
            "diff": summary["avg_ndcg"] - baseline.get("avg_ndcg", 0)
        },
        "latency": {
            "p50_actual": summary["p50_latency"],
            "p95_actual": summary["p95_latency"],
            "p50_baseline": baseline.get("p50_latency_ms", 0),
            "p95_baseline": baseline.get("p95_latency_ms", 0)
        }
    }

    return comparison


def print_report(result_path: Path, baseline_name: str):
    """打印评估报告"""
    with open(result_path) as f:
        result = json.load(f)

    with open(Path(__file__).parent / "baselines.json") as f:
        baselines = json.load(f)

    if baseline_name not in baselines["baselines"]:
        print(f"未知基准线: {baseline_name}")
        print(f"可用基准线: {', '.join(baselines['baselines'].keys())}")
        return

    baseline = baselines["baselines"][baseline_name]
    comparison = compare_with_baseline(result, baseline)

    print(f"\n{'='*60}")
    print(f"  {result_path.name} vs {baseline['model']}")
    print(f"{'='*60}\n")

    # Recall
    r = comparison["avg_recall"]
    color = "↑" if r["diff"] >= 0 else "↓"
    print(f"关键词召回率: {r['actual']*100:.1f}% (基准: {r['baseline']*100:.1f}%) "
          f"{color}{abs(r['diff'])*100:+.1f}% ({r['relative']:+.0f}%)")

    # Success Rate
    print(f"通过率: {comparison['success_rate']['actual']*100:.1f}%")

    # NDCG
    n = comparison["ndcg"]
    color = "↑" if n["diff"] >= 0 else "↓"
    print(f"NDCG: {n['actual']:.3f} (基准: {n['baseline']:.3f}) {color}{n['diff']:+.3f}")

    # Latency
    l = comparison["latency"]
    print(f"延迟 P50: {l['p50_actual']:.0f}ms (基准: {l['p50_baseline']:.0f}ms) "
          f"{'↑' if l['p50_actual'] <= l['p50_baseline'] else '↓'}{l['p50_actual']-l['p50_baseline']:+.0f}ms")
    print(f"延迟 P95: {l['p95_actual']:.0f}ms (基准: {l['p95_baseline']:.0f}ms) "
          f"{'↑' if l['p95_actual'] <= l['p95_baseline'] else '↓'}{l['p95_actual']-l['p95_baseline']:+.0f}ms")

    # 分场景对比
    print(f"\n{'─'*60}")
    print("分场景对比:")
    print(f"{'─'*60}")
    print(f"{'场景':<12} {'实际':<8} {'基准':<8} {'差异'}")
    print(f"{'─'*60}")

    for scenario, result_s in result["by_scenario"].items():
        baseline_s = baseline["by_scenario"].get(scenario, {})
        actual_r = result_s["success_rate"]
        baseline_r = baseline_s.get("success_rate", 0) if "success_rate" in baseline_s else 0
        diff = actual_r - baseline_r
        print(f"{scenario:<12} {actual_r*100:>6.0f}%  {baseline_r*100:>6.0f}%  "
              f"{'↑' if diff >= 0 else '↓'}{diff*100:+.0f}%")

    # 总体评分
    print(f"\n{'='*60}")
    if result["summary"]["avg_recall"] >= 0.9:
        grade = "优秀 🏆"
    elif result["summary"]["avg_recall"] >= 0.8:
        grade = "良好 ✅"
    elif result["summary"]["avg_recall"] >= 0.7:
        grade = "合格 ⚠️"
    else:
        grade = "需改进 ❌"
    print(f"  总体评级: {grade}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="评估 Benchmark 结果")
    parser.add_argument("result_file", help="benchmark_result_*.json 文件路径")
    parser.add_argument("--baseline", default="hash_embedding",
                       choices=["hash_embedding", "semantic_bge_small", "semantic_paraphrase_multilingual", "target"],
                       help="对比的基准线")
    args = parser.parse_args()

    print_report(Path(args.result_file), args.baseline)


if __name__ == "__main__":
    main()

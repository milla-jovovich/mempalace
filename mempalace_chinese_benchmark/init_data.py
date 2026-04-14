#!/usr/bin/env python3
"""
初始化脚本：复制测试数据到 benchmark 目录
"""
import shutil
from pathlib import Path
import json

THIS_DIR = Path(__file__).parent
DEMO_DATA_DIR = Path("../../mempalace_demo/data").resolve()
BENCHMARK_DATA_DIR = THIS_DIR / "data" / "convos"
BENCHMARK_DATA_DIR.mkdir(parents=True, exist_ok=True)

# 复制 mempalace_demo 的对话数据
if DEMO_DATA_DIR.exists():
    for jsonl_file in DEMO_DATA_DIR.glob("*.jsonl"):
        dest = BENCHMARK_DATA_DIR / jsonl_file.name
        if not dest.exists():
            shutil.copy(jsonl_file, dest)
            print(f"✓ 复制 {jsonl_file.name}")

# 创建示例对话（如果数据少）
if len(list(BENCHMARK_DATA_DIR.glob("*.jsonl"))) == 0:
    sample = {
        "type": "human",
        "message": {"content": "Python 中的列表推导式怎么写"}
    }
    sample2 = {
        "type": "human",
        "message": {"content": "React Native 如何实现热更新"}
    }
    sample_file = BENCHMARK_DATA_DIR / "sample_convo.jsonl"
    with open(sample_file, "w") as f:
        f.write(json.dumps(sample, ensure_ascii=False) + "\n")
        f.write(json.dumps(sample2, ensure_ascii=False) + "\n")
    print(f"✓ 创建示例数据: {sample_file.name}")

print(f"\n数据目录: {BENCHMARK_DATA_DIR}")
print(f"对话文件数: {len(list(BENCHMARK_DATA_DIR.glob('*.jsonl')))}")
print("\n现在可以运行: python run_benchmark.py")

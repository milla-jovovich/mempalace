#!/usr/bin/env python3
"""
MemPalace 中文 Benchmark 测试脚本

使用方法:
    python run_benchmark.py [--model <model>] [--top-k <k>] [--wing <wing>]

示例:
    python run_benchmark.py                               # 默认配置运行
    python run_benchmark.py --model bge-small-zh --top-k 10  # 指定模型和数量
"""

import json
import time
import argparse
import shutil
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

BENCHMARK_DIR = Path(__file__).parent
DATA_DIR = BENCHMARK_DIR / "data"
CONVOS_DIR = DATA_DIR / "convos"
TEST_CASES_DIR = BENCHMARK_DIR / "test_cases"
RESULTS_DIR = BENCHMARK_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────
# 颜色输出
# ─────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BLUE = "\033[94m"


def header(text: str):
    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}{text}{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}\n")


def ok(text: str):
    print(f"  {GREEN}✓{RESET} {text}")


def info(text: str):
    print(f"  {BLUE}ℹ{RESET} {text}")


def warn(text: str):
    print(f"  {YELLOW}⚠{RESET} {text}")


def err(text: str):
    print(f"  {RED}✗{RESET} {text}")


# ─────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────
def load_jsonl(path: Path) -> List[Dict]:
    """加载 JSONL 文件"""
    data = []
    with open(path) as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def timeit(func):
    """计时装饰器"""
    def wrapper(*args, **kwargs):
        t0 = time.time()
        result = func(*args, **kwargs)
        elapsed = (time.time() - t0) * 1000
        return result, elapsed
    return wrapper


def extract_cjk_bigrams(text: str) -> List[str]:
    """提取 CJK 双字词（用于关键词 boost）"""
    bigrams = []
    cjk_chars = [c for c in text if "\u4e00" <= c <= "\u9fff"]
    for i in range(len(cjk_chars) - 1):
        bigrams.append(cjk_chars[i] + cjk_chars[i + 1])
    return bigrams


# ─────────────────────────────────────────
# MemPalace 接口
# ─────────────────────────────────────────

# 全局：懒加载的语义嵌入函数
_chroma_ef = None


def _get_chroma_ef():
    """
    懒加载中文语义嵌入函数（与 demo.py 保持一致）
    """
    global _chroma_ef
    if _chroma_ef is not None:
        return _chroma_ef

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        warn("sentence-transformers 未安装，回退到 hash 嵌入")
        _chroma_ef = False
        return _chroma_ef

    models = [
        "BAAI/bge-small-zh-v1.5",
        "paraphrase-multilingual-MiniLM-L12-v2",
        "shibing624/text2vec-base-chinese",
    ]
    for model_name in models:
        try:
            model = SentenceTransformer(model_name)
            ok(f"语义嵌入模型: {model_name}")

            class _LocalSTE:
                def __init__(self, m):
                    self._m = m
                def __call__(self, input):
                    return self._m.encode(list(input), normalize_embeddings=True, show_progress_bar=False).tolist()

            _chroma_ef = _LocalSTE(model)
            return _chroma_ef
        except Exception as e:
            warn(f"  模型 {model_name} 加载失败: {e}")

    _chroma_ef = False
    return _chroma_ef


def _simple_embed(text: str, dim: int = 1024) -> List[float]:
    """轻量级 hash 嵌入（与 demo.py 保持一致）"""
    import hashlib, math
    vec = [0.0] * dim

    tokens = []
    ascii_buf = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if ascii_buf:
                tokens.extend("".join(ascii_buf).lower().split())
                ascii_buf.clear()
            tokens.append(ch)
        else:
            ascii_buf.append(ch)
    if ascii_buf:
        tokens.extend("".join(ascii_buf).lower().split())

    for i, t in enumerate(tokens):
        if not t:
            continue
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
        if i + 1 < len(tokens) and tokens[i + 1]:
            bg = t + tokens[i + 1]
            h2 = int(hashlib.md5(bg.encode()).hexdigest(), 16)
            vec[h2 % dim] += 0.5

    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _chunk_transcript(text: str, max_chars: int = 800) -> List[str]:
    """按完整 Q&A 对切分 transcript（与 demo.py 保持一致）"""
    chunks, current = [], []
    for line in text.split("\n"):
        if line.startswith("> ") and current:
            chunk_text = "\n".join(current).strip()
            if len(chunk_text) >= 30:
                if len(chunk_text) > 2000:
                    for i in range(0, len(chunk_text), 2000):
                        part = chunk_text[i:i + 2000].strip()
                        if len(part) >= 30:
                            chunks.append(part)
                else:
                    chunks.append(chunk_text)
            current = [line]
        else:
            current.append(line)
    if current:
        chunk_text = "\n".join(current).strip()
        if len(chunk_text) >= 30:
            if len(chunk_text) > 2000:
                for i in range(0, len(chunk_text), 2000):
                    part = chunk_text[i:i + 2000].strip()
                    if len(part) >= 30:
                        chunks.append(part)
            else:
                chunks.append(chunk_text)
    return chunks


def _build_simple_index(t: Dict, wing: str, palace_path: Path):
    """使用 chromadb 构建中文索引（与 demo.py 保持一致）"""
    try:
        import chromadb
    except ImportError:
        err("chromadb 未安装")
        return

    client = chromadb.PersistentClient(path=str(palace_path / "chroma"))
    col_name = f"mempalace_{wing}"
    try:
        client.delete_collection(col_name)
    except Exception:
        pass

    col = client.create_collection(col_name, metadata={"hnsw:space": "cosine"})

    # 读取 transcript 文件
    text = t["path"].read_text(encoding="utf-8")
    chunks = _chunk_transcript(text)
    ids, docs, metas = [], [], []
    for i, chunk in enumerate(chunks):
        ids.append(f"{t['name']}_{i}")
        docs.append(chunk)
        metas.append({"wing": wing, "room": "general", "source": t["name"], "chunk": i})

    if ids:
        # 检测语义模型状态
        ef = _get_chroma_ef()
        if ef:
            info(f"  使用语义嵌入计算 {len(docs)} 个 chunk")
            embeddings = ef(docs)
        else:
            warn(f"  语义模型不可用，回退到 hash embedding")
            warn(f"  原因可能是: sentence-transformers 未安装 或 模型下载失败")
            warn(f"  安装命令: pip install sentence-transformers")
            embeddings = [_simple_embed(chunk) for chunk in docs]
        col.upsert(ids=ids, documents=docs, embeddings=embeddings, metadatas=metas)
        ok(f"索引写入 {len(ids)} 个 chunk  ({col_name})")


def build_index(transcripts: List[Dict], palace_path: Path):
    """构建记忆索引（优先使用中文语义模型）"""
    header("构建记忆索引")

    ef = _get_chroma_ef()
    if ef:
        embed_desc = "BAAI/bge-small-zh（中文语义嵌入）"
    else:
        embed_desc = "hash bigram（轻量备用嵌入）"
    info(f"索引嵌入模型: {embed_desc}")

    if ef is False:
        err("语义模型不可用，hash embedding 上限约 55%")
        err("安装命令: pip install sentence-transformers")
        err("然后运行: python -c 'from sentence_transformers import SentenceTransformer; SentenceTransformer(\"BAAI/bge-small-zh-v1.5\")'")
        # 继续执行 hash embedding，但返回 True 避免阻塞
        warn("将继续使用 hash embedding 运行测试...")

    info("使用 chromadb 中文索引路径")
    for t in transcripts:
        wing = t.get("wing", "general")
        info(f"正在索引 {t['name']} → {wing} ...")
        _build_simple_index(t, wing, palace_path)
    ok("索引构建完成")
    return True


def search_memories(query: str, palace_path: Path, n_results: int = 8, wing: str = None):
    """搜索记忆：直接使用 chromadb（我们的索引结构自定义，不走 mempalace.searcher）"""
    # 强制走 chromadb 路径，忽略 mempalace.searcher
    return _search_chromadb(query, palace_path, n_results, wing)


def _search_chromadb(query: str, palace_path: Path, n_results: int, wing: str):
    """降级方案：直接查询 ChromaDB（与 demo.py 保持一致）"""
    try:
        import chromadb
    except ImportError:
        warn("ChromaDB 未安装")
        return []

    client = chromadb.PersistentClient(path=str(palace_path / "chroma"))
    raw_cols = client.list_collections()
    col_names = [c.name if hasattr(c, "name") else str(c) for c in raw_cols]

    info(f"  [DEBUG] palace_path={palace_path}, 查询='{query[:30]}...', wing='{wing}'")
    info(f"  [DEBUG] 可用集合={col_names}")
    info(f"  [DEBUG] wing 过滤: wing in col_name? -> {[(col, wing in col if wing else True) for col in col_names]}")

    # 增加 n_results 给 boost 更多候选
    fetch_n = min(n_results * 2, 20)

    all_results = []
    for col_name in col_names:
        if wing and wing not in col_name:
            info(f"  [DEBUG] 跳过集合 {col_name} (wing 不匹配)")
            continue
        try:
            col = client.get_collection(col_name)
            ef = _get_chroma_ef()
            if ef:
                query_emb = ef([query])[0]
            else:
                query_emb = _simple_embed(query)
            info(f"  [DEBUG] 查询集合 {col_name}, 查询向量维度={len(query_emb)}")
            res = col.query(query_embeddings=[query_emb], n_results=fetch_n)
            docs = res.get("documents", [[]])[0]
            distances = res.get("distances", [[]])[0]
            metas = res.get("metadatas", [[]])[0]
            info(f"    集合 {col_name}: 返回 {len(docs)} 条结果")
            for doc, dist, meta in zip(docs, distances, metas):
                all_results.append({
                    "text": doc,
                    "similarity": max(0.0, 1.0 - dist),
                    "wing": meta.get("wing", col_name),
                    "room": meta.get("room", "?"),
                    "metadata": meta,
                })
        except Exception as _e:
            warn(f"  查询集合 {col_name} 失败: {_e}")
            continue

    info(f"  [DEBUG] 合并结果总数: {len(all_results)}")

    # 关键词 boost（增强版：提高权重到 0.6）
    if all_results:
        query_tokens = set()
        # CJK bigrams（更强区分度）
        cjk_chars = [ch for ch in query if "\u4e00" <= ch <= "\u9fff"]
        for i in range(len(cjk_chars) - 1):
            query_tokens.add(cjk_chars[i] + cjk_chars[i + 1])
        # CJK trigrams（三字词，如"蔚来EP9"）
        for i in range(len(cjk_chars) - 2):
            query_tokens.add(cjk_chars[i] + cjk_chars[i + 1] + cjk_chars[i + 2])
        # ASCII words
        for w in query.lower().split():
            if len(w) >= 2:
                query_tokens.add(w)

        if query_tokens:
            info(f"  [DEBUG] 关键词 boost: 提取了 {len(query_tokens)} 个 token")
            for r in all_results:
                doc_text = r["text"]
                hit = sum(1 for t in query_tokens if t in doc_text)
                # 提升权重到 0.6
                r["similarity"] = r["similarity"] + (hit / len(query_tokens)) * 0.6

    all_results.sort(key=lambda x: x["similarity"], reverse=True)
    return all_results[:n_results]


# ─────────────────────────────────────────
# 评估指标
# ─────────────────────────────────────────
def compute_keyword_recall(hits: List[Dict], keywords: List[str]) -> float:
    """计算关键词召回率"""
    if not keywords:
        return 0.0
    all_text = " ".join(h.get("text", "") for h in hits)
    hit_count = sum(1 for kw in keywords if kw in all_text)
    return hit_count / len(keywords)


def compute_ndcg(hits: List[Dict], relevance_scores: List[int]) -> float:
    """计算 NDCG@K"""
    if not relevance_scores:
        return 0.0

    dcg = 0
    for i, score in enumerate(relevance_scores[:len(hits)]):
        dcg += score / (i + 2)  # log2(i+2)

    # 理想 DCG（按相关性降序）
    idcg = sum(score / (i + 2) for i, score in enumerate(sorted(relevance_scores, reverse=True)))

    return dcg / idcg if idcg > 0 else 0.0


# ─────────────────────────────────────────
# 测试用例加载和多场景组合
# ─────────────────────────────────────────
def load_all_test_cases() -> Tuple[List[Dict], Dict]:
    """加载所有测试用例，按场景分组"""
    all_cases = []
    by_scenario = defaultdict(list)

    scenario_files = {
        "factual": TEST_CASES_DIR / "factual.json",
        "technical": TEST_CASES_DIR / "technical.json",
        "longtail": TEST_CASES_DIR / "longtail.json",
        "multi_hop": TEST_CASES_DIR / "multi_hop.json",
    }

    for scenario, path in scenario_files.items():
        if path.exists():
            cases = json.load(open(path))
            for case in cases:
                case["scenario"] = scenario
                all_cases.append(case)
                by_scenario[scenario].append(case)
            info(f"加载 {scenario}: {len(cases)} 用例")
        else:
            warn(f"未找到 {path.name}，跳过")

    return all_cases, dict(by_scenario)


# ─────────────────────────────────────────
# 主测试流程
# ─────────────────────────────────────────
def run_benchmark(
    test_cases: List[Dict],
    transcripts: List[Dict],
    palace_path: Path,
    top_k: int = 8,
):
    """运行完整 benchmark"""
    header("中文 Benchmark 测试")

    # 统计信息
    stats = {
        "total": len(test_cases),
        "success": 0,
        "total_recall": 0.0,
        "total_ndcg": 0.0,
        "latencies": [],
        "by_scenario": defaultdict(lambda: {
            "count": 0,
            "success": 0,
            "avg_recall": 0.0,
            "avg_ndcg": 0.0,
        }),
    }

    all_results = []

    # 逐个测试
    for idx, case in enumerate(test_cases, 1):
        scenario = case.get("scenario", "unknown")
        query = case["query"]
        wing = case.get("wing")
        keywords = case.get("keywords", [])
        expected_recall = case.get("expected_recall", 0.5)

        print(f"\n{BOLD}[{idx}/{len(test_cases)}]{RESET} {case.get('name', query[:40])}")
        print(f"  场景: {scenario} | 难度: {case.get('difficulty', 1)} | Wing: {wing}")

        # 搜索
        t0 = time.time()
        hits = search_memories(query, palace_path, n_results=top_k, wing=wing)
        elapsed_ms = (time.time() - t0) * 1000

        # 计算 recall
        recall = compute_keyword_recall(hits, keywords)
        ndcg = compute_ndcg(hits, [1 if recall >= expected_recall else 0] * len(hits))

        success = recall >= expected_recall

        # 输出 Top-3
        if hits:
            for i, hit in enumerate(hits[:3], 1):
                preview = hit.get("text", "")[:80].replace("\n", " ")
                score = hit.get("similarity", 0)
                print(f"    #{i} [{score:.3f}] {preview}...")
        else:
            warn("  未检索到结果")

        # 输出 summary
        kw_count = sum(1 for kw in keywords if kw in " ".join(h.get("text", "") for h in hits)) if hits else 0
        status = f"{GREEN}PASS{RESET}" if success else f"{YELLOW}FAIL{RESET}"
        print(f"  关键词: {kw_count}/{len(keywords)}  Recall: {recall*100:.0f}%  "
              f"NDCG: {ndcg:.3f}  {status}  {elapsed_ms:.0f}ms")

        # 更新统计
        stats["success"] += success
        stats["total_recall"] += recall
        stats["total_ndcg"] += ndcg
        stats["latencies"].append(elapsed_ms)

        s = stats["by_scenario"][scenario]
        s["count"] += 1
        s["success"] += success
        s["avg_recall"] += recall
        s["avg_ndcg"] += ndcg

        all_results.append({
            "case_id": case.get("id", idx),
            "scenario": scenario,
            "query": query,
            "expected_recall": expected_recall,
            "actual_recall": recall,
            "ndcg": ndcg,
            "latency_ms": elapsed_ms,
            "success": success,
            "top_hits": hits[:3],
        })

    # 打印总体报告
    header("总体报告")
    n = stats["total"]
    print(f"  总用例数: {n}")
    print(f"  通过率: {stats['success']}/{n} = {stats['success']/n*100:.1f}%")
    print(f"  平均 Recall: {stats['total_recall']/n*100:.1f}%")
    print(f"  平均 NDCG: {stats['total_ndcg']/n:.3f}")

    # 延迟统计
    lats = sorted(stats["latencies"])
    print(f"  延迟 P50: {lats[len(lats)//2]:.0f}ms")
    print(f"  延迟 P95: {lats[int(len(lats)*0.95)]:.0f}ms")

    # 分场景报告
    print(f"\n{BOLD}分场景统计:{RESET}")
    for scenario, s in stats["by_scenario"].items():
        if s["count"] > 0:
            print(f"  {scenario}: {s['success']}/{s['count']} = {s['success']/s['count']*100:.0f}%  "
                  f"Recall {s['avg_recall']/s['count']*100:.0f}%  "
                  f"NDCG {s['avg_ndcg']/s['count']:.3f}")

    # 保存结果
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    result_file = RESULTS_DIR / f"benchmark_result_{timestamp}.json"
    with open(result_file, "w") as f:
        json.dump({
            "timestamp": timestamp,
            "config": {"top_k": top_k},
            "summary": {
                "total": n,
                "success": stats["success"],
                "success_rate": stats["success"] / n,
                "avg_recall": stats["total_recall"] / n,
                "avg_ndcg": stats["total_ndcg"] / n,
                "p50_latency": lats[len(lats)//2],
                "p95_latency": lats[int(len(lats)*0.95)],
            },
            "by_scenario": {k: {
                "count": v["count"],
                "success": v["success"],
                "success_rate": v["success"] / v["count"],
                "avg_recall": v["avg_recall"] / v["count"],
                "avg_ndcg": v["avg_ndcg"] / v["count"],
            } for k, v in stats["by_scenario"].items()},
            "cases": all_results,
        }, f, indent=2, ensure_ascii=False)
    info(f"结果已保存到 {result_file}")

    return stats


# ─────────────────────────────────────────
# 入口
# ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="MemPalace 中文 Benchmark 测试")
    parser.add_argument("--model", default=None, help="语义模型名称")
    parser.add_argument("--top-k", type=int, default=8, help="返回结果数量")
    parser.add_argument("--wing", default=None, help="指定 Wing 过滤")
    parser.add_argument("--no-rebuild", action="store_true", help="跳过索引重建")
    args = parser.parse_args()

    header("MemPalace 中文 Benchmark")

    # 加载测试用例
    test_cases, by_scenario = load_all_test_cases()
    if not test_cases:
        err("未找到任何测试用例")
        return

    # 加载对话数据
    CONVOS_DIR.mkdir(exist_ok=True)

    # 优先使用本地数据，若为空则尝试从 demo 复制
    convos = list(CONVOS_DIR.glob("*.jsonl")) + list(CONVOS_DIR.glob("*.txt"))
    if not convos:
        warn("数据目录为空，尝试从 mempalace_demo 复制...")
        demo_dir = Path("../../mempalace_demo/data").resolve()
        if demo_dir.exists():
            for jsonl_file in demo_dir.glob("*.jsonl"):
                dest = CONVOS_DIR / jsonl_file.name
                if not dest.exists():
                    shutil.copy(jsonl_file, dest)
                    info(f"  复制 {jsonl_file.name}")
            convos = list(CONVOS_DIR.glob("*.jsonl")) + list(CONVOS_DIR.glob("*.txt"))

    # Wing 映射：与 demo.py 保持一致
    wing_map = {
        "conversation_openclaw":  "wing_openclaw",
        "conversation_analysis":  "wing_analysis",
        "conversation_technical": "wing_technical",
        "conversation_qa":        "wing_qa",
    }

    transcripts = []
    for path in convos:
        transcripts.append({
            "name": path.stem,
            "path": path,
            "wing": wing_map.get(path.stem, f"wing_{path.stem}"),
        })
    info(f"找到 {len(transcripts)} 个对话文件")

    # 构建索引
    palace_path = BENCHMARK_DIR / "palace"
    if not args.no_rebuild:
        ok("开始构建索引...")
        if not build_index(transcripts, palace_path):
            err("索引构建失败")
            return
    else:
        ok("跳过索引重建")

    # 运行测试
    run_benchmark(test_cases, transcripts, palace_path, top_k=args.top_k)


if __name__ == "__main__":
    main()

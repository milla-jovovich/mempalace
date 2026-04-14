# MemPalace 中文 Benchmark 测试集

用于评估 MemPalace 对中文记忆的检索能力。

## 目录结构

```
mempalace_chinese_benchmark/
├── data/                    # 测试数据（对话历史）
│   ├── convos/             # 对话文本文件
│   └── test_manifest.json  # 对话元数据
├── test_cases/             # 测试用例（按场景分类）
│   ├── factual.json        # 事实检索
│   ├── technical.json      # 技术细节检索
│   ├── longtail.json       # 长尾/冷门知识
│   └── multi_hop.json      # 多跳推理
├── README.md               # 本文件
├── run_benchmark.py        # 主测试脚本
├── evaluate.py             # 评估工具
└── baselines.json          # 基准线参照
```

## 测试维度

### 1. 精确度指标
- **Keywords Recall**: 关键词召回率（答案中包含预期词汇的比例）
- **Semantic Score**: 语义相似度（嵌入模型的余弦 similarity）
- **NDCG**: 归一化折损累积增益（Top-K 排序质量）

### 2. 覆盖场景
| 场景 | 描述 | 难度 |
|------|------|------|
| Factual | 直接事实检索（人名、地名、数字） | ★ |
| Technical | 技术细节（API参数、配置项、错误码） | ★★ |
| Longtail | 长尾知识（产品名、型号号、历史事件） | ★★★ |
| Multi-hop | 多跳推理（需要跨多篇对话关联） | ★★★★ |

### 3. 语言特征
| 特征 | 测试点 |
|------|--------|
| CJK Tokenization | 中文分词准确性 |
| Homophone | 同音字/近义词（如"配置" vs "设置"） |
| Polysemy | 多义词消歧（如"接口"可以是API也可以是UI） |
| Entity Recognition | 人名、地名、品牌名、产品型号识别 |
| Number Matching | 中文数字（"一百二十五"） vs 阿拉伯数字（125） |

## 运行测试

```bash
cd mempalace_chinese_benchmark
python run_benchmark.py [--model <model>] [--top-k <k>]
```

## 基准线

| 指标 | Baseline | Target |
|------|----------|--------|
| Keywords Recall | 60% | 90%+ |
| Semantic Score@5 | 0.65 | 0.85+ |
| NDCG@10 | 0.58 | 0.80+ |
| Latency (P95) | 500ms | 300ms |

## 测试用例编写指南

### 查询设计
- 使用自然语言问题（不直接暴露关键词）
- 问题和答案使用不同的词汇表达（测试泛化能力）
- 包含否定、条件、比较等复杂句式

### Keywords 选择
- 5-7 个关键词为宜
- 包含专有名词（人名、品牌名、型号号）
- 避免查询语句中直接出现的词（防止作弊）

### Wing 选择
- 为每个数据源指定独立的 wing
- 测试跨 wing 检索能力

## 贡献规范

1. 新增测试用例请按场景分类到 `test_cases/` 对应文件
2. 每个用例需包含：`query`, `wing`, `keywords`, `difficulty`
3. 难度分级：1=简单, 2=中等, 3=困难, 4=专家
4. 提交前运行 `python run_benchmark.py` 验证

## License

MIT License
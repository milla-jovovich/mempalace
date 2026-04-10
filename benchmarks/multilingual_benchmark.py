#!/usr/bin/env python3
"""
Multilingual Benchmark — Quantitative scoring for MemPalace multilingual support.

Scores 6 dimensions on a 0-100 scale:
  1. Language Detection   — zh/en/unknown/fr classification accuracy
  2. Entity Detection     — Chinese name extraction precision & recall
  3. Room Classification  — correct room assignment (zh-Hans/zh-Hant/en/fr)
  4. Memory Extraction    — pattern detection across 5 memory types
  5. Search Quality       — semantic search relevance (requires ChromaDB)
  6. OpenCC Consistency   — simplified↔traditional conversion consistency

Languages tested: 簡中 (zh-Hans), 繁中 (zh-Hant), English, Français

Usage:
    python -m benchmarks.multilingual_benchmark
    python -m benchmarks.multilingual_benchmark --verbose
    python -m benchmarks.multilingual_benchmark --dim language_detection
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import List, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# SCORING FRAMEWORK
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TestCase:
    input: str
    expected: str  # expected output
    tags: List[str] = field(default_factory=list)  # e.g. ["zh", "simplified"]


@dataclass
class TestResult:
    case: TestCase
    actual: str
    passed: bool
    detail: str = ""


@dataclass
class DimensionScore:
    name: str
    score: float  # 0-100
    passed: int
    total: int
    failures: List[TestResult] = field(default_factory=list)
    duration_ms: float = 0.0


def _score_dimension(name: str, cases: List[TestCase], run_fn) -> DimensionScore:
    """Run test cases through a function and score results."""
    results = []
    t0 = time.time()
    for case in cases:
        try:
            actual = run_fn(case.input)
            valid_answers = case.expected.split("|")
            passed = actual in valid_answers
            results.append(
                TestResult(
                    case=case,
                    actual=str(actual),
                    passed=passed,
                    detail="" if passed else f"expected={case.expected}, got={actual}",
                )
            )
        except Exception as e:
            results.append(TestResult(case=case, actual=f"ERROR: {e}", passed=False, detail=str(e)))
    duration = (time.time() - t0) * 1000

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    score = (passed / total * 100) if total > 0 else 0
    failures = [r for r in results if not r.passed]
    return DimensionScore(
        name=name, score=score, passed=passed, total=total, failures=failures, duration_ms=duration
    )


# ─────────────────────────────────────────────────────────────────────────────
# DIMENSION 1: LANGUAGE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

LANGUAGE_DETECTION_CASES = [
    # === Simplified Chinese (簡中) ===
    TestCase("这是一段纯中文文本，用来测试语言检测功能。", "zh", ["zh-Hans"]),
    TestCase("我们今天讨论了系统架构的设计方案和技术选型。", "zh", ["zh-Hans"]),
    TestCase("数据库迁移完成后需要验证所有接口的正确性。", "zh", ["zh-Hans"]),
    TestCase("前端组件的状态管理需要重新设计，性能优化也很关键。", "zh", ["zh-Hans"]),
    TestCase("这个微服务的容错机制还不够完善，需要增加重试逻辑。", "zh", ["zh-Hans"]),
    # === Traditional Chinese (繁中) ===
    TestCase("這是一段純中文文本，用來測試語言檢測功能。", "zh", ["zh-Hant"]),
    TestCase("我們今天討論了系統架構的設計方案和技術選型。", "zh", ["zh-Hant"]),
    TestCase("資料庫遷移完成後需要驗證所有介面的正確性。", "zh", ["zh-Hant"]),
    TestCase("前端元件的狀態管理需要重新設計，效能優化也很關鍵。", "zh", ["zh-Hant"]),
    # === English ===
    TestCase("This is a pure English text for language detection testing.", "en", ["en"]),
    TestCase("The authentication module uses JWT tokens for session management.", "en", ["en"]),
    TestCase("We need to refactor the API endpoints to improve performance.", "en", ["en"]),
    TestCase(
        "The microservice architecture uses gRPC for inter-service communication.", "en", ["en"]
    ),
    # === French (Français) ===
    TestCase("Le code a un bug dans la base de données. Il faut corriger.", "en", ["fr"]),
    TestCase(
        "Nous avons décidé de migrer vers PostgreSQL pour de meilleures performances.", "en", ["fr"]
    ),
    TestCase(
        "L'architecture du système utilise des microservices déployés dans Docker.", "en", ["fr"]
    ),
    TestCase("Le module d'authentification gère les sessions avec des jetons JWT.", "en", ["fr"]),
    # === Spanish (Español) ===
    TestCase(
        "El sistema tiene un error en la base de datos que necesita corrección.", "en", ["es"]
    ),
    TestCase(
        "Decidimos migrar la arquitectura a microservicios para mejorar la escalabilidad.",
        "en",
        ["es"],
    ),
    TestCase(
        "La planificación del proyecto incluye tres fases con plazos definidos.", "en", ["es"]
    ),
    # === German (Deutsch) ===
    TestCase(
        "Der Code hat einen Fehler in der Datenbankabfrage. Wir müssen debuggen.", "en", ["de"]
    ),
    TestCase("Wir haben uns entschieden, auf PostgreSQL umzusteigen.", "en", ["de"]),
    TestCase("Die Systemarchitektur verwendet Microservices mit Docker-Containern.", "en", ["de"]),
    # === Japanese (日本語 — uses CJK kanji) ===
    TestCase("データベースのバグを修正する必要があります。", "zh", ["ja"]),
    TestCase("マイクロサービスアーキテクチャでシステムを再設計しました。", "zh", ["ja"]),
    TestCase("プロジェクトの計画を立てて、マイルストーンを設定する。", "zh", ["ja"]),
    # === Korean (한국어 — Hangul, not CJK ideographs) ===
    TestCase("안녕하세요 프로그래밍을 배우고 있습니다", "en", ["ko"]),
    TestCase("데이터베이스 마이그레이션을 완료했습니다", "en", ["ko"]),
    # === Mixed content (中英混合) ===
    TestCase("小明用 Python 写了一个 REST API 组件", "zh", ["mixed"]),
    TestCase("我们用 React + TypeScript 开发 frontend", "zh", ["mixed"]),
    TestCase("这个 bug 在 production 环境中出现了", "zh", ["mixed"]),
    TestCase("deploy 到 AWS 的 ECS cluster 上", "zh", ["mixed"]),
    # === Edge cases ===
    TestCase("", "unknown", ["edge"]),
    TestCase("   ", "unknown", ["edge"]),
    TestCase("12345 67890", "unknown", ["edge"]),
    TestCase("😀🎉🔥💻", "unknown", ["edge"]),
    TestCase("https://example.com/api/v2", "en", ["edge"]),
    TestCase("2024年3月15日", "zh", ["edge"]),
]


def _run_language_detection(text: str) -> str:
    from mempalace.language_detect import detect_language

    return detect_language(text)


# ─────────────────────────────────────────────────────────────────────────────
# DIMENSION 2: ENTITY DETECTION
# ─────────────────────────────────────────────────────────────────────────────

ENTITY_DETECTION_CASES = [
    # 2-char Chinese names (need 2+ occurrences)
    TestCase("张三说了很多话，张三还提到了项目进展。", "张三", ["zh", "2char"]),
    TestCase("李四觉得这个方案不错。李四决定参与项目。", "李四", ["zh", "2char"]),
    # 3-char Chinese names
    TestCase("王大明今天来了。王大明负责后端开发。", "王大明", ["zh", "3char"]),
    TestCase("张小红参加了会议。张小红提出了建议。", "张小红", ["zh", "3char"]),
    # Traditional Chinese names
    TestCase("張三說了很多話，張三還提到了項目進展。", "張三", ["zh", "traditional"]),
    # English names in Chinese text
    TestCase(
        "Simon和团队讨论了问题。Simon提出了方案。Simon又补充了几点。", "Simon", ["en", "mixed"]
    ),
    # Stopword filtering (should NOT be detected as names)
    TestCase("王国很大，王国有很多人。王国是国家。", "NONE", ["zh", "stopword"]),
    TestCase("马上就到，马上出发，马上完成。", "NONE", ["zh", "stopword"]),
    TestCase("高兴极了，高兴得不得了。高兴。", "NONE", ["zh", "stopword"]),
    # English names (baseline)
    TestCase("Alice said hello. Alice asked about it. Alice told us.", "Alice", ["en", "baseline"]),
]


def _run_entity_detection(text: str) -> str:
    from mempalace.entity_detector import extract_candidates

    candidates = extract_candidates(text)
    if not candidates:
        return "NONE"
    # Return the top candidate by frequency
    return max(candidates, key=candidates.get)


# ─────────────────────────────────────────────────────────────────────────────
# DIMENSION 3: ROOM CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

ROOM_CLASSIFICATION_CASES = [
    # Chinese technical
    TestCase(
        "我们需要修改代码来修复这个错误。调试了很久终于找到问题。部署到服务器上。",
        "technical",
        ["zh"],
    ),
    TestCase("函数的接口需要重构，数据库的查询也要优化。", "technical", ["zh"]),
    # Chinese architecture
    TestCase(
        "系统的架构设计需要重新考虑。模块和组件的结构不够合理。服务之间的依赖太复杂。",
        "architecture",
        ["zh"],
    ),
    # Chinese planning
    TestCase(
        "我们需要制定计划，确定里程碑和截止日期。需求规格要尽快完成。优先级需要重新排列。",
        "planning",
        ["zh"],
    ),
    # Chinese decisions
    TestCase(
        "我们决定使用新的方案。选择了这个策略是因为权衡了各种因素。替换旧的方法。",
        "decisions",
        ["zh"],
    ),
    # Chinese problems
    TestCase(
        "系统出现了严重的故障，崩溃了好几次。这个问题需要尽快修复和解决。", "problems", ["zh"]
    ),
    # Traditional Chinese
    TestCase(
        "我們需要修改代碼來修復這個錯誤。調試了很久終於找到問題。",
        "technical",
        ["zh", "traditional"],
    ),
    TestCase(
        "我們決定使用新的方案。選擇了這個策略是因為權衡了各種因素。",
        "decisions",
        ["zh", "traditional"],
    ),
    # English (baseline)
    TestCase(
        "The code has a bug in the database query function. Need to debug the API server.",
        "technical",
        ["en"],
    ),
    TestCase(
        "We decided to switch from MySQL to PostgreSQL. The trade-off was worth it.",
        "decisions",
        ["en"],
    ),
    # General (no topic keywords)
    TestCase("今天天气真好，阳光明媚，适合出去散步。", "general", ["zh", "general"]),
    TestCase("Just had a lovely walk in the park today.", "general", ["en", "general"]),
    # Mixed
    TestCase("debug 这个 API endpoint，database connection 有 bug", "technical", ["mixed"]),
    # === French (embedding-based, zero keyword config) ===
    TestCase(
        "Le code a un bug dans la base de données. Il faut déboguer le serveur API.",
        "technical",
        ["fr"],
    ),
    TestCase(
        "Nous avons décidé de migrer vers PostgreSQL. Le compromis en vaut la peine.",
        "decisions",
        ["fr"],
    ),
    TestCase(
        "Le système a planté. Une erreur critique a causé une panne du serveur.", "problems", ["fr"]
    ),
    TestCase("Nous devons planifier les étapes du projet et fixer les délais.", "planning", ["fr"]),
    TestCase(
        "L'architecture du système utilise des microservices avec des conteneurs Docker.",
        "architecture",
        ["fr"],
    ),
    TestCase(
        "Nous avons passé une belle journée au parc aujourd'hui.", "general", ["fr", "general"]
    ),
    # === Spanish (embedding-based) ===
    TestCase(
        "El código tiene un error en la consulta de base de datos. Necesitamos depurar el servidor API.",
        "technical",
        ["es"],
    ),
    TestCase(
        "Decidimos cambiar de MySQL a PostgreSQL por mejor soporte JSON. Fue una decisión difícil después de evaluar las alternativas.",
        "decisions",
        ["es"],
    ),
    TestCase(
        "El sistema falló con un error crítico. El servidor se cayó varias veces.",
        "problems",
        ["es"],
    ),
    TestCase(
        "Debemos planificar las fases del proyecto y establecer los plazos.", "planning", ["es"]
    ),
    TestCase(
        "La arquitectura del sistema utiliza microservicios con contenedores Docker.",
        "architecture",
        ["es"],
    ),
    # === German (embedding-based) ===
    TestCase(
        "Der Code hat einen Fehler in der Datenbankabfrage. Wir müssen den API-Server debuggen.",
        "technical",
        ["de"],
    ),
    TestCase(
        "Wir haben uns entschieden, von MySQL auf PostgreSQL umzusteigen.", "decisions", ["de"]
    ),
    TestCase(
        "Das System ist mit einem kritischen Fehler abgestürzt. Der Server fiel mehrmals aus.",
        "problems",
        ["de"],
    ),
    TestCase("Wir müssen die Projektphasen planen und die Termine festlegen.", "planning", ["de"]),
    # === Japanese (embedding-based) ===
    TestCase(
        "データベースクエリにバグがあります。APIサーバーをデバッグする必要があります。",
        "technical",
        ["ja"],
    ),
    TestCase(
        "MySQLからPostgreSQLに移行することにしました。トレードオフは価値がありました。",
        "decisions",
        ["ja"],
    ),
    TestCase(
        "システムが重大なエラーでクラッシュしました。サーバーが数回ダウンしました。",
        "problems",
        ["ja"],
    ),
]


def _run_room_classification(text: str) -> str:
    from mempalace.convo_miner import detect_convo_room

    return detect_convo_room(text)


# ─────────────────────────────────────────────────────────────────────────────
# DIMENSION 4: MEMORY EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

MEMORY_EXTRACTION_CASES = [
    # Chinese decisions
    TestCase(
        "经过讨论，我们决定使用 GraphQL 而不是 REST API。这个方案更适合我们的需求，因为更灵活。",
        "decision",
        ["zh"],
    ),
    TestCase(
        "我們決定使用微服務架構，選擇了這個策略因為權衡了擴展性。",
        "decision",
        ["zh", "traditional"],
    ),
    # Chinese preferences
    TestCase(
        "我偏好函数式编程风格，总是用不可变数据结构。千万不要用全局变量，这是我的习惯。",
        "preference",
        ["zh"],
    ),
    # Chinese milestones
    TestCase(
        "终于成功了！经过三天的努力，我们实现了完整的搜索功能。这是一个重大突破，第一次做到这样。",
        "milestone",
        ["zh"],
    ),
    # Chinese problems
    TestCase(
        "系统出现了严重的错误，数据库崩溃导致服务失败。根本原因是内存泄漏，需要修复。",
        "problem",
        ["zh"],
    ),
    # Chinese emotions
    TestCase(
        "我真的很开心，这个项目让我感到骄傲。我觉得团队做得非常好，我很感恩大家的付出。",
        "emotional|milestone",
        ["zh"],
    ),
    # English baseline
    TestCase(
        "We decided to use PostgreSQL because it has better JSON support. The trade-off was worth it.",
        "decision",
        ["en"],
    ),
    TestCase(
        "I prefer functional style. Always use immutable data. Never mock the database.",
        "preference",
        ["en"],
    ),
    TestCase(
        "Finally got it working! Breakthrough after three days. First time we achieved this.",
        "milestone",
        ["en"],
    ),
    TestCase(
        "The bug crashed the server. Root cause was memory leak. The fix was to patch the allocator.",
        "problem|milestone",
        ["en"],
    ),
    TestCase(
        "I love this project. So proud of what we built. Grateful for the team.",
        "emotional|milestone",
        ["en"],
    ),
]


def _run_memory_extraction(text: str) -> str:
    from mempalace.general_extractor import extract_memories

    memories = extract_memories(text, min_confidence=0.1)
    if not memories:
        return "NONE"
    # Return the primary memory type
    return memories[0]["memory_type"]


# ─────────────────────────────────────────────────────────────────────────────
# DIMENSION 5: SEARCH QUALITY
# ─────────────────────────────────────────────────────────────────────────────

SEARCH_CORPUS = [
    (
        "doc_zh_tech_1",
        "认证模块使用JWT令牌进行会话管理。令牌在24小时后过期。刷新令牌存储在HttpOnly的cookie中。",
    ),
    ("doc_zh_tech_2", "数据库迁移由Alembic处理。我们使用PostgreSQL 15作为主要数据库。"),
    (
        "doc_zh_arch_1",
        "系统架构采用微服务设计，每个服务独立部署在Docker容器中。网关层使用Nginx做负载均衡，服务间通过gRPC通信。",
    ),
    ("doc_zh_plan_1", "项目计划分三个阶段：第一阶段完成核心功能，第二阶段优化性能，第三阶段上线。"),
    ("doc_zht_tech_1", "認證模組使用JWT令牌進行會話管理。令牌在24小時後過期。"),
    ("doc_en_tech_1", "The authentication module uses JWT tokens for session management."),
    ("doc_en_tech_2", "Database migrations are handled by Alembic with PostgreSQL 15."),
    ("doc_en_arch_1", "The system uses a microservices architecture with Docker containers."),
    (
        "doc_fr_tech_1",
        "Le module d'authentification utilise des jetons JWT pour la gestion des sessions.",
    ),
    (
        "doc_fr_arch_1",
        "Le système utilise une architecture de microservices avec des conteneurs Docker.",
    ),
    ("doc_es_tech_1", "El módulo de autenticación utiliza tokens JWT para la gestión de sesiones."),
    (
        "doc_de_tech_1",
        "Das Authentifizierungsmodul verwendet JWT-Token für die Sitzungsverwaltung.",
    ),
    ("doc_ja_tech_1", "認証モジュールはJWTトークンを使用してセッション管理を行います。"),
]

SEARCH_QUERIES: List[Tuple[str, str, List[str]]] = [
    # (query, expected_top_doc_ids (any match = pass), tags)
    # Simplified Chinese — unique content queries
    ("数据库迁移工具Alembic", "doc_zh_tech_2", ["zh-Hans"]),
    ("微服务架构Nginx网关gRPC通信", "doc_zh_arch_1", ["zh-Hans"]),
    ("项目计划三个阶段核心功能", "doc_zh_plan_1", ["zh-Hans"]),
    # Traditional Chinese
    ("認證模組JWT令牌24小時過期", "doc_zht_tech_1", ["zh-Hant"]),
    # English
    ("JWT authentication session management", "doc_en_tech_1", ["en"]),
    ("database migration Alembic PostgreSQL", "doc_en_tech_2", ["en"]),
    # French
    ("authentification JWT gestion sessions jetons", "doc_fr_tech_1", ["fr"]),
    ("architecture microservices conteneurs Docker", "doc_fr_arch_1", ["fr"]),
    # Spanish
    ("autenticación JWT gestión sesiones tokens", "doc_es_tech_1", ["es"]),
    # German
    ("Authentifizierung JWT Sitzungsverwaltung Token", "doc_de_tech_1", ["de"]),
    # Japanese
    ("認証モジュールJWTトークンセッション管理", "doc_ja_tech_1", ["ja"]),
    # Cross-language: more specific queries to anchor to the right doc
    ("刷新令牌HttpOnly cookie", "doc_zh_tech_1", ["zh-Hans", "cross"]),
    ("authentication module JWT tokens session", "doc_en_tech_1", ["en", "cross"]),
    ("microservices architecture Docker containers", "doc_en_arch_1", ["en", "cross"]),
]


def _run_search_benchmark() -> DimensionScore:
    """Special dimension — requires seeding a ChromaDB collection."""
    import tempfile
    import os

    try:
        import chromadb
        from mempalace.config import get_embedding_function
    except ImportError:
        return DimensionScore(
            name="Search Quality",
            score=0,
            passed=0,
            total=len(SEARCH_QUERIES),
            failures=[],
            duration_ms=0,
        )

    t0 = time.time()
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        palace_path = os.path.join(tmpdir, "palace")
        os.makedirs(palace_path)
        client = chromadb.PersistentClient(path=palace_path)
        ef = get_embedding_function()
        col = client.create_collection("bench_search", embedding_function=ef)

        # Seed corpus
        col.add(
            ids=[doc_id for doc_id, _ in SEARCH_CORPUS],
            documents=[doc_text for _, doc_text in SEARCH_CORPUS],
        )

        # Run queries
        for query, expected_id, tags in SEARCH_QUERIES:
            try:
                res = col.query(query_texts=[query], n_results=3)
                top_ids = res["ids"][0] if res["ids"] else []
                top_id = top_ids[0] if top_ids else "NONE"
                passed = top_id == expected_id
                detail = "" if passed else f"expected={expected_id}, got={top_id} (top3={top_ids})"
                results.append(
                    TestResult(
                        case=TestCase(query, expected_id, tags),
                        actual=top_id,
                        passed=passed,
                        detail=detail,
                    )
                )
            except Exception as e:
                results.append(
                    TestResult(
                        case=TestCase(query, expected_id, tags),
                        actual=f"ERROR: {e}",
                        passed=False,
                        detail=str(e),
                    )
                )

    duration = (time.time() - t0) * 1000
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    score = (passed / total * 100) if total > 0 else 0
    failures = [r for r in results if not r.passed]
    return DimensionScore(
        name="Search Quality",
        score=score,
        passed=passed,
        total=total,
        failures=failures,
        duration_ms=duration,
    )


# ─────────────────────────────────────────────────────────────────────────────
# DIMENSION 6: OPENCC CONSISTENCY
# ─────────────────────────────────────────────────────────────────────────────

# Test that simplified and traditional Chinese produce the same classification
OPENCC_CONSISTENCY_PAIRS = [
    # (simplified, traditional, description)
    (
        "我们需要修改代码来修复这个错误。调试了很久终于找到问题。",
        "我們需要修改代碼來修復這個錯誤。調試了很久終於找到問題。",
        "technical room",
    ),
    (
        "我们决定使用新的方案。选择了这个策略是因为权衡了各种因素。",
        "我們決定使用新的方案。選擇了這個策略是因為權衡了各種因素。",
        "decisions room",
    ),
    (
        "系统出现了严重的故障，崩溃了好几次。这个问题需要尽快修复。",
        "系統出現了嚴重的故障，崩潰了好幾次。這個問題需要盡快修復。",
        "problems room",
    ),
    (
        "我们需要制定计划，确定里程碑和截止日期。",
        "我們需要制定計畫，確定里程碑和截止日期。",
        "planning room",
    ),
    ("经过讨论，我们决定使用微服务架构。", "經過討論，我們決定使用微服務架構。", "decision memory"),
    ("终于成功了！这是一个重大突破。", "終於成功了！這是一個重大突破。", "milestone memory"),
]


def _run_opencc_benchmark() -> DimensionScore:
    """Test that simplified↔traditional Chinese produce consistent results."""
    t0 = time.time()
    results = []

    try:
        from opencc import OpenCC

        s2t = OpenCC("s2t")
    except ImportError:
        return DimensionScore(
            name="OpenCC Consistency",
            score=0,
            passed=0,
            total=len(OPENCC_CONSISTENCY_PAIRS) * 3,
            failures=[],
            duration_ms=0,
        )

    from mempalace.convo_miner import detect_convo_room
    from mempalace.general_extractor import extract_memories

    for simplified, traditional, desc in OPENCC_CONSISTENCY_PAIRS:
        # Test 1: Room classification consistency
        room_s = detect_convo_room(simplified)
        room_t = detect_convo_room(traditional)
        passed = room_s == room_t
        results.append(
            TestResult(
                case=TestCase(f"room: {desc}", f"s={room_s},t={room_t}", ["opencc", "room"]),
                actual=f"s={room_s},t={room_t}",
                passed=passed,
                detail="" if passed else f"simplified→{room_s}, traditional→{room_t}",
            )
        )

        # Test 2: OpenCC s2t conversion matches actual traditional
        converted = s2t.convert(simplified)
        room_converted = detect_convo_room(converted)
        passed = room_converted == room_s
        results.append(
            TestResult(
                case=TestCase(f"s2t convert: {desc}", room_s, ["opencc", "convert"]),
                actual=room_converted,
                passed=passed,
                detail="" if passed else f"original_s→{room_s}, s2t_converted→{room_converted}",
            )
        )

        # Test 3: Memory type consistency
        mem_s = extract_memories(simplified, min_confidence=0.1)
        mem_t = extract_memories(traditional, min_confidence=0.1)
        type_s = mem_s[0]["memory_type"] if mem_s else "NONE"
        type_t = mem_t[0]["memory_type"] if mem_t else "NONE"
        passed = type_s == type_t
        results.append(
            TestResult(
                case=TestCase(f"memory: {desc}", f"s={type_s},t={type_t}", ["opencc", "memory"]),
                actual=f"s={type_s},t={type_t}",
                passed=passed,
                detail="" if passed else f"simplified→{type_s}, traditional→{type_t}",
            )
        )

    duration = (time.time() - t0) * 1000
    passed_count = sum(1 for r in results if r.passed)
    total = len(results)
    score = (passed_count / total * 100) if total > 0 else 0
    failures = [r for r in results if not r.passed]
    return DimensionScore(
        name="OpenCC Consistency",
        score=score,
        passed=passed_count,
        total=total,
        failures=failures,
        duration_ms=duration,
    )


# ─────────────────────────────────────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────────────────────────────────────


def _print_report(dimensions: List[DimensionScore], verbose: bool = False):
    """Print benchmark results as a formatted report."""
    total_passed = sum(d.passed for d in dimensions)
    total_tests = sum(d.total for d in dimensions)
    overall_score = sum(d.score for d in dimensions) / len(dimensions) if dimensions else 0

    print("\n" + "=" * 65)
    print("  MemPalace Multilingual Benchmark Report")
    print("=" * 65)

    # Dimension scores
    print(f"\n{'Dimension':<25} {'Score':>7} {'Pass':>6} {'Total':>6} {'Time':>8}")
    print("-" * 60)
    for d in dimensions:
        bar = "█" * int(d.score / 5) + "░" * (20 - int(d.score / 5))
        print(f"  {d.name:<23} {d.score:>5.1f}% {d.passed:>5}/{d.total:<5} {d.duration_ms:>6.0f}ms")
        print(f"  {bar}")

    print("-" * 60)
    print(f"  {'OVERALL':<23} {overall_score:>5.1f}% {total_passed:>5}/{total_tests:<5}")
    print()

    # Grade
    if overall_score >= 90:
        grade = "A"
    elif overall_score >= 80:
        grade = "B"
    elif overall_score >= 70:
        grade = "C"
    elif overall_score >= 60:
        grade = "D"
    else:
        grade = "F"
    print(f"  Grade: {grade}")
    print()

    # Tag breakdown
    tag_stats = {}
    for d in dimensions:
        for f in d.failures:
            for tag in f.case.tags:
                tag_stats.setdefault(tag, {"fail": 0, "total": 0})
                tag_stats[tag]["fail"] += 1
        # Count all tags
        # We only have failures, so count totals from dimension
    if tag_stats:
        print("  Failure breakdown by tag:")
        for tag, stats in sorted(tag_stats.items(), key=lambda x: -x[1]["fail"]):
            print(f"    [{tag}] {stats['fail']} failures")
        print()

    # Failures detail
    if verbose:
        for d in dimensions:
            if d.failures:
                print(f"  ── {d.name} failures ──")
                for f in d.failures:
                    tags_str = ", ".join(f.case.tags)
                    print(f"    ✗ [{tags_str}] {f.detail}")
                    print(f"      Input: {f.case.input[:80]}...")
                print()

    # JSON output
    report = {
        "overall_score": round(overall_score, 1),
        "grade": grade,
        "dimensions": [
            {
                "name": d.name,
                "score": round(d.score, 1),
                "passed": d.passed,
                "total": d.total,
                "duration_ms": round(d.duration_ms, 1),
                "failures": [
                    {
                        "input": f.case.input[:100],
                        "expected": f.case.expected,
                        "actual": f.actual,
                        "tags": f.case.tags,
                    }
                    for f in d.failures
                ],
            }
            for d in dimensions
        ],
    }
    report_path = "benchmarks/multilingual_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"  Report saved to: {report_path}")
    print("=" * 65)

    return report


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────


def run_benchmark(verbose: bool = False, dimensions_filter: str = None):
    """Run the full multilingual benchmark."""
    all_dims = []

    dims_to_run = {
        "language_detection": (
            "Language Detection",
            LANGUAGE_DETECTION_CASES,
            _run_language_detection,
        ),
        "entity_detection": ("Entity Detection", ENTITY_DETECTION_CASES, _run_entity_detection),
        "room_classification": (
            "Room Classification",
            ROOM_CLASSIFICATION_CASES,
            _run_room_classification,
        ),
        "memory_extraction": ("Memory Extraction", MEMORY_EXTRACTION_CASES, _run_memory_extraction),
        "search_quality": None,  # Special handling
        "opencc_consistency": None,  # Special handling
    }

    if dimensions_filter:
        dims_to_run = {k: v for k, v in dims_to_run.items() if k == dimensions_filter}

    for key, spec in dims_to_run.items():
        if key == "search_quality":
            print("  Running: Search Quality...")
            all_dims.append(_run_search_benchmark())
        elif key == "opencc_consistency":
            print("  Running: OpenCC Consistency...")
            all_dims.append(_run_opencc_benchmark())
        else:
            name, cases, fn = spec
            print(f"  Running: {name}...")
            all_dims.append(_score_dimension(name, cases, fn))

    return _print_report(all_dims, verbose=verbose)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MemPalace Multilingual Benchmark")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show failure details")
    parser.add_argument("--dim", type=str, default=None, help="Run single dimension")
    args = parser.parse_args()

    report = run_benchmark(verbose=args.verbose, dimensions_filter=args.dim)
    sys.exit(0 if report["overall_score"] >= 70 else 1)

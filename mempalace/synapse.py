import json
import logging
import math
import os
import sqlite3
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_LTP_WINDOW_DAYS = 30
DEFAULT_LTP_MAX_BOOST = 2.0
DEFAULT_LTP_COEFFICIENT = 0.3
DEFAULT_TAGGING_WINDOW_HOURS = 24
DEFAULT_TAGGING_MAX_BOOST = 1.5
DEFAULT_ASSOCIATION_MAX_BOOST = 1.5
DEFAULT_ASSOCIATION_COEFFICIENT = 0.15
SYNAPSE_DB_NAME = "synapse.sqlite3"

# Chroma drawer metadata — Phase 3 synaptic marking for newly filed drawers
SYNAPSE_MARK_METADATA_KEY = "synapse_mark"
SYNAPSE_MARK_NEW = "new"

SOFT_ARCHIVE_ISSUE_REF = "#336"


def _canonical_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def build_soft_archive_proposal(
    wing: str,
    room: str,
    *,
    target_wing: str = "archive",
    inactive_days: int = 180,
) -> dict[str, Any]:
    """
    Soft-archive nudge for consolidation candidates (#336).
    Does not move data — surfaces suggested wing/room for a future soft-archive wing.
    """
    safe_w = (wing or "unknown").replace(" ", "_")
    safe_r = (room or "unknown").replace(" ", "_")
    return {
        "reason": "inactive_beyond_consolidation_window",
        "inactive_days_threshold": inactive_days,
        "suggested_wing": target_wing,
        "suggested_room": f"{safe_w}__{safe_r}"[:220],
        "related_issue": SOFT_ARCHIVE_ISSUE_REF,
        "disclaimer": "Suggestion only — no automatic move; user or agent relocates the drawer.",
    }


class SynapseDB:
    """Manages the synapse.sqlite3 database for retrieval logging and scoring."""

    def __init__(self, palace_path: str):
        """
        palace_path: palace のルートディレクトリ（knowledge_graph.sqlite3 と同階層）
        synapse.sqlite3 が存在しなければ作成し、テーブルを初期化する。
        WAL モードを有効にする。
        """
        self.db_path = os.path.join(palace_path, SYNAPSE_DB_NAME)
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS retrieval_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    drawer_id TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    query_hash TEXT NOT NULL,
                    session_id TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_retrieval_log_drawer
                    ON retrieval_log(drawer_id);

                CREATE INDEX IF NOT EXISTS idx_retrieval_log_session
                    ON retrieval_log(session_id);

                CREATE INDEX IF NOT EXISTS idx_retrieval_log_retrieved_at
                    ON retrieval_log(retrieved_at);

                CREATE TABLE IF NOT EXISTS co_retrieval (
                    drawer_a TEXT NOT NULL,
                    drawer_b TEXT NOT NULL,
                    co_count INTEGER NOT NULL DEFAULT 0,
                    last_co_retrieved TEXT NOT NULL,
                    PRIMARY KEY (drawer_a, drawer_b)
                );

                CREATE INDEX IF NOT EXISTS idx_co_retrieval_drawer_a
                    ON co_retrieval(drawer_a);
                CREATE INDEX IF NOT EXISTS idx_co_retrieval_drawer_b
                    ON co_retrieval(drawer_b);

                CREATE TABLE IF NOT EXISTS synapse_stats (
                    drawer_id TEXT PRIMARY KEY,
                    total_retrievals INTEGER NOT NULL DEFAULT 0,
                    recent_density REAL NOT NULL DEFAULT 0.0,
                    ltp_score REAL NOT NULL DEFAULT 1.0,
                    last_updated TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS query_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_text TEXT NOT NULL,
                    query_embedding TEXT NOT NULL,
                    result_ids TEXT NOT NULL,
                    result_scores TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_query_log_timestamp
                    ON query_log(timestamp);
                """
            )
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def connection(self):
        """Single search/request: reuse one SQLite connection (WAL, busy timeout)."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def log_retrieval(
        self,
        drawer_ids: list[str],
        query_hash: str,
        session_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ):
        """
        検索結果に含まれた drawer_id のリストを retrieval_log に記録する。
        - retrieved_at: UTC ISO 8601 形式
        - fire-and-forget: 例外が発生してもログ出力のみで呼び出し元に伝播しない
        """
        if not drawer_ids:
            return
        try:
            retrieved_at = _utc_now_iso()
            rows = [(did, retrieved_at, query_hash, session_id) for did in drawer_ids]
            if conn is not None:
                conn.executemany(
                    "INSERT INTO retrieval_log (drawer_id, retrieved_at, query_hash, session_id) "
                    "VALUES (?, ?, ?, ?)",
                    rows,
                )
            else:
                with self.connection() as c:
                    c.executemany(
                        "INSERT INTO retrieval_log (drawer_id, retrieved_at, query_hash, session_id) "
                        "VALUES (?, ?, ?, ?)",
                        rows,
                    )
        except Exception as e:
            logger.warning("log_retrieval failed: %s", e)
        else:
            try:
                self._record_co_retrieval_pairs(drawer_ids, retrieved_at, conn=conn)
            except Exception as e:
                logger.warning("co_retrieval pair update failed: %s", e)

    def _record_co_retrieval_pairs(
        self,
        drawer_ids: list[str],
        retrieved_at: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        """同一検索結果内の drawer ペアごとに co_count を増分する。"""
        uniq = sorted(set(drawer_ids))
        if len(uniq) < 2:
            return

        def _run(c: sqlite3.Connection) -> None:
            for i in range(len(uniq)):
                for j in range(i + 1, len(uniq)):
                    a, b = _canonical_pair(uniq[i], uniq[j])
                    c.execute(
                        """
                        INSERT INTO co_retrieval (drawer_a, drawer_b, co_count, last_co_retrieved)
                        VALUES (?, ?, 1, ?)
                        ON CONFLICT(drawer_a, drawer_b) DO UPDATE SET
                            co_count = co_count + 1,
                            last_co_retrieved = excluded.last_co_retrieved
                        """,
                        (a, b, retrieved_at),
                    )

        if conn is not None:
            _run(conn)
        else:
            with self.connection() as c:
                _run(c)

    def rebuild_co_retrieval_from_log(self) -> int:
        """
        retrieval_log を集計して co_retrieval を一括再構築する。
        ログ削除後や整合性修復用。挿入した行数を返す。
        """
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("DELETE FROM co_retrieval")
            conn.execute(
                """
                INSERT INTO co_retrieval (drawer_a, drawer_b, co_count, last_co_retrieved)
                SELECT
                    d1.drawer_id AS drawer_a,
                    d2.drawer_id AS drawer_b,
                    COUNT(DISTINCT d1.session_id) AS co_count,
                    MAX(d1.retrieved_at) AS last_co_retrieved
                FROM retrieval_log d1
                INNER JOIN retrieval_log d2
                    ON d1.session_id = d2.session_id
                    AND d1.drawer_id < d2.drawer_id
                GROUP BY d1.drawer_id, d2.drawer_id
                """
            )
            conn.commit()
            cur = conn.execute("SELECT COUNT(*) FROM co_retrieval")
            n = int(cur.fetchone()[0])
            return n
        finally:
            conn.close()

    def get_association_scores_batch(
        self,
        drawer_ids: list[str],
        max_boost: float = DEFAULT_ASSOCIATION_MAX_BOOST,
        coefficient: float = DEFAULT_ASSOCIATION_COEFFICIENT,
        conn: Optional[sqlite3.Connection] = None,
    ) -> dict[str, float]:
        """
        同一検索結果の drawer 集合について、co_retrieval の共起強度から association を計算する。
        各 drawer について、ヒット集合内の他 drawer との co_count 合計を用いる。
        """
        uniq = list(dict.fromkeys([d for d in drawer_ids if d]))
        out: dict[str, float] = {d: 1.0 for d in uniq}
        if len(uniq) < 2:
            return out
        own = False
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            own = True
        try:
            ph = ",".join("?" * len(uniq))
            cur = conn.execute(
                f"SELECT drawer_a, drawer_b, co_count FROM co_retrieval "
                f"WHERE drawer_a IN ({ph}) AND drawer_b IN ({ph})",
                (*uniq, *uniq),
            )
            edge: dict[tuple[str, str], int] = {}
            for a, b, c in cur.fetchall():
                edge[(a, b)] = int(c)
        finally:
            if own:
                conn.close()
        for d in uniq:
            total = 0
            for o in uniq:
                if o == d:
                    continue
                ca, cb = _canonical_pair(d, o)
                total += edge.get((ca, cb), 0)
            if total == 0:
                out[d] = 1.0
            else:
                raw = 1.0 + math.log(1 + total) * coefficient
                out[d] = _clamp(raw, 1.0, max_boost)
        return out

    def get_top_co_pairs(self, limit: int = 20) -> list[dict[str, Any]]:
        """共起回数の多いペアを返す。"""
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "SELECT drawer_a, drawer_b, co_count, last_co_retrieved FROM co_retrieval "
                "ORDER BY co_count DESC, last_co_retrieved DESC LIMIT ?",
                (limit,),
            )
            return [
                {
                    "drawer_a": r[0],
                    "drawer_b": r[1],
                    "co_count": int(r[2]),
                    "last_co_retrieved": r[3],
                }
                for r in cur.fetchall()
            ]
        finally:
            conn.close()

    def get_co_occurrence_clusters(
        self, max_edges: int = 40, max_clusters: int = 12
    ) -> list[dict[str, Any]]:
        """
        強い共起ペアから無向グラフを張り、連結成分をクラスタとして返す。
        """
        top = self.get_top_co_pairs(max_edges)
        if not top:
            return []

        parent: dict[str, str] = {}

        def find(x: str) -> str:
            if x not in parent:
                parent[x] = x
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x: str, y: str) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        for p in top:
            union(p["drawer_a"], p["drawer_b"])

        root_nodes: dict[str, set[str]] = {}
        for p in top:
            for n in (p["drawer_a"], p["drawer_b"]):
                r = find(n)
                root_nodes.setdefault(r, set()).add(n)

        clusters: list[dict[str, Any]] = []
        for r, drawers in root_nodes.items():
            if len(drawers) < 2:
                continue
            tw = sum(int(p["co_count"]) for p in top if find(p["drawer_a"]) == r)
            clusters.append(
                {
                    "drawers": sorted(drawers),
                    "total_co_weight": tw,
                    "size": len(drawers),
                }
            )

        clusters.sort(key=lambda c: (-c["total_co_weight"], -c["size"]))
        return clusters[:max_clusters]

    def get_ltp_score(
        self,
        drawer_id: str,
        window_days: int = DEFAULT_LTP_WINDOW_DAYS,
        max_boost: float = DEFAULT_LTP_MAX_BOOST,
    ) -> float:
        """
        直近 window_days 日間の retrieval_log から drawer_id の検索回数を集計し、
        LTP スコアを計算して返す。
        ltp = clamp(1.0 + log(1 + recent_count) * LTP_COEFFICIENT, 1.0, max_boost)
        retrieval_log にエントリがなければ 1.0 を返す。
        """
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=window_days)
        cutoff = cutoff_dt.isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "SELECT COUNT(*) FROM retrieval_log WHERE drawer_id = ? AND retrieved_at >= ?",
                (drawer_id, cutoff),
            )
            row = cur.fetchone()
            recent_count = int(row[0]) if row else 0
        finally:
            conn.close()

        if recent_count == 0:
            return 1.0
        raw = 1.0 + math.log(1 + recent_count) * DEFAULT_LTP_COEFFICIENT
        return _clamp(raw, 1.0, max_boost)

    def get_ltp_scores_batch(
        self,
        drawer_ids: list[str],
        window_days: int = DEFAULT_LTP_WINDOW_DAYS,
        max_boost: float = DEFAULT_LTP_MAX_BOOST,
        conn: Optional[sqlite3.Connection] = None,
    ) -> dict[str, float]:
        """
        複数の drawer_id に対する LTP スコアを一括取得する。
        N+1 クエリを避けるため、IN 句で一括集計する。
        戻り値: {drawer_id: ltp_score}。ログにない drawer_id は 1.0。
        """
        out: dict[str, float] = {did: 1.0 for did in drawer_ids}
        if not drawer_ids:
            return out
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=window_days)
        cutoff = cutoff_dt.isoformat()
        placeholders = ",".join("?" * len(drawer_ids))
        sql = (
            f"SELECT drawer_id, COUNT(*) as cnt FROM retrieval_log "
            f"WHERE drawer_id IN ({placeholders}) AND retrieved_at >= ? GROUP BY drawer_id"
        )
        own = False
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            own = True
        try:
            cur = conn.execute(sql, (*drawer_ids, cutoff))
            for drawer_id, cnt in cur.fetchall():
                recent_count = int(cnt)
                if recent_count == 0:
                    out[drawer_id] = 1.0
                else:
                    raw = 1.0 + math.log(1 + recent_count) * DEFAULT_LTP_COEFFICIENT
                    out[drawer_id] = _clamp(raw, 1.0, max_boost)
        finally:
            if own:
                conn.close()
        return out

    @staticmethod
    def calculate_tagging_boost(
        filed_at: Optional[str],
        window_hours: int = DEFAULT_TAGGING_WINDOW_HOURS,
        max_boost: float = DEFAULT_TAGGING_MAX_BOOST,
    ) -> float:
        """
        filed_at（ISO 8601 文字列）から現在までの経過時間を計算し、
        tagging boost を返す。
        - 窓内: 1.0 + (max_boost - 1.0) * (1.0 - hours / window_hours)
        - 窓外: 1.0
        - filed_at が None またはパース失敗: 1.0
        """
        if filed_at is None:
            return 1.0
        try:
            s = filed_at.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            filed = datetime.fromisoformat(s)
            if filed.tzinfo is None:
                filed = filed.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            delta = now - filed.astimezone(timezone.utc)
            hours = delta.total_seconds() / 3600.0
        except (ValueError, TypeError, OSError):
            return 1.0

        if hours >= float(window_hours):
            return 1.0
        if hours < 0:
            hours = 0.0
        amplitude = max_boost - 1.0
        boost = 1.0 + amplitude * (1.0 - hours / float(window_hours))
        return _clamp(boost, 1.0, max_boost)

    def calculate_synapse_score(
        self,
        similarity: float,
        decay: float,
        drawer_id: str,
        filed_at: Optional[str],
        ltp_scores: Optional[dict[str, float]] = None,
        window_days: int = DEFAULT_LTP_WINDOW_DAYS,
        ltp_max_boost: float = DEFAULT_LTP_MAX_BOOST,
        tagging_window_hours: int = DEFAULT_TAGGING_WINDOW_HOURS,
        tagging_max_boost: float = DEFAULT_TAGGING_MAX_BOOST,
        association_scores: Optional[dict[str, float]] = None,
    ) -> dict[str, Any]:
        """
        最終スコアを計算して返す。
        final_score = similarity * decay * ltp * association * tagging

        戻り値:
        {
            "final_score": float,
            "similarity": float,
            "decay": float,
            "ltp": float,
            "association": float,
            "tagging": float
        }
        """
        if ltp_scores is not None:
            ltp = ltp_scores.get(drawer_id, 1.0)
        else:
            ltp = self.get_ltp_score(drawer_id, window_days, max_boost=ltp_max_boost)
        tagging = self.calculate_tagging_boost(
            filed_at,
            window_hours=tagging_window_hours,
            max_boost=tagging_max_boost,
        )
        if association_scores is not None:
            association = association_scores.get(drawer_id, 1.0)
        else:
            association = 1.0
        final_score = similarity * decay * ltp * tagging * association
        return {
            "final_score": final_score,
            "similarity": similarity,
            "decay": decay,
            "ltp": ltp,
            "association": association,
            "tagging": tagging,
        }

    def cleanup_old_logs(self, retention_days: int = 90) -> int:
        """
        retention_days より古い retrieval_log エントリを削除する。
        削除件数を返す。
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        deleted = 0
        with self.connection() as conn:
            cur = conn.execute("DELETE FROM retrieval_log WHERE retrieved_at < ?", (cutoff,))
            rc = cur.rowcount
            if rc is not None and rc >= 0:
                deleted = int(rc)
        if deleted > 1000:
            self._vacuum_database()
        if deleted > 0:
            try:
                self.rebuild_co_retrieval_from_log()
            except Exception as e:
                logger.warning("rebuild_co_retrieval_from_log after cleanup failed: %s", e)
        return deleted

    def _vacuum_database(self) -> None:
        try:
            vacuum_conn = sqlite3.connect(self.db_path)
            try:
                vacuum_conn.execute("VACUUM")
                vacuum_conn.commit()
            finally:
                vacuum_conn.close()
        except Exception as e:
            logger.warning("VACUUM failed: %s", e)

    def get_log_stats(self) -> dict[str, Any]:
        """ログの統計情報を返す。"""
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT drawer_id), MIN(retrieved_at), MAX(retrieved_at) "
                "FROM retrieval_log"
            ).fetchone()
            total, unique, oldest, newest = row
        finally:
            conn.close()
        db_size_kb = 0.0
        try:
            db_size_kb = round(os.path.getsize(self.db_path) / 1024, 1)
        except OSError:
            pass
        return {
            "total_entries": int(total or 0),
            "unique_drawers": int(unique or 0),
            "oldest_entry": oldest,
            "newest_entry": newest,
            "db_size_kb": db_size_kb,
        }

    def refresh_stats(
        self,
        window_days: int = DEFAULT_LTP_WINDOW_DAYS,
        ltp_max_boost: float = DEFAULT_LTP_MAX_BOOST,
    ) -> None:
        """
        synapse_stats テーブルを retrieval_log から再計算して更新する。
        mempalace status や明示的なリフレッシュ時に呼ばれる。
        """
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=window_days)
        cutoff = cutoff_dt.isoformat()
        now_iso = _utc_now_iso()
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute("SELECT drawer_id, COUNT(*) FROM retrieval_log GROUP BY drawer_id")
            totals = {row[0]: int(row[1]) for row in cur.fetchall()}
            cur = conn.execute(
                "SELECT drawer_id, COUNT(*) FROM retrieval_log WHERE retrieved_at >= ? "
                "GROUP BY drawer_id",
                (cutoff,),
            )
            recent = {row[0]: int(row[1]) for row in cur.fetchall()}
            for drawer_id, total_retrievals in totals.items():
                rc = recent.get(drawer_id, 0)
                recent_density = rc / float(max(1, window_days))
                if rc == 0:
                    ltp_score = 1.0
                else:
                    raw = 1.0 + math.log(1 + rc) * DEFAULT_LTP_COEFFICIENT
                    ltp_score = _clamp(raw, 1.0, ltp_max_boost)
                conn.execute(
                    "INSERT OR REPLACE INTO synapse_stats "
                    "(drawer_id, total_retrievals, recent_density, ltp_score, last_updated) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (drawer_id, total_retrievals, recent_density, ltp_score, now_iso),
                )
            conn.commit()
        finally:
            conn.close()

    def get_consolidation_candidates(
        self, inactive_days: int = 180, wing: Optional[str] = None
    ) -> list[dict]:
        """
        inactive_days 以上検索されていない drawer_id のリストを返す。
        wing が指定されていれば drawer_id に部分一致する行に限定する。
        戻り値: [{"drawer_id": str, "last_retrieved_at": str, "days_inactive": int}]
        """
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=inactive_days)).isoformat()
        if wing:
            sql = (
                "SELECT drawer_id, MAX(retrieved_at) AS last_at FROM retrieval_log "
                "WHERE drawer_id LIKE ? "
                "GROUP BY drawer_id HAVING MAX(retrieved_at) < ?"
            )
            params = (f"%{wing}%", cutoff)
        else:
            sql = (
                "SELECT drawer_id, MAX(retrieved_at) AS last_at FROM retrieval_log "
                "GROUP BY drawer_id HAVING MAX(retrieved_at) < ?"
            )
            params = (cutoff,)
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(sql, params)
            rows = cur.fetchall()
        finally:
            conn.close()

        out: list[dict] = []
        for drawer_id, last_at in rows:
            try:
                s = last_at.strip()
                if s.endswith("Z"):
                    s = s[:-1] + "+00:00"
                last_dt = datetime.fromisoformat(s)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                last_dt = last_dt.astimezone(timezone.utc)
                days_inactive = max(0, (now - last_dt).days)
            except (ValueError, TypeError, AttributeError):
                days_inactive = inactive_days
            out.append(
                {
                    "drawer_id": drawer_id,
                    "last_retrieved_at": last_at,
                    "days_inactive": days_inactive,
                }
            )
        return out

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """2つのベクトルのコサイン類似度を返す。"""
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = sum(a * a for a in vec_a) ** 0.5
        norm_b = sum(b * b for b in vec_b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def apply_mmr(
        self,
        scored_results: list[dict[str, Any]],
        query_embedding: list[float],
        lambda_param: float = 0.7,
        final_k: int = 5,
    ) -> dict[str, Any]:
        """Synapse スコアリング済みの結果リストに MMR を適用する。"""
        candidates: list[dict[str, Any]] = [dict(h) for h in scored_results]
        before_n = len(candidates)

        if lambda_param >= 0.999:
            sel = sorted(
                candidates,
                key=lambda h: float(h.get("synapse_score", h.get("similarity", 0.0))),
                reverse=True,
            )[:final_k]
            after_n = len(sel)
            max_internal = 0.0
            if len(sel) >= 2:

                def _ge(h: dict[str, Any]) -> list[float]:
                    emb = h.get("embedding")
                    if isinstance(emb, list) and emb:
                        return [float(x) for x in emb]
                    return []

                embs = [_ge(s) for s in sel]
                for i in range(len(sel)):
                    for j in range(i + 1, len(sel)):
                        if embs[i] and embs[j]:
                            max_internal = max(
                                max_internal,
                                self._cosine_similarity(embs[i], embs[j]),
                            )
            return {
                "results": sel,
                "mmr_metadata": {
                    "applied": True,
                    "lambda": lambda_param,
                    "candidates_before_mmr": before_n,
                    "candidates_after_mmr": after_n,
                    "dropped_as_redundant": max(0, before_n - after_n),
                    "max_internal_similarity": max_internal,
                },
            }

        selected: list[dict[str, Any]] = []

        def _get_emb(h: dict[str, Any]) -> list[float]:
            emb = h.get("embedding")
            if isinstance(emb, list) and emb:
                return [float(x) for x in emb]
            return []

        def _rel_score(h: dict[str, Any]) -> float:
            if "synapse_score" in h:
                return float(h["synapse_score"])
            if "distance" in h and h["distance"] is not None:
                return float(1.0 - float(h["distance"]))
            return float(h.get("similarity", 0.0))

        while candidates and len(selected) < final_k:
            best_i = -1
            best_mmr = float("-inf")
            for i, cand in enumerate(candidates):
                emb_c = _get_emb(cand)
                sim_q = (
                    self._cosine_similarity(emb_c, query_embedding) if emb_c else _rel_score(cand)
                )
                if not selected:
                    mmr_s = lambda_param * sim_q
                else:
                    max_sim_sel = max(
                        self._cosine_similarity(emb_c, _get_emb(s))
                        if emb_c and _get_emb(s)
                        else 0.0
                        for s in selected
                    )
                    mmr_s = lambda_param * sim_q - (1.0 - lambda_param) * max_sim_sel
                if mmr_s > best_mmr:
                    best_mmr = mmr_s
                    best_i = i
            if best_i < 0:
                break
            chosen = candidates.pop(best_i)
            selected.append(chosen)

        after_n = len(selected)
        dropped = max(0, before_n - after_n)

        max_internal = 0.0
        if len(selected) >= 2:
            embs = [_get_emb(s) for s in selected]
            for i in range(len(selected)):
                for j in range(i + 1, len(selected)):
                    if embs[i] and embs[j]:
                        max_internal = max(max_internal, self._cosine_similarity(embs[i], embs[j]))

        return {
            "results": selected,
            "mmr_metadata": {
                "applied": True,
                "lambda": lambda_param,
                "candidates_before_mmr": before_n,
                "candidates_after_mmr": after_n,
                "dropped_as_redundant": dropped,
                "max_internal_similarity": max_internal,
            },
        }

    def log_query(
        self,
        query_text: str,
        query_embedding: list[float],
        result_ids: list[str],
        result_scores: list[float],
    ) -> None:
        """検索クエリとその結果を query_log に記録する。"""
        try:
            with self.connection() as conn:
                conn.execute(
                    "INSERT INTO query_log (query_text, query_embedding, result_ids, "
                    "result_scores, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (
                        query_text,
                        json.dumps(query_embedding),
                        json.dumps(result_ids),
                        json.dumps(result_scores),
                        _utc_now_iso(),
                    ),
                )
        except Exception as e:
            logger.warning("log_query failed: %s", e)

    def expand_query(
        self,
        collection: Any,
        query_text: str,
        query_embedding: list[float],
        max_expansions: int = 3,
        similarity_threshold: float = 0.65,
        lookback_days: int = 60,
    ) -> dict[str, Any]:
        """過去の検索ログから類似クエリを見つけ、拡張キーワードを返す。"""
        qt_lower = query_text.lower()
        qt_words = set(qt_lower.replace(",", " ").split())

        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=int(lookback_days))
        cutoff = cutoff_dt.isoformat()

        conn = sqlite3.connect(self.db_path)
        rows: list[tuple[Any, ...]] = []
        try:
            cur = conn.execute(
                "SELECT query_text, query_embedding, result_ids, result_scores FROM query_log "
                "WHERE timestamp > ? ORDER BY timestamp DESC",
                (cutoff,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        similar_past: list[str] = []
        source_ids: set[str] = set()
        for qtxt, qemb_blob, rids_blob, rs_blob in rows:
            try:
                past_emb = json.loads(qemb_blob)
                if not isinstance(past_emb, list) or not past_emb:
                    continue
                past_emb_f = [float(x) for x in past_emb]
                sim = self._cosine_similarity([float(x) for x in query_embedding], past_emb_f)
                if sim >= similarity_threshold and str(qtxt) != query_text:
                    similar_past.append(str(qtxt))
                    rids = json.loads(rids_blob)
                    scores = json.loads(rs_blob)
                    if isinstance(rids, list) and isinstance(scores, list):
                        paired = list(zip(rids, scores))
                        paired.sort(key=lambda x: float(x[1]), reverse=True)
                        for did, _sc in paired[:5]:
                            if isinstance(did, str):
                                source_ids.add(did)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        expansion_terms: list[str] = []
        if source_ids and collection is not None:
            try:
                got = collection.get(ids=list(source_ids), include=["metadatas", "documents"])
                metas = got.get("metadatas") or []
                docs = got.get("documents") or []
                counter: Counter[str] = Counter()
                for mi, meta in enumerate(metas):
                    meta = meta or {}
                    title = meta.get("title") or ""
                    doc_snip = ""
                    if mi < len(docs) and docs[mi]:
                        doc_snip = str(docs[mi])[:240]
                    blob = f"{title} {doc_snip} {meta.get('room', '')} {meta.get('wing', '')}"
                    for w in blob.replace("/", " ").split():
                        w_clean = w.strip().lower()
                        if len(w_clean) < 2 or w_clean in qt_words:
                            continue
                        counter[w_clean] += 1
                expansion_terms = [t for t, _ in counter.most_common(max_expansions)]
            except Exception as e:
                logger.warning("expand_query metadata fetch failed: %s", e)

        similar_past = list(dict.fromkeys(similar_past))
        metadata = {
            "past_query_rows": len(rows),
            "similar_query_matches": len(similar_past),
            "unique_source_drawers": len(source_ids),
            "lookback_days": int(lookback_days),
        }
        return {
            "applied": bool(similar_past) or bool(expansion_terms),
            "original_query": query_text,
            "expansion_terms": expansion_terms[:max_expansions],
            "similar_past_queries": similar_past[:20],
            "source_drawer_count": len(source_ids),
            "metadata": metadata,
        }

    def _drawer_last_retrieved(self, drawer_id: str) -> str:
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT MAX(retrieved_at) FROM retrieval_log WHERE drawer_id = ?",
                (drawer_id,),
            ).fetchone()
            return str(row[0]) if row and row[0] else ""
        finally:
            conn.close()

    def _drawer_retrieval_count(self, drawer_id: str) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM retrieval_log WHERE drawer_id = ?", (drawer_id,)
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    def get_top_ltp_drawers(self, ltp_threshold: float, limit: int = 10) -> list[tuple[str, float]]:
        """synapse_stats から LTP が閾値以上の drawer を上位 limit 件返す。"""
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "SELECT drawer_id, ltp_score FROM synapse_stats WHERE ltp_score >= ? "
                "ORDER BY ltp_score DESC LIMIT ?",
                (ltp_threshold, limit),
            )
            return [(str(r[0]), float(r[1])) for r in cur.fetchall()]
        finally:
            conn.close()

    def get_retrieval_spread(self, drawer_id: str) -> int:
        """
        query_log 上で drawer_id が結果に含まれた異なる query_text の数（近似 spread）。
        0 件なら 1 を返す。
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute("SELECT query_text, result_ids FROM query_log")
            distinct: set[str] = set()
            for qtext, rids_blob in cur.fetchall():
                try:
                    rids = json.loads(rids_blob)
                    if isinstance(rids, list) and drawer_id in rids:
                        distinct.add(str(qtext))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
            n = len(distinct)
            return n if n > 0 else 1
        finally:
            conn.close()

    def get_recently_tagged_drawer_ids(
        self, collection: Any, tagged_window_hours: int
    ) -> list[str]:
        """synapse_mark=new かつ filed_at が窓内の drawer id を返す。"""
        if collection is None:
            return []
        now = datetime.now(timezone.utc)
        window = float(tagged_window_hours)
        out: list[str] = []
        try:
            got = collection.get(include=["metadatas"], limit=10000)
            for did, meta in zip(got.get("ids") or [], got.get("metadatas") or []):
                meta = meta or {}
                if meta.get(SYNAPSE_MARK_METADATA_KEY) != SYNAPSE_MARK_NEW:
                    continue
                fa = meta.get("filed_at")
                if not fa:
                    continue
                try:
                    s = str(fa).strip()
                    if s.endswith("Z"):
                        s = s[:-1] + "+00:00"
                    filed = datetime.fromisoformat(s)
                    if filed.tzinfo is None:
                        filed = filed.replace(tzinfo=timezone.utc)
                    hours = (now - filed.astimezone(timezone.utc)).total_seconds() / 3600.0
                except (ValueError, TypeError, OSError):
                    continue
                if 0 <= hours < window:
                    out.append(did)
        except Exception as e:
            logger.warning("get_recently_tagged_drawer_ids failed: %s", e)
        return out

    def get_pinned_memories(
        self,
        collection: Any,
        max_tokens: int = 2000,
        max_items: int = 5,
        ltp_threshold: float = 1.5,
        include_tagged: bool = True,
        tagged_window_hours: int = 48,
    ) -> dict[str, Any]:
        """LTP スコア上位 + 直近 tagged の drawer を返す。"""
        if collection is None:
            return {
                "pinned_memories": [],
                "pinned_count": 0,
                "pinned_total_tokens": 0,
                "pinned_source": "none (no collection)",
            }

        ltp_ranked = self.get_top_ltp_drawers(ltp_threshold, limit=10)
        tagged_ids: list[str] = []
        if include_tagged:
            tagged_ids = self.get_recently_tagged_drawer_ids(collection, tagged_window_hours)

        merged: dict[str, dict[str, Any]] = {}
        for rank, (did, ltp) in enumerate(ltp_ranked, start=1):
            merged[did] = {
                "ltp_score": ltp,
                "from_ltp": True,
                "ltp_rank": rank,
                "ltp_pool": len(ltp_ranked),
            }
        for did in tagged_ids:
            if did not in merged:
                merged[did] = {
                    "ltp_score": 1.0,
                    "from_ltp": False,
                    "ltp_rank": 0,
                    "ltp_pool": len(ltp_ranked),
                }
            merged[did]["from_tagged"] = True

        pool_n = len(merged)
        for did in merged:
            spread = self.get_retrieval_spread(did)
            capped = min(int(spread), 10)
            ltp = float(merged[did]["ltp_score"])
            pinning = ltp * (1.0 + 0.2 * float(capped))
            merged[did]["retrieval_spread"] = spread
            merged[did]["pinning_score"] = pinning

        ordered = sorted(
            merged.keys(),
            key=lambda d: float(merged[d]["pinning_score"]),
            reverse=True,
        )
        pinning_ranks = {did: i + 1 for i, did in enumerate(ordered)}

        pinned: list[dict[str, Any]] = []
        total_tokens = 0
        for did in ordered:
            if len(pinned) >= max_items:
                break
            try:
                got = collection.get(ids=[did], include=["documents", "metadatas"])
                if not got.get("ids"):
                    continue
                doc = (got.get("documents") or [""])[0] or ""
                meta = (got.get("metadatas") or [{}])[0] or {}
            except Exception:
                continue
            content = doc
            token_count = max(1, len(content) // 4)
            if total_tokens + token_count > max_tokens:
                break
            title = meta.get("title") or content[:50]
            info = merged[did]
            prank = pinning_ranks.get(did, 0)
            spread = int(info.get("retrieval_spread", 1))
            pscore = float(info.get("pinning_score", info["ltp_score"]))
            ltp_disp = float(info["ltp_score"])
            reasons: list[str] = []
            reasons.append(
                f"ltp_score={ltp_disp:.2f}, spread={spread}, pinning_score={pscore:.2f} "
                f"(rank {prank} of {pool_n})"
            )
            if info.get("from_tagged"):
                reasons.append(f"tagged within {tagged_window_hours}h")
            pinned_reason = "; ".join(reasons) if reasons else "pinned"
            entry = {
                "drawer_id": did,
                "title": str(title),
                "content_preview": content[:200],
                "ltp_score": float(info["ltp_score"]),
                "retrieval_spread": spread,
                "pinning_score": pscore,
                "retrieval_count": self._drawer_retrieval_count(did),
                "last_retrieved": self._drawer_last_retrieved(did),
                "pinned_reason": pinned_reason,
                "source_wing": str(meta.get("wing", "unknown")),
                "source_room": str(meta.get("room", "unknown")),
                "token_count": token_count,
            }
            pinned.append(entry)
            total_tokens += token_count

        src = f"synapse_ltp (threshold={ltp_threshold})"
        if include_tagged:
            src += f" + synapse_tagging (window={tagged_window_hours}h)"
        return {
            "pinned_memories": pinned,
            "pinned_count": len(pinned),
            "pinned_total_tokens": total_tokens,
            "pinned_source": src,
        }

    def detect_superseded(
        self,
        collection: Any,
        result_ids: list[str],
        similarity_threshold: float = 0.86,
        min_age_gap_days: int = 7,
        max_candidates: int = 10,
    ) -> dict[str, Any]:
        """検索結果またはコレクション内で上書き関係にある drawer ペアを検出する。"""
        if collection is None or not result_ids:
            return {"candidates": [], "checked": True, "pair_count_evaluated": 0}

        uniq = list(dict.fromkeys(result_ids))
        try:
            got = collection.get(ids=uniq, include=["embeddings", "metadatas"])
        except Exception as e:
            logger.warning("detect_superseded fetch failed: %s", e)
            return {"candidates": [], "checked": True, "pair_count_evaluated": 0}

        ids = got.get("ids") or []
        embs_raw = got.get("embeddings")
        if embs_raw is None:
            embs = []
        else:
            try:
                embs = list(embs_raw)
            except TypeError:
                embs = []
        metas = got.get("metadatas") or []

        def _parse_date(m: dict[str, Any]) -> Optional[datetime]:
            fa = m.get("filed_at") if m else None
            if not fa:
                return None
            try:
                s = str(fa).strip()
                if s.endswith("Z"):
                    s = s[:-1] + "+00:00"
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except (ValueError, TypeError, OSError):
                return None

        indexed: list[tuple[str, list[float], dict[str, Any], Optional[datetime]]] = []
        for i, did in enumerate(ids):
            emb = embs[i] if i < len(embs) else None
            meta = metas[i] if i < len(metas) else {}
            if emb is None:
                continue
            if hasattr(emb, "tolist"):
                emb = emb.tolist()
            if not isinstance(emb, list) or len(emb) == 0:
                continue
            emb_f = [float(x) for x in emb]
            dt = _parse_date(meta or {})
            indexed.append((did, emb_f, meta or {}, dt))

        pair_count = 0
        raw_cands: list[dict[str, Any]] = []
        for i in range(len(indexed)):
            for j in range(i + 1, len(indexed)):
                pair_count += 1
                a_id, a_emb, a_meta, a_dt = indexed[i]
                b_id, b_emb, b_meta, b_dt = indexed[j]
                sim = self._cosine_similarity(a_emb, b_emb)
                if sim < similarity_threshold:
                    continue
                if a_dt is None or b_dt is None:
                    continue
                age_gap = abs((a_dt - b_dt).days)
                if age_gap < min_age_gap_days:
                    continue
                if a_dt <= b_dt:
                    older_id, older_meta, older_dt = a_id, a_meta, a_dt
                    newer_id, newer_meta, newer_dt = b_id, b_meta, b_dt
                else:
                    older_id, older_meta, older_dt = b_id, b_meta, b_dt
                    newer_id, newer_meta, newer_dt = a_id, a_meta, a_dt
                if sim >= 0.93 and age_gap >= 30:
                    conf = "high"
                elif sim >= 0.86 and age_gap >= 14:
                    conf = "medium"
                else:
                    conf = "low"
                raw_cands.append(
                    {
                        "superseded_id": older_id,
                        "superseded_title": str((older_meta or {}).get("title", older_id)),
                        "superseded_date": older_dt.isoformat(),
                        "superseding_id": newer_id,
                        "superseding_title": str((newer_meta or {}).get("title", newer_id)),
                        "superseding_date": newer_dt.isoformat(),
                        "similarity": sim,
                        "age_gap_days": age_gap,
                        "confidence": conf,
                    }
                )

        conf_rank = {"high": 0, "medium": 1, "low": 2}
        raw_cands.sort(key=lambda c: (conf_rank.get(c["confidence"], 3), -c["similarity"]))
        return {
            "candidates": raw_cands[:max_candidates],
            "checked": True,
            "pair_count_evaluated": pair_count,
        }

    def detect_superseded_palace_wide(
        self,
        collection: Any,
        similarity_threshold: float = 0.86,
        min_age_gap_days: int = 7,
        max_candidates: int = 10,
        wing: Optional[str] = None,
    ) -> dict[str, Any]:
        """コレクション全体（または wing 限定）の drawer 間で supersede 候補を検出。"""
        if collection is None:
            return {"candidates": [], "checked": True, "pair_count_evaluated": 0}
        try:
            kwargs: dict[str, Any] = {"include": ["embeddings", "metadatas"], "limit": 10000}
            if wing:
                kwargs["where"] = {"wing": wing}
            got = collection.get(**kwargs)
            all_ids = list(got.get("ids") or [])
        except Exception as e:
            logger.warning("detect_superseded_palace_wide failed: %s", e)
            return {"candidates": [], "checked": True, "pair_count_evaluated": 0}
        return self.detect_superseded(
            collection,
            all_ids,
            similarity_threshold=similarity_threshold,
            min_age_gap_days=min_age_gap_days,
            max_candidates=max_candidates,
        )

    def apply_supersede_filter(
        self,
        results: list[dict[str, Any]],
        supersede_candidates: dict[str, Any],
        action: str = "filter",
    ) -> dict[str, Any]:
        """検索結果に supersede フィルタ／アノテーションを適用する。"""
        cands = supersede_candidates.get("candidates") or []
        superseded_ids = {c["superseded_id"] for c in cands}
        supers_map = {c["superseded_id"]: c for c in cands}
        detail = [
            {
                "superseded_id": c["superseded_id"],
                "superseding_id": c["superseding_id"],
                "similarity": c["similarity"],
                "confidence": c["confidence"],
            }
            for c in cands
        ]

        if action == "filter":
            out = [h for h in results if h.get("id") not in superseded_ids]
            return {
                "results": out,
                "synapse_supersede": {
                    "checked": True,
                    "action": "filter",
                    "superseded_filtered": len(results) - len(out),
                    "superseded_annotated": 0,
                    "detail": detail,
                },
            }

        annotated = 0
        out = []
        for h in results:
            hid = h.get("id")
            new_h = dict(h)
            if hid in supers_map:
                c = supers_map[hid]
                new_h["synapse_superseded_by"] = c["superseding_id"]
                new_h["synapse_supersede_note"] = (
                    f"Likely superseded by {c['superseding_id']} (similarity={c['similarity']:.3f})"
                )
                annotated += 1
            for c in cands:
                if c["superseding_id"] == hid:
                    prev = list(new_h.get("synapse_supersedes") or [])
                    if c["superseded_id"] not in prev:
                        prev.append(c["superseded_id"])
                    new_h["synapse_supersedes"] = prev
            out.append(new_h)

        return {
            "results": out,
            "synapse_supersede": {
                "checked": True,
                "action": "annotate",
                "superseded_filtered": 0,
                "superseded_annotated": annotated,
                "detail": detail,
            },
        }

    def consolidate(
        self,
        collection: Any,
        drawer_ids: list[str],
        summary: str,
        wing: Optional[str] = None,
        room: Optional[str] = None,
    ) -> dict[str, Any]:
        """指定 drawer 群を1つの統合 drawer にまとめる。"""
        if not summary or not str(summary).strip():
            raise ValueError("summary is required")
        if not drawer_ids:
            raise ValueError("drawer_ids must not be empty")
        got = collection.get(ids=drawer_ids, include=["metadatas", "documents"])
        got_ids = set(got.get("ids") or [])
        for did in drawer_ids:
            if did not in got_ids:
                raise ValueError(f"Unknown drawer id: {did}")

        metas = got.get("metadatas") or []
        wings = [m.get("wing") for m in metas if m]
        rooms = [m.get("room") for m in metas if m]
        w_mode = wing
        if w_mode is None and wings:
            w_mode = max(set(wings), key=wings.count)
        else:
            w_mode = w_mode or "unknown"
        r_mode = room
        if r_mode is None and rooms:
            r_mode = max(set(rooms), key=rooms.count)
        else:
            r_mode = r_mode or "unknown"

        new_id = f"consolidated_{uuid.uuid4().hex[:12]}"
        now = _utc_now_iso()
        collection.add(
            ids=[new_id],
            documents=[summary],
            metadatas=[
                {
                    "wing": w_mode,
                    "room": r_mode,
                    "status": "consolidated_summary",
                    "source_drawers": json.dumps(drawer_ids),
                    "consolidation_date": now,
                    "consolidation_count": len(drawer_ids),
                    "filed_at": now,
                }
            ],
        )
        fresh = collection.get(ids=drawer_ids, include=["metadatas"])
        upd_ids: list[str] = []
        upd_meta: list[dict[str, Any]] = []
        for i, did in enumerate(fresh.get("ids") or []):
            om = dict((fresh.get("metadatas") or [{}])[i] or {})
            om["status"] = "consolidated"
            om["consolidated_into"] = new_id
            upd_ids.append(did)
            upd_meta.append(om)
        if upd_ids:
            collection.update(ids=upd_ids, metadatas=upd_meta)

        return {
            "consolidated_drawer_id": new_id,
            "source_drawers_archived": len(drawer_ids),
            "wing": w_mode,
            "room": r_mode,
            "reversible": True,
            "undo_ids": list(drawer_ids),
        }

    def get_consolidated_sources(
        self, collection: Any, consolidated_drawer_id: str
    ) -> list[dict[str, Any]]:
        """統合 drawer の元 drawer 一覧を返す。"""
        got = collection.get(ids=[consolidated_drawer_id], include=["metadatas", "documents"])
        if not got.get("ids"):
            return []
        meta = (got.get("metadatas") or [{}])[0] or {}
        raw = meta.get("source_drawers")
        try:
            src_ids = json.loads(raw) if isinstance(raw, str) else []
        except json.JSONDecodeError:
            src_ids = []
        if not isinstance(src_ids, list):
            return []
        got2 = collection.get(ids=src_ids, include=["metadatas", "documents"])
        out: list[dict[str, Any]] = []
        for i, did in enumerate(got2.get("ids") or []):
            out.append(
                {
                    "id": did,
                    "content": (got2.get("documents") or [""])[i],
                    "metadata": (got2.get("metadatas") or [{}])[i] or {},
                }
            )
        return out

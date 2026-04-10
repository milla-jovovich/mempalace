import logging
import math
import os
import sqlite3
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
            cur = conn.execute(
                "SELECT drawer_id, COUNT(*) FROM retrieval_log GROUP BY drawer_id"
            )
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

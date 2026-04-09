import logging
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_LTP_WINDOW_DAYS = 30
DEFAULT_LTP_MAX_BOOST = 2.0
DEFAULT_LTP_COEFFICIENT = 0.3
DEFAULT_TAGGING_WINDOW_HOURS = 24
DEFAULT_TAGGING_MAX_BOOST = 1.5
SYNAPSE_DB_NAME = "synapse.sqlite3"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


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

    def log_retrieval(self, drawer_ids: list[str], query_hash: str, session_id: str):
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
            conn = sqlite3.connect(self.db_path)
            try:
                conn.executemany(
                    "INSERT INTO retrieval_log (drawer_id, retrieved_at, query_hash, session_id) "
                    "VALUES (?, ?, ?, ?)",
                    rows,
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning("log_retrieval failed: %s", e)

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
        conn = sqlite3.connect(self.db_path)
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
    ) -> dict[str, Any]:
        """
        最終スコアを計算して返す。
        final_score = similarity * decay * ltp * tagging
        (Phase 1 では association は 1.0 固定)

        戻り値:
        {
            "final_score": float,
            "similarity": float,
            "decay": float,
            "ltp": float,
            "association": 1.0,
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
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute("DELETE FROM retrieval_log WHERE retrieved_at < ?", (cutoff,))
            deleted = cur.rowcount
            conn.commit()
        finally:
            conn.close()
        try:
            vacuum_conn = sqlite3.connect(self.db_path)
            try:
                vacuum_conn.execute("VACUUM")
                vacuum_conn.commit()
            finally:
                vacuum_conn.close()
        except Exception as e:
            logger.warning("VACUUM failed: %s", e)
        if deleted is None or deleted < 0:
            return 0
        return int(deleted)

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

    def get_consolidation_candidates(self, inactive_days: int = 180) -> list[dict]:
        """
        inactive_days 以上検索されていない drawer_id のリストを返す。
        戻り値: [{"drawer_id": str, "last_retrieved_at": str, "days_inactive": int}]
        """
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=inactive_days)).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "SELECT drawer_id, MAX(retrieved_at) AS last_at FROM retrieval_log "
                "GROUP BY drawer_id HAVING MAX(retrieved_at) < ?",
                (cutoff,),
            )
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

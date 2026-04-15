"""
Lightweight project and task tracking for MemPalace.

This module adds a standalone tracker for:
  - registered projects
  - task lifecycle state
  - structured event logs
  - checkpoints for cross-session resume

It intentionally does not touch palace drawers or knowledge-graph tables.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


DEFAULT_PROJECT_TRACKER_PATH = os.path.expanduser("~/.mempalace/project_tracker.sqlite3")

VALID_PROJECT_STATUSES = frozenset({"active", "paused", "archived"})
ACTIVE_TASK_STATUSES = frozenset({"queued", "running", "waiting"})
TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "cancelled"})
VALID_TASK_STATUSES = ACTIVE_TASK_STATUSES | TERMINAL_TASK_STATUSES
VALID_EVENT_LEVELS = frozenset({"debug", "info", "warning", "error"})


class ProjectTrackerError(RuntimeError):
    """Raised when project tracking input or state is invalid."""


def _now_iso() -> str:
    return datetime.now().isoformat()


def _require_text(
    value: Any,
    field_name: str,
    *,
    max_length: int = 4000,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ProjectTrackerError(f"{field_name} must be a string")
    cleaned = value.strip()
    if not cleaned and not allow_empty:
        raise ProjectTrackerError(f"{field_name} must not be empty")
    if "\x00" in cleaned:
        raise ProjectTrackerError(f"{field_name} contains null bytes")
    if len(cleaned) > max_length:
        raise ProjectTrackerError(f"{field_name} exceeds maximum length of {max_length} characters")
    return cleaned


def _normalize_percent(percent: Any) -> Optional[float]:
    if percent is None:
        return None
    try:
        normalized = float(percent)
    except (TypeError, ValueError) as exc:
        raise ProjectTrackerError("percent must be a number between 0 and 100") from exc
    if normalized < 0 or normalized > 100:
        raise ProjectTrackerError("percent must be between 0 and 100")
    return round(normalized, 2)


def _normalize_status(status: str, allowed: frozenset[str], field_name: str) -> str:
    normalized = _require_text(status, field_name, max_length=32).lower()
    if normalized not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ProjectTrackerError(f"{field_name} must be one of: {allowed_text}")
    return normalized


def _json_dumps(value: Optional[Dict[str, Any]]) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _json_loads(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _normalize_payload(value: Optional[Dict[str, Any]], field_name: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProjectTrackerError(f"{field_name} must be a JSON object")
    return value


def _semantic_event_type(kind: str) -> str:
    if kind == "task_started":
        return "task.started"
    if kind == "task_updated":
        return "task.updated"
    if kind == "checkpoint":
        return "checkpoint.saved"
    if kind == "log":
        return "log.message"
    return kind.replace("_", ".")


def _hash_json(value: Dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ProjectTracker:
    def __init__(self, db_path: str = None):
        self.db_path = os.path.abspath(os.path.expanduser(db_path or DEFAULT_PROJECT_TRACKER_PATH))
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = None
        self._lock = threading.RLock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
        return self._connection

    def _init_db(self) -> None:
        conn = self._conn()
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                root_path TEXT NOT NULL UNIQUE,
                wing TEXT,
                source_type TEXT NOT NULL DEFAULT 'local',
                status TEXT NOT NULL DEFAULT 'active',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_activity_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(name);
            CREATE INDEX IF NOT EXISTS idx_projects_wing ON projects(wing);
            CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT,
                percent REAL,
                summary TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                updated_at TEXT NOT NULL,
                last_event_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id, last_event_at DESC);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                kind TEXT NOT NULL DEFAULT 'log',
                stage TEXT,
                percent REAL,
                message TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, id DESC);

            CREATE TABLE IF NOT EXISTS task_checkpoints (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                stage TEXT,
                summary TEXT NOT NULL,
                state_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_task_checkpoints_task
                ON task_checkpoints(task_id, created_at DESC);
            """
        )
        conn.commit()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def inspect_project_path(self, root_path: str) -> Dict[str, Any]:
        resolved_path = self._resolve_project_path(root_path)
        metadata: Dict[str, Any] = {
            "has_mempalace_yaml": False,
            "has_entities_json": False,
        }

        config_path = Path(resolved_path) / "mempalace.yaml"
        if config_path.is_file():
            metadata["has_mempalace_yaml"] = True
            try:
                loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            except (yaml.YAMLError, OSError):
                loaded = {}
            if isinstance(loaded, dict):
                wing = loaded.get("wing")
                if isinstance(wing, str) and wing.strip():
                    metadata["detected_wing"] = wing.strip()
                rooms = loaded.get("rooms")
                if isinstance(rooms, list):
                    metadata["room_count"] = len(rooms)

        entities_path = Path(resolved_path) / "entities.json"
        if entities_path.is_file():
            metadata["has_entities_json"] = True
            try:
                loaded = json.loads(entities_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                loaded = {}
            if isinstance(loaded, dict):
                people = loaded.get("people") or []
                projects = loaded.get("projects") or []
                if isinstance(people, list):
                    metadata["entity_people_count"] = len(people)
                if isinstance(projects, list):
                    metadata["entity_project_count"] = len(projects)

        return metadata

    def register_project(
        self,
        root_path: str,
        *,
        name: str = None,
        wing: str = None,
        source_type: str = "local",
        status: str = "active",
        metadata: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        resolved_path = self._resolve_project_path(root_path)
        source_type = _require_text(source_type, "source_type", max_length=32).lower()
        status = _normalize_status(status, VALID_PROJECT_STATUSES, "status")

        detected_metadata = self.inspect_project_path(resolved_path)
        merged_metadata = dict(detected_metadata)
        merged_metadata.update(_normalize_payload(metadata, "metadata"))

        project_name = name or Path(resolved_path).name
        project_name = _require_text(project_name, "name", max_length=200)
        project_wing = wing or detected_metadata.get("detected_wing") or project_name
        project_wing = _require_text(project_wing, "wing", max_length=200)
        now = _now_iso()

        with self._lock:
            conn = self._conn()
            existing = conn.execute(
                "SELECT * FROM projects WHERE root_path = ?",
                (resolved_path,),
            ).fetchone()
            if existing:
                existing_metadata = _json_loads(existing["metadata_json"])
                existing_metadata.update(merged_metadata)
                conn.execute(
                    """
                    UPDATE projects
                    SET name = ?, wing = ?, source_type = ?, status = ?,
                        metadata_json = ?, updated_at = ?, last_activity_at = ?
                    WHERE id = ?
                    """,
                    (
                        project_name,
                        project_wing,
                        source_type,
                        status,
                        _json_dumps(existing_metadata),
                        now,
                        now,
                        existing["id"],
                    ),
                )
                conn.commit()
                project_id = existing["id"]
                created = False
            else:
                project_id = self._make_project_id(resolved_path)
                conn.execute(
                    """
                    INSERT INTO projects (
                        id, name, root_path, wing, source_type, status,
                        metadata_json, created_at, updated_at, last_activity_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        project_name,
                        resolved_path,
                        project_wing,
                        source_type,
                        status,
                        _json_dumps(merged_metadata),
                        now,
                        now,
                        now,
                    ),
                )
                conn.commit()
                created = True

        result = self.get_project(project_id)
        result["created"] = created
        return result

    def get_project(self, selector: str) -> Dict[str, Any]:
        with self._lock:
            conn = self._conn()
            row = self._resolve_project_row(selector, conn)
            return self._serialize_project(row, conn, include_latest_task=True)

    def list_projects(self, limit: int = 50) -> Dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        with self._lock:
            conn = self._conn()
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY last_activity_at DESC, created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            projects = [
                self._serialize_project(row, conn, include_latest_task=True) for row in rows
            ]
            return {"projects": projects, "count": len(projects)}

    def project_status(self, selector: Optional[str] = None) -> Dict[str, Any]:
        if selector:
            project = self.get_project(selector)
            return {"project": project}
        return self.list_projects()

    def start_task(
        self,
        project_selector: str,
        title: str,
        *,
        status: str = "running",
        stage: str = None,
        percent: Any = None,
        summary: str = None,
        metadata: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        task_title = _require_text(title, "title", max_length=300)
        task_status = _normalize_status(status, VALID_TASK_STATUSES, "status")
        task_stage = _require_text(stage, "stage", max_length=200) if stage is not None else None
        task_percent = _normalize_percent(percent)
        task_summary = (
            _require_text(summary, "summary", max_length=4000) if summary is not None else None
        )
        task_metadata = _normalize_payload(metadata, "metadata")
        now = _now_iso()

        with self._lock:
            conn = self._conn()
            project = self._resolve_project_row(project_selector, conn)
            task_id = f"task_{uuid.uuid4().hex[:12]}"
            started_at = now if task_status in ACTIVE_TASK_STATUSES else None
            ended_at = now if task_status in TERMINAL_TASK_STATUSES else None
            conn.execute(
                """
                INSERT INTO tasks (
                    id, project_id, title, status, stage, percent, summary, metadata_json,
                    created_at, started_at, ended_at, updated_at, last_event_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    project["id"],
                    task_title,
                    task_status,
                    task_stage,
                    task_percent,
                    task_summary,
                    _json_dumps(task_metadata),
                    now,
                    started_at,
                    ended_at,
                    now,
                    now,
                ),
            )
            self._touch_project(conn, project["id"], now)
            self._insert_event(
                conn,
                task_id,
                level="info",
                kind="task_started",
                stage=task_stage,
                percent=task_percent,
                message=task_summary or f"Task started: {task_title}",
                payload={"status": task_status},
                created_at=now,
            )
            conn.commit()

        return self.get_task(task_id)

    def update_task(
        self,
        task_id: str,
        *,
        status: str = None,
        stage: str = None,
        percent: Any = None,
        summary: str = None,
        metadata: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        normalized_status = (
            _normalize_status(status, VALID_TASK_STATUSES, "status") if status is not None else None
        )
        normalized_stage = (
            _require_text(stage, "stage", max_length=200) if stage is not None else None
        )
        normalized_percent = _normalize_percent(percent) if percent is not None else None
        normalized_summary = (
            _require_text(summary, "summary", max_length=4000) if summary is not None else None
        )
        metadata_patch = _normalize_payload(metadata, "metadata")
        now = _now_iso()

        with self._lock:
            conn = self._conn()
            task = self._resolve_task_row(task_id, conn)
            merged_metadata = _json_loads(task["metadata_json"])
            merged_metadata.update(metadata_patch)

            next_status = normalized_status or task["status"]
            next_stage = normalized_stage if normalized_stage is not None else task["stage"]
            next_percent = normalized_percent if percent is not None else task["percent"]
            next_summary = normalized_summary if normalized_summary is not None else task["summary"]

            started_at = task["started_at"]
            if started_at is None and next_status in ACTIVE_TASK_STATUSES:
                started_at = now

            ended_at = task["ended_at"]
            if next_status in TERMINAL_TASK_STATUSES:
                ended_at = now
            elif normalized_status is not None:
                ended_at = None

            conn.execute(
                """
                UPDATE tasks
                SET status = ?, stage = ?, percent = ?, summary = ?, metadata_json = ?,
                    started_at = ?, ended_at = ?, updated_at = ?, last_event_at = ?
                WHERE id = ?
                """,
                (
                    next_status,
                    next_stage,
                    next_percent,
                    next_summary,
                    _json_dumps(merged_metadata),
                    started_at,
                    ended_at,
                    now,
                    now,
                    task["id"],
                ),
            )
            self._touch_project(conn, task["project_id"], now)
            event_message = next_summary or f"Task updated: {next_status}"
            self._insert_event(
                conn,
                task["id"],
                level="info",
                kind="task_updated",
                stage=next_stage,
                percent=next_percent,
                message=event_message,
                payload={"status": next_status},
                created_at=now,
            )
            conn.commit()

        return self.get_task(task_id)

    def log_event(
        self,
        task_id: str,
        message: str,
        *,
        level: str = "info",
        kind: str = "log",
        stage: str = None,
        percent: Any = None,
        payload: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        event_message = _require_text(message, "message", max_length=4000)
        event_level = _normalize_status(level, VALID_EVENT_LEVELS, "level")
        event_kind = _require_text(kind, "kind", max_length=64).lower()
        event_stage = _require_text(stage, "stage", max_length=200) if stage is not None else None
        event_percent = _normalize_percent(percent) if percent is not None else None
        event_payload = _normalize_payload(payload, "payload")
        now = _now_iso()

        with self._lock:
            conn = self._conn()
            task = self._resolve_task_row(task_id, conn)
            next_stage = event_stage if event_stage is not None else task["stage"]
            next_percent = event_percent if percent is not None else task["percent"]

            event_id = self._insert_event(
                conn,
                task["id"],
                level=event_level,
                kind=event_kind,
                stage=event_stage,
                percent=event_percent,
                message=event_message,
                payload=event_payload,
                created_at=now,
            )
            conn.execute(
                """
                UPDATE tasks
                SET stage = ?, percent = ?, updated_at = ?, last_event_at = ?
                WHERE id = ?
                """,
                (next_stage, next_percent, now, now, task["id"]),
            )
            self._touch_project(conn, task["project_id"], now)
            conn.commit()

        task_state = self.get_task(task_id)
        event = self._get_event_by_id(event_id)
        return {"task": task_state, "event": event}

    def add_checkpoint(
        self,
        task_id: str,
        summary: str,
        *,
        stage: str = None,
        state: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        checkpoint_summary = _require_text(summary, "summary", max_length=4000)
        checkpoint_stage = (
            _require_text(stage, "stage", max_length=200) if stage is not None else None
        )
        checkpoint_state = _normalize_payload(state, "state")
        now = _now_iso()

        with self._lock:
            conn = self._conn()
            task = self._resolve_task_row(task_id, conn)
            checkpoint_id = f"checkpoint_{task['id']}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            conn.execute(
                """
                INSERT INTO task_checkpoints (id, task_id, stage, summary, state_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    task["id"],
                    checkpoint_stage,
                    checkpoint_summary,
                    _json_dumps(checkpoint_state),
                    now,
                ),
            )
            next_stage = checkpoint_stage or task["stage"]
            conn.execute(
                """
                UPDATE tasks
                SET stage = ?, summary = ?, updated_at = ?, last_event_at = ?
                WHERE id = ?
                """,
                (next_stage, checkpoint_summary, now, now, task["id"]),
            )
            self._touch_project(conn, task["project_id"], now)
            self._insert_event(
                conn,
                task["id"],
                level="info",
                kind="checkpoint",
                stage=checkpoint_stage,
                percent=task["percent"],
                message=checkpoint_summary,
                payload={"checkpoint_id": checkpoint_id},
                created_at=now,
            )
            conn.commit()

        task_state = self.get_task(task_id)
        latest_checkpoint = task_state.get("latest_checkpoint")
        return {"task": task_state, "checkpoint": latest_checkpoint}

    def get_task(
        self,
        task_id: str,
        *,
        include_events: int = 20,
        include_checkpoints: int = 5,
    ) -> Dict[str, Any]:
        include_events = max(0, min(int(include_events), 200))
        include_checkpoints = max(0, min(int(include_checkpoints), 50))
        with self._lock:
            conn = self._conn()
            row = self._resolve_task_row(task_id, conn)
            return self._serialize_task(
                row,
                conn,
                include_events=include_events,
                include_checkpoints=include_checkpoints,
            )

    def resume_task(
        self,
        *,
        task_id: str = None,
        project_selector: str = None,
        events_limit: int = 20,
        checkpoints_limit: int = 5,
    ) -> Dict[str, Any]:
        if task_id:
            task = self.get_task(
                task_id,
                include_events=events_limit,
                include_checkpoints=checkpoints_limit,
            )
        else:
            with self._lock:
                conn = self._conn()
                if project_selector:
                    project = self._resolve_project_row(project_selector, conn)
                    row = conn.execute(
                        """
                        SELECT * FROM tasks
                        WHERE project_id = ?
                        ORDER BY last_event_at DESC, created_at DESC
                        LIMIT 1
                        """,
                        (project["id"],),
                    ).fetchone()
                    if row is None:
                        return {
                            "project": self._serialize_project(
                                project, conn, include_latest_task=False
                            ),
                            "task": None,
                            "message": "No tasks found for this project",
                        }
                    task = self._serialize_task(
                        row,
                        conn,
                        include_events=events_limit,
                        include_checkpoints=checkpoints_limit,
                    )
                else:
                    row = conn.execute(
                        """
                        SELECT * FROM tasks
                        ORDER BY last_event_at DESC, created_at DESC
                        LIMIT 1
                        """
                    ).fetchone()
                    if row is None:
                        return {"task": None, "message": "No tracked tasks found"}
                    task = self._serialize_task(
                        row,
                        conn,
                        include_events=events_limit,
                        include_checkpoints=checkpoints_limit,
                    )

        return {
            "recovered_at": _now_iso(),
            "project": task["project"],
            "task": task,
            "thread": task.get("thread"),
            "latest_checkpoint": task.get("latest_checkpoint"),
            "recent_events": task.get("events", []),
        }

    def _resolve_project_path(self, root_path: str) -> str:
        candidate = Path(os.path.expanduser(root_path)).resolve()
        if not candidate.exists():
            raise ProjectTrackerError(f"project path does not exist: {candidate}")
        if not candidate.is_dir():
            raise ProjectTrackerError(f"project path is not a directory: {candidate}")
        return str(candidate)

    def _make_project_id(self, root_path: str) -> str:
        digest = hashlib.sha256(root_path.encode("utf-8")).hexdigest()[:12]
        return f"project_{digest}"

    def _resolve_project_row(self, selector: str, conn: sqlite3.Connection) -> sqlite3.Row:
        selector_text = _require_text(selector, "project selector", max_length=2048)
        resolved_selector = os.path.abspath(os.path.expanduser(selector_text))

        row = conn.execute("SELECT * FROM projects WHERE id = ?", (selector_text,)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM projects WHERE root_path = ?",
                (resolved_selector,),
            ).fetchone()
        if row is None:
            row = conn.execute("SELECT * FROM projects WHERE name = ?", (selector_text,)).fetchone()
        if row is None:
            raise ProjectTrackerError(f"project not found: {selector_text}")
        return row

    def _resolve_task_row(self, task_id: str, conn: sqlite3.Connection) -> sqlite3.Row:
        normalized = _require_text(task_id, "task_id", max_length=128)
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (normalized,)).fetchone()
        if row is None:
            raise ProjectTrackerError(f"task not found: {normalized}")
        return row

    def _touch_project(self, conn: sqlite3.Connection, project_id: str, timestamp: str) -> None:
        conn.execute(
            "UPDATE projects SET updated_at = ?, last_activity_at = ? WHERE id = ?",
            (timestamp, timestamp, project_id),
        )

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        task_id: str,
        *,
        level: str,
        kind: str,
        stage: str,
        percent: Optional[float],
        message: str,
        payload: Dict[str, Any],
        created_at: str,
    ) -> int:
        cur = conn.execute(
            """
            INSERT INTO task_events (task_id, level, kind, stage, percent, message, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                level,
                kind,
                stage,
                percent,
                message,
                _json_dumps(payload),
                created_at,
            ),
        )
        return int(cur.lastrowid)

    def _get_event_by_id(self, event_id: int) -> Dict[str, Any]:
        with self._lock:
            conn = self._conn()
            row = conn.execute("SELECT * FROM task_events WHERE id = ?", (event_id,)).fetchone()
            if row is None:
                raise ProjectTrackerError(f"event not found: {event_id}")
            return self._serialize_event(row)

    def _serialize_project(
        self,
        row: sqlite3.Row,
        conn: sqlite3.Connection,
        *,
        include_latest_task: bool,
    ) -> Dict[str, Any]:
        counts = {
            status: count
            for status, count in conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM tasks
                WHERE project_id = ?
                GROUP BY status
                """,
                (row["id"],),
            ).fetchall()
        }
        latest_task = None
        if include_latest_task:
            latest_task_row = conn.execute(
                """
                SELECT * FROM tasks
                WHERE project_id = ?
                ORDER BY last_event_at DESC, created_at DESC
                LIMIT 1
                """,
                (row["id"],),
            ).fetchone()
            if latest_task_row is not None:
                latest_task = self._serialize_task(
                    latest_task_row,
                    conn,
                    include_events=0,
                    include_checkpoints=0,
                )

        return {
            "project_id": row["id"],
            "name": row["name"],
            "root_path": row["root_path"],
            "wing": row["wing"],
            "source_type": row["source_type"],
            "status": row["status"],
            "metadata": _json_loads(row["metadata_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_activity_at": row["last_activity_at"],
            "task_counts": counts,
            "latest_task": latest_task,
        }

    def _serialize_task(
        self,
        row: sqlite3.Row,
        conn: sqlite3.Connection,
        *,
        include_events: int,
        include_checkpoints: int,
    ) -> Dict[str, Any]:
        project_row = conn.execute(
            "SELECT * FROM projects WHERE id = ?",
            (row["project_id"],),
        ).fetchone()
        task = {
            "task_id": row["id"],
            "thread_id": row["id"],
            "project_id": row["project_id"],
            "title": row["title"],
            "status": row["status"],
            "stage": row["stage"],
            "percent": row["percent"],
            "summary": row["summary"],
            "metadata": _json_loads(row["metadata_json"]),
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "updated_at": row["updated_at"],
            "last_event_at": row["last_event_at"],
            "project": self._serialize_project(project_row, conn, include_latest_task=False),
        }

        latest_checkpoint_row = conn.execute(
            """
            SELECT * FROM task_checkpoints
            WHERE task_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (row["id"],),
        ).fetchone()
        if latest_checkpoint_row is not None:
            task["latest_checkpoint"] = self._serialize_checkpoint(latest_checkpoint_row)

        checkpoints: List[Dict[str, Any]] = []
        if include_checkpoints:
            checkpoint_rows = conn.execute(
                """
                SELECT * FROM task_checkpoints
                WHERE task_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (row["id"], include_checkpoints),
            ).fetchall()
            checkpoints = [self._serialize_checkpoint(cp_row) for cp_row in reversed(checkpoint_rows)]
        if checkpoints:
            task["checkpoints"] = checkpoints
            task["latest_checkpoint"] = checkpoints[-1]

        events: List[Dict[str, Any]] = []
        if include_events:
            event_rows = conn.execute(
                """
                SELECT * FROM task_events
                WHERE task_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (row["id"], include_events),
            ).fetchall()
            events = self._annotate_event_chain(
                [self._serialize_event(event_row) for event_row in reversed(event_rows)]
            )
        if events:
            task["events"] = events
            task["event_chain"] = events

        task["thread"] = self._build_thread_snapshot(task)

        return task

    def _serialize_event(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "event_id": row["id"],
            "task_id": row["task_id"],
            "level": row["level"],
            "kind": row["kind"],
            "stage": row["stage"],
            "percent": row["percent"],
            "message": row["message"],
            "payload": _json_loads(row["payload_json"]),
            "created_at": row["created_at"],
            "event_type": _semantic_event_type(row["kind"]),
            "source": "mempalace.project_tracker",
            "source_event_type": row["kind"],
        }

    def _serialize_checkpoint(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "checkpoint_id": row["id"],
            "task_id": row["task_id"],
            "stage": row["stage"],
            "summary": row["summary"],
            "state": _json_loads(row["state_json"]),
            "created_at": row["created_at"],
        }

    def _annotate_event_chain(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        previous_chain_hash: Optional[str] = None
        annotated: List[Dict[str, Any]] = []
        for sequence, event in enumerate(events, start=1):
            event_hash = _hash_json(
                {
                    "task_id": event["task_id"],
                    "event_id": event["event_id"],
                    "event_type": event["event_type"],
                    "level": event["level"],
                    "stage": event["stage"],
                    "percent": event["percent"],
                    "message": event["message"],
                    "payload": event["payload"],
                    "created_at": event["created_at"],
                }
            )
            chain_hash = hashlib.sha256(
                f"{previous_chain_hash or ''}:{event_hash}".encode("utf-8")
            ).hexdigest()
            enriched = dict(event)
            enriched["sequence"] = sequence
            enriched["event_hash"] = event_hash
            enriched["previous_event_hash"] = previous_chain_hash
            enriched["chain_hash"] = chain_hash
            annotated.append(enriched)
            previous_chain_hash = chain_hash
        return annotated

    def _build_thread_snapshot(self, task: Dict[str, Any]) -> Dict[str, Any]:
        checkpoint = task.get("latest_checkpoint") or {}
        project = task.get("project") or {}
        return {
            "thread_id": task["task_id"],
            "checkpoint_ns": "mempalace.task",
            "checkpoint_id": checkpoint.get("checkpoint_id"),
            "checkpoint_created_at": checkpoint.get("created_at"),
            "checkpoint_state": checkpoint.get("state", {}),
            "values": {
                "status": task.get("status"),
                "stage": task.get("stage"),
                "percent": task.get("percent"),
                "summary": task.get("summary"),
                "metadata": task.get("metadata", {}),
                "project_id": task.get("project_id"),
                "project_wing": project.get("wing"),
            },
        }

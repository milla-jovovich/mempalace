"""
Context orchestration for MemPalace.

This is intentionally a thin composition layer on top of existing MemPalace
primitives. The design borrows two ideas from mature open-source projects:

- LangGraph persistence: separate thread/checkpoint state from long-term store
- agent-evidence: normalize logs into semantic event envelopes with hash chains

The goal is not to replace MemPalace with a new runtime. The goal is to expose
the memory + tracker data in a shape that agent clients can consume directly.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import MempalaceConfig, sanitize_name
from .layers import MemoryStack
from .palace import get_collection
from .project_tracker import ProjectTracker, ProjectTrackerError
from .searcher import search_memories

DEFAULT_MAX_CHARS = 12_000
DEFAULT_MEMORY_RESULTS = 5
DEFAULT_SEARCH_RESULTS = 5
DEFAULT_EVENT_LIMIT = 8
DEFAULT_CHECKPOINT_LIMIT = 3
DEFAULT_DIARY_ENTRIES = 3

REFERENCE_MODELS = [
    {
        "name": "LangGraph persistence",
        "url": "https://github.com/langchain-ai/langgraph",
        "concept": "thread/checkpoint/store separation",
    },
    {
        "name": "agent-evidence",
        "url": "https://github.com/joy7758/agent-evidence",
        "concept": "structured semantic event envelopes",
    },
]


class ContextManagerError(RuntimeError):
    """Raised when a context pack cannot be built."""


def _now_iso() -> str:
    return datetime.now().isoformat()


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ContextManagerError(f"value must be an integer between {minimum} and {maximum}") from exc
    return max(minimum, min(normalized, maximum))


def _json_preview(value: Any, max_chars: int = 400) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 16] + "... [truncated]"


def _clip_text(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 16].rstrip() + "\n...[truncated]"


def _normalize_snippet(text: str, max_chars: int = 320) -> str:
    flattened = " ".join((text or "").split())
    if len(flattened) <= max_chars:
        return flattened
    return flattened[: max_chars - 3] + "..."


class ContextManager:
    def __init__(
        self,
        *,
        palace_path: str = None,
        tracker: ProjectTracker = None,
        config: MempalaceConfig = None,
    ):
        self.config = config or MempalaceConfig()
        self.palace_path = palace_path or self.config.palace_path
        self.tracker = tracker or ProjectTracker(db_path=self.config.project_tracker_path)
        self.stack = MemoryStack(palace_path=self.palace_path)

    def build_context_pack(
        self,
        *,
        query: str = None,
        wing: str = None,
        room: str = None,
        task_id: str = None,
        project_selector: str = None,
        agent_name: str = None,
        memory_results: int = DEFAULT_MEMORY_RESULTS,
        search_results: int = DEFAULT_SEARCH_RESULTS,
        events_limit: int = DEFAULT_EVENT_LIMIT,
        checkpoints_limit: int = DEFAULT_CHECKPOINT_LIMIT,
        diary_entries: int = DEFAULT_DIARY_ENTRIES,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> Dict[str, Any]:
        memory_results = _clamp_int(memory_results, DEFAULT_MEMORY_RESULTS, 1, 20)
        search_results = _clamp_int(search_results, DEFAULT_SEARCH_RESULTS, 1, 20)
        events_limit = _clamp_int(events_limit, DEFAULT_EVENT_LIMIT, 0, 50)
        checkpoints_limit = _clamp_int(checkpoints_limit, DEFAULT_CHECKPOINT_LIMIT, 0, 20)
        diary_entries = _clamp_int(diary_entries, DEFAULT_DIARY_ENTRIES, 0, 20)
        max_chars = _clamp_int(max_chars, DEFAULT_MAX_CHARS, 1200, 100_000)

        query_text = None
        if query is not None:
            if not isinstance(query, str):
                raise ContextManagerError("query must be a string")
            query_text = query.strip() or None

        if wing:
            wing = sanitize_name(wing, "wing")
        if room:
            room = sanitize_name(room, "room")
        if agent_name:
            agent_name = sanitize_name(agent_name, "agent_name")

        thread_bundle = self._load_thread(
            task_id=task_id,
            project_selector=project_selector,
            events_limit=events_limit,
            checkpoints_limit=checkpoints_limit,
        )
        resolved_wing = wing or self._infer_wing(thread_bundle)

        wake_up_text = self.stack.wake_up(wing=resolved_wing)
        recall_text = None
        if resolved_wing or room:
            recall_text = self.stack.recall(
                wing=resolved_wing,
                room=room,
                n_results=memory_results,
            )

        search_payload = {"query": query_text, "filters": {"wing": resolved_wing, "room": room}, "results": []}
        if query_text:
            search_payload = search_memories(
                query=query_text,
                palace_path=self.palace_path,
                wing=resolved_wing,
                room=room,
                n_results=search_results,
            )

        diary_payload = self._read_diary_entries(agent_name, diary_entries)
        checkpoint_signal = self._peek_recent_checkpoint()

        section_specs = [
            ("THREAD SNAPSHOT", self._render_thread_snapshot(thread_bundle), 0),
            ("WAKE-UP", wake_up_text, 1),
            ("ON-DEMAND MEMORY", recall_text, 2),
            ("SEMANTIC SEARCH", self._render_search_hits(search_payload), 3),
            ("RECENT DIARY", self._render_diary_entries(diary_payload), 4),
            ("SAVE HOOK SIGNAL", self._render_checkpoint_signal(checkpoint_signal), 5),
            ("RECENT EVENTS", self._render_event_chain(thread_bundle, events_limit), 6),
        ]
        prompt, sections = self._assemble_prompt(section_specs, max_chars)

        task = thread_bundle.get("task")
        return {
            "generated_at": _now_iso(),
            "mode": "context_pack_v1",
            "references": REFERENCE_MODELS,
            "scope": {
                "palace_path": self.palace_path,
                "wing": resolved_wing,
                "room": room,
                "query": query_text,
                "agent_name": agent_name,
                "project": project_selector,
                "task_id": task_id or (task or {}).get("task_id"),
            },
            "thread": (task or {}).get("thread"),
            "project": thread_bundle.get("project"),
            "task": task,
            "wake_up": wake_up_text,
            "recall": recall_text,
            "search": search_payload,
            "diary": diary_payload,
            "checkpoint_signal": checkpoint_signal,
            "prompt": prompt,
            "prompt_chars": len(prompt),
            "prompt_tokens_est": _estimate_tokens(prompt),
            "sections": sections,
        }

    def _load_thread(
        self,
        *,
        task_id: str = None,
        project_selector: str = None,
        events_limit: int,
        checkpoints_limit: int,
    ) -> Dict[str, Any]:
        if not task_id and not project_selector:
            return {}
        try:
            return self.tracker.resume_task(
                task_id=task_id,
                project_selector=project_selector,
                events_limit=events_limit,
                checkpoints_limit=checkpoints_limit,
            )
        except ProjectTrackerError as exc:
            raise ContextManagerError(str(exc)) from exc

    def _infer_wing(self, thread_bundle: Dict[str, Any]) -> Optional[str]:
        project = thread_bundle.get("project") or {}
        if isinstance(project, dict):
            wing = project.get("wing")
            if isinstance(wing, str) and wing.strip():
                return wing.strip()
        task = thread_bundle.get("task") or {}
        task_project = task.get("project") or {}
        if isinstance(task_project, dict):
            wing = task_project.get("wing")
            if isinstance(wing, str) and wing.strip():
                return wing.strip()
        return None

    def _read_diary_entries(self, agent_name: Optional[str], last_n: int) -> Dict[str, Any]:
        if not agent_name or last_n <= 0:
            return {"agent": agent_name, "entries": [], "showing": 0, "total": 0}

        wing = f"wing_{agent_name.lower().replace(' ', '_')}"
        try:
            col = get_collection(self.palace_path, create=False)
        except Exception:
            return {"agent": agent_name, "entries": [], "showing": 0, "total": 0}

        try:
            results = col.get(
                where={"$and": [{"wing": wing}, {"room": "diary"}]},
                include=["documents", "metadatas"],
                limit=10_000,
            )
        except Exception:
            return {"agent": agent_name, "entries": [], "showing": 0, "total": 0}

        ids = results.get("ids") or []
        docs = results.get("documents") or []
        metas = results.get("metadatas") or []
        entries: List[Dict[str, Any]] = []
        for doc, meta in zip(docs, metas):
            entries.append(
                {
                    "timestamp": meta.get("filed_at", ""),
                    "date": meta.get("date", ""),
                    "topic": meta.get("topic", ""),
                    "content": doc,
                }
            )
        entries.sort(key=lambda item: item["timestamp"], reverse=True)
        visible = entries[:last_n]
        return {
            "agent": agent_name,
            "entries": visible,
            "showing": len(visible),
            "total": len(ids),
        }

    def _peek_recent_checkpoint(self) -> Optional[Dict[str, Any]]:
        ack_file = Path.home() / ".mempalace" / "hook_state" / "last_checkpoint"
        if not ack_file.is_file():
            return None
        try:
            data = json.loads(ack_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return {
            "status": "pending_ack",
            "message": data.get("message") or "Recent save hook checkpoint is waiting to be acknowledged.",
            "count": data.get("msgs", 0),
            "timestamp": data.get("timestamp") or data.get("ts"),
        }

    def _render_thread_snapshot(self, thread_bundle: Dict[str, Any]) -> Optional[str]:
        task = thread_bundle.get("task")
        if not isinstance(task, dict):
            return thread_bundle.get("message")

        project = task.get("project") or {}
        thread = task.get("thread") or {}
        lines = [
            f"thread_id: {thread.get('thread_id') or task.get('task_id')}",
            f"checkpoint_ns: {thread.get('checkpoint_ns') or 'mempalace.task'}",
            f"project: {project.get('name') or project.get('project_id')}",
            f"wing: {project.get('wing') or '-'}",
            f"status: {task.get('status') or '-'}",
            f"stage: {task.get('stage') or '-'}",
            f"percent: {task.get('percent') if task.get('percent') is not None else '-'}",
            f"summary: {task.get('summary') or '-'}",
        ]
        if thread.get("checkpoint_id"):
            lines.append(f"checkpoint_id: {thread['checkpoint_id']}")
        checkpoint_state = thread.get("checkpoint_state") or {}
        if checkpoint_state:
            lines.append(f"checkpoint_state: {_json_preview(checkpoint_state)}")
        return "\n".join(lines)

    def _render_search_hits(self, search_payload: Dict[str, Any]) -> Optional[str]:
        if not isinstance(search_payload, dict):
            return None
        if search_payload.get("error"):
            return search_payload["error"]
        hits = search_payload.get("results") or []
        if not hits:
            query = search_payload.get("query") or "current query"
            return f"No semantic matches found for: {query}"
        lines = []
        for index, hit in enumerate(hits, 1):
            lines.append(
                f"[{index}] {hit.get('wing', '?')}/{hit.get('room', '?')} "
                f"sim={hit.get('similarity', '?')} src={hit.get('source_file', '?')}"
            )
            lines.append(f"    {_normalize_snippet(hit.get('text', ''))}")
        return "\n".join(lines)

    def _render_diary_entries(self, diary_payload: Dict[str, Any]) -> Optional[str]:
        entries = (diary_payload or {}).get("entries") or []
        if not entries:
            return None
        lines = []
        for entry in entries:
            stamp = entry.get("timestamp") or entry.get("date") or "unknown-time"
            topic = entry.get("topic") or "general"
            lines.append(f"[{stamp}] {topic}: {_normalize_snippet(entry.get('content', ''))}")
        return "\n".join(lines)

    def _render_checkpoint_signal(self, checkpoint_signal: Optional[Dict[str, Any]]) -> Optional[str]:
        if not checkpoint_signal:
            return None
        lines = [
            checkpoint_signal.get("message") or "Recent save hook checkpoint detected.",
            f"messages_saved: {checkpoint_signal.get('count', 0)}",
        ]
        if checkpoint_signal.get("timestamp"):
            lines.append(f"timestamp: {checkpoint_signal['timestamp']}")
        return "\n".join(lines)

    def _render_event_chain(self, thread_bundle: Dict[str, Any], event_limit: int) -> Optional[str]:
        task = thread_bundle.get("task") or {}
        events = task.get("event_chain") or task.get("events") or []
        if not events or event_limit <= 0:
            return None

        lines = []
        for event in events[:event_limit]:
            event_type = event.get("event_type") or event.get("kind") or "log"
            stage = event.get("stage") or "-"
            percent = event.get("percent")
            lines.append(
                f"[{event.get('sequence', '?')}] {event.get('created_at')} "
                f"{event_type} stage={stage} percent={percent if percent is not None else '-'}"
            )
            lines.append(f"    {event.get('message')}")
            if event.get("payload"):
                lines.append(f"    payload={_json_preview(event['payload'], max_chars=240)}")
            if event.get("chain_hash"):
                lines.append(f"    chain={event['chain_hash'][:16]}")
        return "\n".join(lines)

    def _assemble_prompt(
        self,
        section_specs: List[Tuple[str, Optional[str], int]],
        max_chars: int,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        ordered = sorted(section_specs, key=lambda item: item[2])
        prompt_parts: List[str] = []
        section_meta: List[Dict[str, Any]] = []
        used_chars = 0

        for title, body, _priority in ordered:
            if not body:
                continue
            section_text = f"## {title}\n{body}".strip()
            section_chars = len(section_text)
            remaining = max_chars - used_chars
            if remaining <= 0:
                section_meta.append(
                    {
                        "title": title,
                        "included": False,
                        "truncated": False,
                        "chars": section_chars,
                    }
                )
                continue

            included_text = section_text
            truncated = False
            if section_chars > remaining:
                included_text = _clip_text(section_text, remaining)
                truncated = True

            prompt_parts.append(included_text)
            used_chars += len(included_text) + (2 if prompt_parts else 0)
            section_meta.append(
                {
                    "title": title,
                    "included": True,
                    "truncated": truncated,
                    "chars": len(included_text),
                }
            )

        prompt = "\n\n".join(part for part in prompt_parts if part)
        return prompt, section_meta

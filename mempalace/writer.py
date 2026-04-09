"""Shared drawer metadata and write helpers."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


_DEFAULT_IMPORTANCE = 3
_DEFAULT_CONFIDENCE = 1.0


def _md5_hexdigest(value: str) -> str:
    return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()


def hash_content(content: str) -> str:
    return _md5_hexdigest(content)


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    return slug.strip("_") or "unknown"


def resolve_source_updated_at(source: Any = None) -> str:
    if source in (None, ""):
        return ""
    if isinstance(source, datetime):
        return source.isoformat()

    try:
        source_path = Path(source)
    except TypeError:
        return str(source)

    if source_path.exists():
        return datetime.fromtimestamp(source_path.stat().st_mtime).isoformat()
    return str(source)


def build_source_group_id(
    source_type: str,
    *,
    source_file: str = "",
    wing: str = "",
    room: str = "",
) -> str:
    if source_type == "manual_drawer":
        return f"manual_drawer:{wing}:{room}"
    if source_file:
        return f"{source_type}_{_md5_hexdigest(source_file)[:16]}"
    return f"{source_type}_{_md5_hexdigest(f'{wing}:{room}')[:16]}"


def build_closet_id(wing: str, room: str, source_group_id: str) -> str:
    return f"closet_{_slug(wing)}_{_slug(room)}_{_md5_hexdigest(source_group_id)[:12]}"


def build_drawer_id(
    wing: str,
    room: str,
    *,
    source_file: Optional[str] = None,
    chunk_index: int = 0,
    content: Optional[str] = None,
    filed_at: Optional[str] = None,
) -> str:
    if source_file:
        seed = f"{source_file}{chunk_index}"
    else:
        seed = f"{(content or '')[:100]}{filed_at or ''}"
    return f"drawer_{wing}_{room}_{_md5_hexdigest(seed)[:16]}"


def build_shared_metadata(
    wing: str,
    room: str,
    content: str,
    *,
    source_file: str = "",
    chunk_index: int = 0,
    added_by: str = "",
    filed_at: Optional[str] = None,
    source_type: str,
    hall: str,
    memory_type: str,
    importance: int = _DEFAULT_IMPORTANCE,
    confidence: float = _DEFAULT_CONFIDENCE,
    source_group_id: Optional[str] = None,
    source_updated_at: Any = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    filed_at = filed_at or datetime.now().isoformat()
    source_group_id = source_group_id or build_source_group_id(
        source_type,
        source_file=source_file,
        wing=wing,
        room=room,
    )

    metadata = {
        "wing": wing,
        "room": room,
        "source_file": source_file,
        "chunk_index": chunk_index,
        "added_by": added_by,
        "filed_at": filed_at,
        "closet_id": build_closet_id(wing, room, source_group_id),
        "source_group_id": source_group_id,
        "source_type": source_type,
        "hall": hall,
        "memory_type": memory_type,
        "importance": importance,
        "confidence": confidence,
        "content_hash": hash_content(content),
        "source_updated_at": resolve_source_updated_at(source_updated_at),
    }

    if extra_metadata:
        protected_keys = frozenset(metadata.keys())
        for key, value in extra_metadata.items():
            if value is None:
                continue
            if key in protected_keys:
                raise ValueError(
                    f"extra_metadata key '{key}' conflicts with core metadata field"
                )
            metadata[key] = value

    return metadata


def add_collection_drawer(collection, drawer_id: str, content: str, metadata: Dict[str, Any]):
    collection.add(
        ids=[drawer_id],
        documents=[content],
        metadatas=[metadata],
    )

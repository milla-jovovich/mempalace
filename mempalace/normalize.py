#!/usr/bin/env python3
"""
normalize.py — Convert any chat export format to MemPalace transcript format.

Supported:
    - Plain text with > markers (pass through)
    - Claude.ai JSON export
    - ChatGPT conversations.json
    - Claude Code JSONL
    - Slack JSON export
    - Plain text (pass through for paragraph chunking)

No API key. No internet. Everything local.
"""

import json
import os
from pathlib import Path
from typing import Optional

SEGMENT_SEPARATOR = "\n\n---\n\n"


def normalize(filepath: str) -> str:
    """
    Load a file and normalize to transcript format if it's a chat export.
    Plain text files pass through unchanged.
    """
    return join_normalized_segments(normalize_segments(filepath))


def join_normalized_segments(segments: list[str]) -> str:
    if not segments:
        return ""
    if len(segments) == 1:
        return segments[0]
    return SEGMENT_SEPARATOR.join(segment.strip() for segment in segments if segment.strip())


def normalize_segments(filepath: str) -> list[str]:
    """
    Load a file and normalize it to one or more transcript segments.
    Most current formats produce a single segment, but callers can use this
    helper to preserve boundaries when that changes.
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        raise IOError(f"Could not read {filepath}: {e}")

    if not content.strip():
        return [content]

    # Already has > markers — pass through
    lines = content.split("\n")
    if sum(1 for line in lines if line.strip().startswith(">")) >= 3:
        return [content]

    # Try JSON normalization
    ext = Path(filepath).suffix.lower()
    if ext in (".json", ".jsonl") or content.strip()[:1] in ("{", "["):
        normalized = _try_normalize_json(content)
        if normalized:
            return [normalized]

    return [content]


def _try_normalize_json(content: str) -> Optional[str]:
    """Try all known JSON chat schemas."""

    normalized = _try_claude_code_jsonl(content)
    if normalized:
        return normalized

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None

    for parser in (_try_claude_ai_json, _try_chatgpt_json, _try_slack_json):
        normalized = parser(data)
        if normalized:
            return normalized

    return None


def _try_claude_code_jsonl(content: str) -> Optional[str]:
    """Claude Code JSONL sessions."""
    lines = [line.strip() for line in content.strip().split("\n") if line.strip()]
    messages = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        msg_type = entry.get("type", "")
        message = entry.get("message", {})
        if msg_type == "human":
            text = _extract_content(message.get("content", ""))
            if text:
                messages.append(("user", text))
        elif msg_type == "assistant":
            text = _extract_content(message.get("content", ""))
            if text:
                messages.append(("assistant", text))
    if len(messages) >= 2:
        return _messages_to_transcript(messages)
    return None


def _try_claude_ai_json(data) -> Optional[str]:
    """Claude.ai JSON export: [{"role": "user", "content": "..."}]"""
    if isinstance(data, dict):
        data = data.get("messages", data.get("chat_messages", []))
    if not isinstance(data, list):
        return None
    messages = []
    for item in data:
        if not isinstance(item, dict):
            continue
        role = item.get("role", "")
        text = _extract_content(item.get("content", ""))
        if role in ("user", "human") and text:
            messages.append(("user", text))
        elif role in ("assistant", "ai") and text:
            messages.append(("assistant", text))
    if len(messages) >= 2:
        return _messages_to_transcript(messages)
    return None


def _try_chatgpt_json(data) -> Optional[str]:
    """ChatGPT conversations.json with mapping tree."""
    if not isinstance(data, dict) or "mapping" not in data:
        return None
    mapping = data["mapping"]
    messages = []
    # Find root: prefer node with parent=None AND no message (synthetic root)
    root_id = None
    fallback_root = None
    for node_id, node in mapping.items():
        if node.get("parent") is None:
            if node.get("message") is None:
                root_id = node_id
                break
            elif fallback_root is None:
                fallback_root = node_id
    if not root_id:
        root_id = fallback_root
    if root_id:
        current_id = root_id
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            node = mapping.get(current_id, {})
            msg = node.get("message")
            if msg:
                role = msg.get("author", {}).get("role", "")
                content = msg.get("content", {})
                parts = content.get("parts", []) if isinstance(content, dict) else []
                text = " ".join(str(p) for p in parts if isinstance(p, str) and p).strip()
                if role == "user" and text:
                    messages.append(("user", text))
                elif role == "assistant" and text:
                    messages.append(("assistant", text))
            children = node.get("children", [])
            current_id = children[0] if children else None
    if len(messages) >= 2:
        return _messages_to_transcript(messages)
    return None


def _try_slack_json(data) -> Optional[str]:
    """
    Slack channel export: [{"type": "message", "user": "...", "text": "..."}]
    Optimized for 2-person DMs. In channels with 3+ people, alternating
    speakers are labeled user/assistant to preserve the exchange structure.
    """
    if not isinstance(data, list):
        return None
    messages = []
    seen_users = {}
    last_role = None
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        user_id = item.get("user", item.get("username", ""))
        text = item.get("text", "").strip()
        if not text or not user_id:
            continue
        if user_id not in seen_users:
            # Alternate roles so exchange chunking works with any number of speakers
            if not seen_users:
                seen_users[user_id] = "user"
            elif last_role == "user":
                seen_users[user_id] = "assistant"
            else:
                seen_users[user_id] = "user"
        last_role = seen_users[user_id]
        messages.append((seen_users[user_id], text))
    if len(messages) >= 2:
        return _messages_to_transcript(messages)
    return None


def _extract_content(content) -> str:
    """Pull text from content — handles str, list of blocks, or dict."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return " ".join(parts).strip()
    if isinstance(content, dict):
        return content.get("text", "").strip()
    return ""


def _messages_to_transcript(messages: list, spellcheck: bool = True) -> str:
    """Convert [(role, text), ...] to transcript format with > markers."""
    if spellcheck:
        try:
            from mempalace.spellcheck import spellcheck_user_text

            _fix = spellcheck_user_text
        except Exception:
            _fix = None
    else:
        _fix = None

    lines = []
    i = 0
    while i < len(messages):
        role, text = messages[i]
        if role == "user":
            if _fix is not None:
                text = _fix(text)
            lines.append(f"> {text}")
            if i + 1 < len(messages) and messages[i + 1][0] == "assistant":
                lines.append(messages[i + 1][1])
                i += 2
            else:
                i += 1
        else:
            lines.append(text)
            i += 1
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python normalize.py <filepath>")
        sys.exit(1)
    filepath = sys.argv[1]
    result = normalize(filepath)
    quote_count = sum(1 for line in result.split("\n") if line.strip().startswith(">"))
    print(f"\nFile: {os.path.basename(filepath)}")
    print(f"Normalized: {len(result)} chars | {quote_count} user turns detected")
    print("\n--- Preview (first 20 lines) ---")
    print("\n".join(result.split("\n")[:20]))

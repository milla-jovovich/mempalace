import json
import re
from typing import Optional


def normalize(file_path: str) -> Optional[str]:
    """Normalize various conversation export formats into a consistent markdown transcript.

    Supported formats:
    - Claude Code JSONL (session transcripts)
    - Claude.ai JSON exports
    - ChatGPT JSON exports
    - Slack JSON exports (one-to-one or channel)
    - Gemini session JSON
    - Plain text (pass-through)
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None

    if not content.strip():
        return None

    # Try JSON formats
    normalized = _try_normalize_json(content)
    if normalized:
        return normalized

    # Try JSONL formats
    normalized = _try_normalize_jsonl(content)
    if normalized:
        return normalized

    # Fallback to plain text
    return content


def _try_normalize_json(content: str) -> Optional[str]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None

    for parser in (_try_claude_ai_json, _try_chatgpt_json, _try_slack_json, _try_gemini_json):
        normalized = parser(data)
        if normalized:
            return normalized
    return None


def _try_normalize_jsonl(content: str) -> Optional[str]:
    lines = content.strip().split("\n")
    if not lines:
        return None

    # Try Claude Code format: {"message": {"role": "...", "content": "..."}}
    # or {"message": {"role": "...", "parts": [{"text": "..."}]}} (Qwen variant)
    transcript_messages = []
    try:
        for line in lines:
            if not line.strip():
                continue
            entry = json.loads(line)
            msg = entry.get("message")
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue

            # Standard Claude Code
            text = msg.get("content", "")
            if isinstance(text, list):
                text = " ".join(block.get("text", "") for block in text if isinstance(block, dict))

            # Qwen parts variant
            if not text:
                parts = msg.get("parts", [])
                if isinstance(parts, list):
                    text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict))

            if text:
                transcript_messages.append(f"> {role.upper()}: {text}")

        if transcript_messages:
            return "\n\n".join(transcript_messages)
    except (json.JSONDecodeError, KeyError, AttributeError):
        pass

    return None


def _try_claude_ai_json(data: dict) -> Optional[str]:
    """Claude.ai JSON export format (typically via browser console or extensions)."""
    messages = data.get("messages", [])
    if not messages or not isinstance(messages, list):
        return None

    transcript_messages = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = "user" if msg.get("sender") == "human" else "assistant"
        text = msg.get("text", "")
        if text:
            transcript_messages.append(f"> {role.upper()}: {text}")

    if transcript_messages:
        return "\n\n".join(transcript_messages)
    return None


def _try_chatgpt_json(data: dict) -> Optional[str]:
    """ChatGPT JSON export format."""
    mapping = data.get("mapping", {})
    if not mapping or not isinstance(mapping, dict):
        return None

    transcript_messages = []
    # Sort by creation time if available, or follow the linked list
    try:
        # Simplistic: just find all messages and join them
        for node in mapping.values():
            msg = node.get("message")
            if not msg:
                continue
            author = msg.get("author", {})
            role = author.get("role")
            if role not in ("user", "assistant"):
                continue
            content = msg.get("content", {})
            parts = content.get("parts", [])
            text = " ".join(part for part in parts if isinstance(part, str))
            if text:
                # Store with timestamp for sorting
                transcript_messages.append((msg.get("create_time") or 0, role, text))

        if transcript_messages:
            transcript_messages.sort(key=lambda x: x[0])
            return "\n\n".join(f"> {m[1].upper()}: {m[2]}" for m in transcript_messages)
    except (KeyError, AttributeError):
        pass
    return None


def _try_slack_json(data: list) -> Optional[str]:
    """Slack JSON export format (list of messages)."""
    if not isinstance(data, list):
        return None

    transcript_messages = []
    for msg in data:
        if not isinstance(msg, dict):
            continue
        # Skip bot messages that aren't assistants if we want to be strict,
        # but for now just take everything that looks like a message.
        role = "user" if "user" in msg else "assistant"
        text = msg.get("text", "")
        if text:
            # Strip Slack user IDs/mentions like <@U12345>
            text = re.sub(r"<@[A-Z0-9]+>", "User", text)
            transcript_messages.append(f"> {role.upper()}: {text}")

    if transcript_messages:
        return "\n\n".join(transcript_messages)
    return None


def _try_gemini_json(data: dict) -> Optional[str]:
    """Gemini CLI session JSON format.

    Schema: {
        "sessionId": "...",
        "projectHash": "...",
        "startTime": "...",
        "lastUpdated": "...",
        "messages": [
            {"id": "...", "timestamp": "...", "type": "user", "content": [{"text": "..."}]},
            {"id": "...", "timestamp": "...", "type": "model", "content": [{"text": "..."}]},
        ],
        "kind": "session"
    }
    """
    messages = data.get("messages", [])
    if not messages or not isinstance(messages, list):
        return None

    transcript_messages = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        msg_type = msg.get("type", "")
        if msg_type not in ("user", "model"):
            continue
        role = "user" if msg_type == "user" else "assistant"
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        text = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
        if text:
            transcript_messages.append(f"> {role.upper()}: {text}")

    if transcript_messages:
        return "\n\n".join(transcript_messages)
    return None

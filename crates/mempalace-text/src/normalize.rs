//! Chat format normalizer (6 formats). Port of Python mempalace/normalize.py.

use serde_json::Value;
use std::path::Path;
use thiserror::Error;

/// Errors from the normalize module.
#[derive(Debug, Error)]
pub enum NormalizeError {
    /// File could not be read (OS error or permissions).
    #[error("Could not read {0}: {1}")]
    Io(String, String),
    /// File exceeds the 500 MB safety limit.
    #[error("File too large ({0} MB): {1}")]
    TooLarge(u64, String),
}

/// Load a file and normalize to transcript format if it's a chat export.
/// Plain text files pass through unchanged.
pub fn normalize(filepath: &Path) -> Result<String, NormalizeError> {
    normalize_impl(filepath, None)
}

/// Internal implementation with optional size override for testing.
/// When `mock_size` is `Some(n)`, the real `fs::metadata` call is skipped.
pub(crate) fn normalize_impl(
    filepath: &Path,
    mock_size: Option<u64>,
) -> Result<String, NormalizeError> {
    let path_str = filepath.display().to_string();

    let file_size = if let Some(size) = mock_size {
        size
    } else {
        std::fs::metadata(filepath)
            .map_err(|e| NormalizeError::Io(path_str.clone(), e.to_string()))?
            .len()
    };

    if file_size > 500 * 1024 * 1024 {
        return Err(NormalizeError::TooLarge(
            file_size / (1024 * 1024),
            path_str,
        ));
    }

    let bytes =
        std::fs::read(filepath).map_err(|e| NormalizeError::Io(path_str.clone(), e.to_string()))?;
    let content = String::from_utf8_lossy(&bytes).into_owned();

    if content.trim().is_empty() {
        return Ok(content);
    }

    // Already has > markers — pass through
    let lines: Vec<&str> = content.split('\n').collect();
    let marker_count = lines.iter().filter(|l| l.trim().starts_with('>')).count();
    if marker_count >= 3 {
        return Ok(content);
    }

    // Try JSON normalization if extension or content suggests JSON
    let ext = filepath
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_lowercase();
    let first_char = content.trim().chars().next().unwrap_or(' ');
    if ext == "json" || ext == "jsonl" || first_char == '{' || first_char == '[' {
        if let Some(normalized) = try_normalize_json(&content) {
            return Ok(normalized);
        }
    }

    Ok(content)
}

/// Try all known JSON chat schemas.
pub(crate) fn try_normalize_json(content: &str) -> Option<String> {
    // Try JSONL formats first (before full JSON parse)
    if let Some(result) = try_claude_code_jsonl(content) {
        return Some(result);
    }
    if let Some(result) = try_codex_jsonl(content) {
        return Some(result);
    }

    // Try full JSON parse
    let data: Value = serde_json::from_str(content).ok()?;

    for parser in &[
        try_claude_ai_json as fn(&Value) -> Option<String>,
        try_chatgpt_json,
        try_slack_json,
    ] {
        if let Some(result) = parser(&data) {
            return Some(result);
        }
    }

    None
}

/// Claude Code JSONL sessions.
pub(crate) fn try_claude_code_jsonl(content: &str) -> Option<String> {
    let mut messages: Vec<(String, String)> = Vec::new();

    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let entry: Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        let obj = match entry.as_object() {
            Some(o) => o,
            None => continue,
        };

        let msg_type = obj.get("type").and_then(|v| v.as_str()).unwrap_or("");
        let message = obj.get("message").cloned().unwrap_or(Value::Null);

        if msg_type == "human" || msg_type == "user" {
            let content_val = message
                .get("content")
                .cloned()
                .unwrap_or(Value::String(String::new()));
            let text = extract_content(&content_val);
            if !text.is_empty() {
                messages.push(("user".to_string(), text));
            }
        } else if msg_type == "assistant" {
            let content_val = message
                .get("content")
                .cloned()
                .unwrap_or(Value::String(String::new()));
            let text = extract_content(&content_val);
            if !text.is_empty() {
                messages.push(("assistant".to_string(), text));
            }
        }
    }

    if messages.len() >= 2 {
        let refs: Vec<(&str, &str)> = messages
            .iter()
            .map(|(r, t)| (r.as_str(), t.as_str()))
            .collect();
        Some(messages_to_transcript(&refs, true))
    } else {
        None
    }
}

/// OpenAI Codex CLI sessions.
pub(crate) fn try_codex_jsonl(content: &str) -> Option<String> {
    let mut messages: Vec<(String, String)> = Vec::new();
    let mut has_session_meta = false;

    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let entry: Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        let obj = match entry.as_object() {
            Some(o) => o,
            None => continue,
        };

        let entry_type = obj.get("type").and_then(|v| v.as_str()).unwrap_or("");

        if entry_type == "session_meta" {
            has_session_meta = true;
            continue;
        }
        if entry_type != "event_msg" {
            continue;
        }

        let payload = match obj.get("payload").and_then(|v| v.as_object()) {
            Some(p) => p,
            None => continue,
        };

        let payload_type = payload.get("type").and_then(|v| v.as_str()).unwrap_or("");
        let msg = match payload.get("message").and_then(|v| v.as_str()) {
            Some(s) => s,
            None => continue,
        };
        let text = msg.trim();
        if text.is_empty() {
            continue;
        }

        if payload_type == "user_message" {
            messages.push(("user".to_string(), text.to_string()));
        } else if payload_type == "agent_message" {
            messages.push(("assistant".to_string(), text.to_string()));
        }
    }

    if messages.len() >= 2 && has_session_meta {
        let refs: Vec<(&str, &str)> = messages
            .iter()
            .map(|(r, t)| (r.as_str(), t.as_str()))
            .collect();
        Some(messages_to_transcript(&refs, true))
    } else {
        None
    }
}

/// Claude.ai JSON export: flat messages list or privacy export with chat_messages.
pub(crate) fn try_claude_ai_json(data: &Value) -> Option<String> {
    // Normalize: if data is a dict, extract messages or chat_messages
    let list = if let Some(obj) = data.as_object() {
        if let Some(msgs) = obj.get("messages") {
            msgs
        } else if let Some(chat) = obj.get("chat_messages") {
            chat
        } else {
            return None;
        }
    } else {
        data
    };

    let arr = list.as_array()?;

    // Privacy export: array of conversation objects with chat_messages inside each
    if arr
        .first()
        .and_then(|v| v.as_object())
        .map_or(false, |o| o.contains_key("chat_messages"))
    {
        let mut all_messages: Vec<(String, String)> = Vec::new();
        for convo in arr {
            let convo_obj = match convo.as_object() {
                Some(o) => o,
                None => continue,
            };
            let chat_msgs = match convo_obj.get("chat_messages").and_then(|v| v.as_array()) {
                Some(a) => a,
                None => continue,
            };
            for item in chat_msgs {
                let item_obj = match item.as_object() {
                    Some(o) => o,
                    None => continue,
                };
                let role = item_obj.get("role").and_then(|v| v.as_str()).unwrap_or("");
                let content_val = item_obj.get("content").cloned().unwrap_or(Value::Null);
                let text = extract_content(&content_val);
                if (role == "user" || role == "human") && !text.is_empty() {
                    all_messages.push(("user".to_string(), text));
                } else if (role == "assistant" || role == "ai") && !text.is_empty() {
                    all_messages.push(("assistant".to_string(), text));
                }
            }
        }
        if all_messages.len() >= 2 {
            let refs: Vec<(&str, &str)> = all_messages
                .iter()
                .map(|(r, t)| (r.as_str(), t.as_str()))
                .collect();
            return Some(messages_to_transcript(&refs, true));
        }
        return None;
    }

    // Flat messages list
    let mut messages: Vec<(String, String)> = Vec::new();
    for item in arr {
        let item_obj = match item.as_object() {
            Some(o) => o,
            None => continue,
        };
        let role = item_obj.get("role").and_then(|v| v.as_str()).unwrap_or("");
        let content_val = item_obj.get("content").cloned().unwrap_or(Value::Null);
        let text = extract_content(&content_val);
        if (role == "user" || role == "human") && !text.is_empty() {
            messages.push(("user".to_string(), text));
        } else if (role == "assistant" || role == "ai") && !text.is_empty() {
            messages.push(("assistant".to_string(), text));
        }
    }
    if messages.len() >= 2 {
        let refs: Vec<(&str, &str)> = messages
            .iter()
            .map(|(r, t)| (r.as_str(), t.as_str()))
            .collect();
        Some(messages_to_transcript(&refs, true))
    } else {
        None
    }
}

/// ChatGPT conversations.json with mapping tree.
pub(crate) fn try_chatgpt_json(data: &Value) -> Option<String> {
    let obj = data.as_object()?;
    let mapping = obj.get("mapping")?.as_object()?;
    let mut messages: Vec<(String, String)> = Vec::new();

    // Find root: prefer node with parent=None AND message=None (synthetic root)
    let mut root_id: Option<String> = None;
    let mut fallback_root: Option<String> = None;

    for (node_id, node) in mapping {
        let node_obj = match node.as_object() {
            Some(o) => o,
            None => continue,
        };
        // parent must be JSON null
        if node_obj.get("parent").map_or(false, |v| v.is_null()) {
            if node_obj.get("message").map_or(true, |v| v.is_null()) {
                root_id = Some(node_id.clone());
                break;
            } else if fallback_root.is_none() {
                fallback_root = Some(node_id.clone());
            }
        }
    }

    let start_id = root_id.or(fallback_root)?;
    let mut current_id = start_id;
    let mut visited = std::collections::HashSet::new();

    loop {
        if visited.contains(&current_id) {
            break;
        }
        visited.insert(current_id.clone());

        let node = match mapping.get(&current_id).and_then(|v| v.as_object()) {
            Some(o) => o,
            None => break,
        };

        if let Some(msg) = node.get("message").and_then(|v| v.as_object()) {
            let role = msg
                .get("author")
                .and_then(|a| a.as_object())
                .and_then(|a| a.get("role"))
                .and_then(|r| r.as_str())
                .unwrap_or("");
            let content = msg.get("content").cloned().unwrap_or(Value::Null);
            let parts: &[Value] = content
                .as_object()
                .and_then(|o| o.get("parts"))
                .and_then(|p| p.as_array())
                .map(|a| a.as_slice())
                .unwrap_or(&[]);
            let text: String = parts
                .iter()
                .filter_map(|p| p.as_str())
                .filter(|s| !s.is_empty())
                .collect::<Vec<_>>()
                .join(" ");
            let text = text.trim().to_string();

            if role == "user" && !text.is_empty() {
                messages.push(("user".to_string(), text));
            } else if role == "assistant" && !text.is_empty() {
                messages.push(("assistant".to_string(), text));
            }
        }

        let children = node
            .get("children")
            .and_then(|c| c.as_array())
            .map(|a| a.as_slice())
            .unwrap_or(&[]);
        if let Some(next) = children.first().and_then(|v| v.as_str()) {
            current_id = next.to_string();
        } else {
            break;
        }
    }

    if messages.len() >= 2 {
        let refs: Vec<(&str, &str)> = messages
            .iter()
            .map(|(r, t)| (r.as_str(), t.as_str()))
            .collect();
        Some(messages_to_transcript(&refs, true))
    } else {
        None
    }
}

/// Slack channel export.
pub(crate) fn try_slack_json(data: &Value) -> Option<String> {
    let arr = data.as_array()?;
    let mut messages: Vec<(String, String)> = Vec::new();
    let mut seen_users: std::collections::HashMap<String, String> =
        std::collections::HashMap::new();
    let mut last_role: Option<String> = None;

    for item in arr {
        let obj = match item.as_object() {
            Some(o) => o,
            None => continue,
        };
        if obj.get("type").and_then(|v| v.as_str()) != Some("message") {
            continue;
        }
        let user_id = obj
            .get("user")
            .or_else(|| obj.get("username"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let text = obj
            .get("text")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        if text.is_empty() || user_id.is_empty() {
            continue;
        }

        if !seen_users.contains_key(&user_id) {
            let role = if seen_users.is_empty() {
                "user".to_string()
            } else if last_role.as_deref() == Some("user") {
                "assistant".to_string()
            } else {
                "user".to_string()
            };
            seen_users.insert(user_id.clone(), role);
        }
        let role = seen_users[&user_id].clone();
        last_role = Some(role.clone());
        messages.push((role, text));
    }

    if messages.len() >= 2 {
        let refs: Vec<(&str, &str)> = messages
            .iter()
            .map(|(r, t)| (r.as_str(), t.as_str()))
            .collect();
        Some(messages_to_transcript(&refs, true))
    } else {
        None
    }
}

/// Pull text from content — handles str, list of blocks, or dict.
pub(crate) fn extract_content(content: &Value) -> String {
    match content {
        Value::String(s) => s.trim().to_string(),
        Value::Array(arr) => {
            let parts: Vec<String> = arr
                .iter()
                .filter_map(|item| match item {
                    Value::String(s) => Some(s.clone()),
                    Value::Object(obj)
                        if obj.get("type").and_then(|v| v.as_str()) == Some("text") =>
                    {
                        obj.get("text")
                            .and_then(|v| v.as_str())
                            .map(|s| s.to_string())
                    }
                    _ => None,
                })
                .collect();
            parts.join(" ").trim().to_string()
        }
        Value::Object(obj) => obj
            .get("text")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string(),
        _ => String::new(),
    }
}

/// Convert `[(role, text), ...]` to transcript format with `>` markers.
/// When `apply_spellcheck` is true, user text is passed through the spellcheck
/// module (which is identity when no autocorrect library is installed).
pub(crate) fn messages_to_transcript(messages: &[(&str, &str)], apply_spellcheck: bool) -> String {
    let mut lines: Vec<String> = Vec::new();
    let mut i = 0;

    while i < messages.len() {
        let (role, text) = messages[i];
        if role == "user" {
            let text_out = if apply_spellcheck {
                crate::spellcheck::spellcheck_user_text(text, None)
            } else {
                text.to_string()
            };
            lines.push(format!("> {text_out}"));
            if i + 1 < messages.len() && messages[i + 1].0 == "assistant" {
                lines.push(messages[i + 1].1.to_string());
                i += 2;
            } else {
                i += 1;
            }
        } else {
            lines.push(text.to_string());
            i += 1;
        }
        lines.push(String::new());
    }

    lines.join("\n")
}

// ─────────────────────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]

    use super::*;
    use serde_json::json;

    // ── normalize() top-level ──────────────────────────────────────────────

    #[test]
    fn test_plain_text() {
        let tmp = tempfile::tempdir().unwrap();
        let f = tmp.path().join("plain.txt");
        std::fs::write(&f, "Hello world\nSecond line\n").unwrap();
        let result = normalize(&f).unwrap();
        assert!(result.contains("Hello world"));
    }

    #[test]
    fn test_claude_json() {
        let tmp = tempfile::tempdir().unwrap();
        let data =
            json!([{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]);
        let f = tmp.path().join("claude.json");
        std::fs::write(&f, data.to_string()).unwrap();
        let result = normalize(&f).unwrap();
        assert!(result.contains("Hi"));
    }

    #[test]
    fn test_empty() {
        let tmp = tempfile::tempdir().unwrap();
        let f = tmp.path().join("empty.txt");
        std::fs::write(&f, "").unwrap();
        let result = normalize(&f).unwrap();
        assert!(result.trim().is_empty());
    }

    #[test]
    fn test_normalize_io_error() {
        let result = normalize(std::path::Path::new("/nonexistent/path/file.txt"));
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("Could not read"));
    }

    #[test]
    fn test_normalize_already_has_markers() {
        let tmp = tempfile::tempdir().unwrap();
        let content = "> question 1\nanswer 1\n> question 2\nanswer 2\n> question 3\nanswer 3\n";
        let f = tmp.path().join("markers.txt");
        std::fs::write(&f, content).unwrap();
        let result = normalize(&f).unwrap();
        assert_eq!(result, content);
    }

    #[test]
    fn test_normalize_json_content_detected_by_brace() {
        let tmp = tempfile::tempdir().unwrap();
        let data = json!([{"role": "user", "content": "Hey"}, {"role": "assistant", "content": "Hi there"}]);
        let f = tmp.path().join("chat.txt");
        std::fs::write(&f, data.to_string()).unwrap();
        let result = normalize(&f).unwrap();
        assert!(result.contains("Hey"));
    }

    #[test]
    fn test_normalize_whitespace_only() {
        let tmp = tempfile::tempdir().unwrap();
        let f = tmp.path().join("ws.txt");
        std::fs::write(&f, "   \n  \n  ").unwrap();
        let result = normalize(&f).unwrap();
        assert!(result.trim().is_empty());
    }

    #[test]
    fn test_normalize_rejects_large_file() {
        // Use mock_size to simulate a 600 MB file without needing a real file
        let result = normalize_impl(
            std::path::Path::new("/fake/huge_file.txt"),
            Some(600 * 1024 * 1024),
        );
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .to_lowercase()
            .contains("too large"));
    }

    // ── _extract_content ───────────────────────────────────────────────────

    #[test]
    fn test_extract_content_string() {
        assert_eq!(extract_content(&json!("hello")), "hello");
    }

    #[test]
    fn test_extract_content_list_of_strings() {
        assert_eq!(extract_content(&json!(["hello", "world"])), "hello world");
    }

    #[test]
    fn test_extract_content_list_of_blocks() {
        let blocks = json!([{"type": "text", "text": "hello"}, {"type": "image", "url": "x"}]);
        assert_eq!(extract_content(&blocks), "hello");
    }

    #[test]
    fn test_extract_content_dict() {
        assert_eq!(extract_content(&json!({"text": "hello"})), "hello");
    }

    #[test]
    fn test_extract_content_none() {
        assert_eq!(extract_content(&Value::Null), "");
    }

    #[test]
    fn test_extract_content_mixed_list() {
        let blocks = json!(["plain", {"type": "text", "text": "block"}]);
        assert_eq!(extract_content(&blocks), "plain block");
    }

    // ── _try_claude_code_jsonl ─────────────────────────────────────────────

    #[test]
    fn test_claude_code_jsonl_valid() {
        let lines = vec![
            json!({"type": "human", "message": {"content": "What is X?"}}).to_string(),
            json!({"type": "assistant", "message": {"content": "X is Y."}}).to_string(),
        ];
        let result = try_claude_code_jsonl(&lines.join("\n"));
        assert!(result.is_some());
        let r = result.unwrap();
        assert!(r.contains("> What is X?"));
        assert!(r.contains("X is Y."));
    }

    #[test]
    fn test_claude_code_jsonl_user_type() {
        let lines = vec![
            json!({"type": "user", "message": {"content": "Q"}}).to_string(),
            json!({"type": "assistant", "message": {"content": "A"}}).to_string(),
        ];
        let result = try_claude_code_jsonl(&lines.join("\n"));
        assert!(result.is_some());
        assert!(result.unwrap().contains("> Q"));
    }

    #[test]
    fn test_claude_code_jsonl_too_few_messages() {
        let lines = vec![json!({"type": "human", "message": {"content": "only one"}}).to_string()];
        let result = try_claude_code_jsonl(&lines.join("\n"));
        assert!(result.is_none());
    }

    #[test]
    fn test_claude_code_jsonl_invalid_json_lines() {
        let lines = vec![
            "not json".to_string(),
            json!({"type": "human", "message": {"content": "Q"}}).to_string(),
            json!({"type": "assistant", "message": {"content": "A"}}).to_string(),
        ];
        let result = try_claude_code_jsonl(&lines.join("\n"));
        assert!(result.is_some());
    }

    #[test]
    fn test_claude_code_jsonl_non_dict_entries() {
        let lines = vec![
            json!([1, 2, 3]).to_string(),
            json!({"type": "human", "message": {"content": "Q"}}).to_string(),
            json!({"type": "assistant", "message": {"content": "A"}}).to_string(),
        ];
        let result = try_claude_code_jsonl(&lines.join("\n"));
        assert!(result.is_some());
    }

    // ── _try_codex_jsonl ───────────────────────────────────────────────────

    #[test]
    fn test_codex_jsonl_valid() {
        let lines = vec![
            json!({"type": "session_meta", "payload": {}}).to_string(),
            json!({"type": "event_msg", "payload": {"type": "user_message", "message": "Q"}})
                .to_string(),
            json!({"type": "event_msg", "payload": {"type": "agent_message", "message": "A"}})
                .to_string(),
        ];
        let result = try_codex_jsonl(&lines.join("\n"));
        assert!(result.is_some());
        assert!(result.unwrap().contains("> Q"));
    }

    #[test]
    fn test_codex_jsonl_no_session_meta() {
        let lines = vec![
            json!({"type": "event_msg", "payload": {"type": "user_message", "message": "Q"}})
                .to_string(),
            json!({"type": "event_msg", "payload": {"type": "agent_message", "message": "A"}})
                .to_string(),
        ];
        let result = try_codex_jsonl(&lines.join("\n"));
        assert!(result.is_none());
    }

    #[test]
    fn test_codex_jsonl_skips_non_event_msg() {
        let lines = vec![
            json!({"type": "session_meta"}).to_string(),
            json!({"type": "response_item", "payload": {"type": "user_message", "message": "X"}})
                .to_string(),
            json!({"type": "event_msg", "payload": {"type": "user_message", "message": "Q"}})
                .to_string(),
            json!({"type": "event_msg", "payload": {"type": "agent_message", "message": "A"}})
                .to_string(),
        ];
        let result = try_codex_jsonl(&lines.join("\n"));
        assert!(result.is_some());
        let r = result.unwrap();
        // "X" should not appear before "> Q"
        let before_q = r.split("> Q").next().unwrap_or("");
        assert!(!before_q.contains('X'));
    }

    #[test]
    fn test_codex_jsonl_non_string_message() {
        let lines = vec![
            json!({"type": "session_meta"}).to_string(),
            json!({"type": "event_msg", "payload": {"type": "user_message", "message": 123}})
                .to_string(),
            json!({"type": "event_msg", "payload": {"type": "user_message", "message": "Q"}})
                .to_string(),
            json!({"type": "event_msg", "payload": {"type": "agent_message", "message": "A"}})
                .to_string(),
        ];
        let result = try_codex_jsonl(&lines.join("\n"));
        assert!(result.is_some());
    }

    #[test]
    fn test_codex_jsonl_empty_text_skipped() {
        let lines = vec![
            json!({"type": "session_meta"}).to_string(),
            json!({"type": "event_msg", "payload": {"type": "user_message", "message": "  "}})
                .to_string(),
            json!({"type": "event_msg", "payload": {"type": "user_message", "message": "Q"}})
                .to_string(),
            json!({"type": "event_msg", "payload": {"type": "agent_message", "message": "A"}})
                .to_string(),
        ];
        let result = try_codex_jsonl(&lines.join("\n"));
        assert!(result.is_some());
    }

    #[test]
    fn test_codex_jsonl_payload_not_dict() {
        let lines = vec![
            json!({"type": "session_meta"}).to_string(),
            json!({"type": "event_msg", "payload": "not a dict"}).to_string(),
            json!({"type": "event_msg", "payload": {"type": "user_message", "message": "Q"}})
                .to_string(),
            json!({"type": "event_msg", "payload": {"type": "agent_message", "message": "A"}})
                .to_string(),
        ];
        let result = try_codex_jsonl(&lines.join("\n"));
        assert!(result.is_some());
    }

    // ── _try_claude_ai_json ───────────────────────────────────────────────

    #[test]
    fn test_claude_ai_flat_messages() {
        let data = json!([
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]);
        let result = try_claude_ai_json(&data);
        assert!(result.is_some());
        assert!(result.unwrap().contains("> Hello"));
    }

    #[test]
    fn test_claude_ai_dict_with_messages_key() {
        let data = json!({
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"}
            ]
        });
        let result = try_claude_ai_json(&data);
        assert!(result.is_some());
    }

    #[test]
    fn test_claude_ai_privacy_export() {
        let data = json!([{
            "chat_messages": [
                {"role": "human", "content": "Q1"},
                {"role": "ai", "content": "A1"}
            ]
        }]);
        let result = try_claude_ai_json(&data);
        assert!(result.is_some());
        assert!(result.unwrap().contains("> Q1"));
    }

    #[test]
    fn test_claude_ai_not_a_list() {
        let result = try_claude_ai_json(&json!("not a list"));
        assert!(result.is_none());
    }

    #[test]
    fn test_claude_ai_too_few_messages() {
        let data = json!([{"role": "user", "content": "Hello"}]);
        let result = try_claude_ai_json(&data);
        assert!(result.is_none());
    }

    #[test]
    fn test_claude_ai_dict_with_chat_messages_key() {
        let data = json!({
            "chat_messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "World"}
            ]
        });
        let result = try_claude_ai_json(&data);
        assert!(result.is_some());
    }

    #[test]
    fn test_claude_ai_privacy_export_non_dict_items() {
        let data = json!([
            {
                "chat_messages": [
                    "not a dict",
                    {"role": "user", "content": "Q"},
                    {"role": "assistant", "content": "A"}
                ]
            },
            "not a convo"
        ]);
        let result = try_claude_ai_json(&data);
        assert!(result.is_some());
    }

    // ── _try_chatgpt_json ─────────────────────────────────────────────────

    #[test]
    fn test_chatgpt_json_valid() {
        let data = json!({
            "mapping": {
                "root": {
                    "parent": null,
                    "message": null,
                    "children": ["msg1"]
                },
                "msg1": {
                    "parent": "root",
                    "message": {
                        "author": {"role": "user"},
                        "content": {"parts": ["Hello ChatGPT"]}
                    },
                    "children": ["msg2"]
                },
                "msg2": {
                    "parent": "msg1",
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"parts": ["Hello! How can I help?"]}
                    },
                    "children": []
                }
            }
        });
        let result = try_chatgpt_json(&data);
        assert!(result.is_some());
        assert!(result.unwrap().contains("> Hello ChatGPT"));
    }

    #[test]
    fn test_chatgpt_json_no_mapping() {
        let result = try_chatgpt_json(&json!({"data": []}));
        assert!(result.is_none());
    }

    #[test]
    fn test_chatgpt_json_not_dict() {
        let result = try_chatgpt_json(&json!([1, 2, 3]));
        assert!(result.is_none());
    }

    #[test]
    fn test_chatgpt_json_fallback_root() {
        let data = json!({
            "mapping": {
                "root": {
                    "parent": null,
                    "message": {
                        "author": {"role": "system"},
                        "content": {"parts": ["system prompt"]}
                    },
                    "children": ["msg1"]
                },
                "msg1": {
                    "parent": "root",
                    "message": {
                        "author": {"role": "user"},
                        "content": {"parts": ["Hello"]}
                    },
                    "children": ["msg2"]
                },
                "msg2": {
                    "parent": "msg1",
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"parts": ["Hi there"]}
                    },
                    "children": []
                }
            }
        });
        let result = try_chatgpt_json(&data);
        assert!(result.is_some());
    }

    #[test]
    fn test_chatgpt_json_too_few_messages() {
        let data = json!({
            "mapping": {
                "root": {
                    "parent": null,
                    "message": null,
                    "children": ["msg1"]
                },
                "msg1": {
                    "parent": "root",
                    "message": {
                        "author": {"role": "user"},
                        "content": {"parts": ["Only one"]}
                    },
                    "children": []
                }
            }
        });
        let result = try_chatgpt_json(&data);
        assert!(result.is_none());
    }

    // ── _try_slack_json ────────────────────────────────────────────────────

    #[test]
    fn test_slack_json_valid() {
        let data = json!([
            {"type": "message", "user": "U1", "text": "Hello"},
            {"type": "message", "user": "U2", "text": "Hi there"}
        ]);
        let result = try_slack_json(&data);
        assert!(result.is_some());
        assert!(result.unwrap().contains("Hello"));
    }

    #[test]
    fn test_slack_json_not_a_list() {
        let result = try_slack_json(&json!({"type": "message"}));
        assert!(result.is_none());
    }

    #[test]
    fn test_slack_json_too_few_messages() {
        let data = json!([{"type": "message", "user": "U1", "text": "Hello"}]);
        let result = try_slack_json(&data);
        assert!(result.is_none());
    }

    #[test]
    fn test_slack_json_skips_non_message_types() {
        let data = json!([
            {"type": "channel_join", "user": "U1", "text": "joined"},
            {"type": "message", "user": "U1", "text": "Hello"},
            {"type": "message", "user": "U2", "text": "Hi"}
        ]);
        let result = try_slack_json(&data);
        assert!(result.is_some());
    }

    #[test]
    fn test_slack_json_three_users() {
        let data = json!([
            {"type": "message", "user": "U1", "text": "Hello"},
            {"type": "message", "user": "U2", "text": "Hi"},
            {"type": "message", "user": "U3", "text": "Hey"}
        ]);
        let result = try_slack_json(&data);
        assert!(result.is_some());
    }

    #[test]
    fn test_slack_json_empty_text_skipped() {
        let data = json!([
            {"type": "message", "user": "U1", "text": ""},
            {"type": "message", "user": "U1", "text": "Hello"},
            {"type": "message", "user": "U2", "text": "Hi"}
        ]);
        let result = try_slack_json(&data);
        assert!(result.is_some());
    }

    #[test]
    fn test_slack_json_username_fallback() {
        let data = json!([
            {"type": "message", "username": "bot1", "text": "Hello"},
            {"type": "message", "username": "bot2", "text": "Hi"}
        ]);
        let result = try_slack_json(&data);
        assert!(result.is_some());
    }

    // ── _try_normalize_json ────────────────────────────────────────────────

    #[test]
    fn test_try_normalize_json_invalid_json() {
        let result = try_normalize_json("not json at all {{{");
        assert!(result.is_none());
    }

    #[test]
    fn test_try_normalize_json_valid_but_unknown_schema() {
        let result = try_normalize_json(&json!({"random": "data"}).to_string());
        assert!(result.is_none());
    }

    // ── _messages_to_transcript ────────────────────────────────────────────

    #[test]
    fn test_messages_to_transcript_basic() {
        let msgs = vec![("user", "Q"), ("assistant", "A")];
        let result = messages_to_transcript(&msgs, false);
        assert!(result.contains("> Q"));
        assert!(result.contains('A'));
    }

    #[test]
    fn test_messages_to_transcript_consecutive_users() {
        let msgs = vec![("user", "Q1"), ("user", "Q2"), ("assistant", "A")];
        let result = messages_to_transcript(&msgs, false);
        assert!(result.contains("> Q1"));
        assert!(result.contains("> Q2"));
    }

    #[test]
    fn test_messages_to_transcript_assistant_first() {
        let msgs = vec![("assistant", "preamble"), ("user", "Q"), ("assistant", "A")];
        let result = messages_to_transcript(&msgs, false);
        assert!(result.contains("preamble"));
        assert!(result.contains("> Q"));
    }
}

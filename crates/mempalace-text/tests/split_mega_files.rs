#![allow(clippy::unwrap_used, clippy::expect_used, clippy::format_push_string)]

use std::sync::Mutex;

use mempalace_text::split_mega_files::{
    extract_people, extract_subject, extract_timestamp, find_session_boundaries,
    is_true_session_start, load_known_names_config, load_known_people, load_username_map,
    reset_known_names_cache, set_known_names_path, set_known_people_override, split_file,
    FALLBACK_KNOWN_PEOPLE,
};
use tempfile::TempDir;

static GLOBAL_GUARD: Mutex<()> = Mutex::new(());

fn guard() -> std::sync::MutexGuard<'static, ()> {
    GLOBAL_GUARD
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

fn lines(strs: &[&str]) -> Vec<String> {
    strs.iter().map(|s| (*s).to_string()).collect()
}

// ── Config loading ─────────────────────────────────────────────────────────

#[test]
fn load_known_people_falls_back_when_config_missing() {
    let _g = guard();
    let tmp = TempDir::new().unwrap();
    set_known_names_path(tmp.path().join("missing.json"));
    reset_known_names_cache();
    set_known_people_override(None);

    let fallback: Vec<String> = FALLBACK_KNOWN_PEOPLE
        .iter()
        .map(|s| (*s).to_string())
        .collect();
    assert_eq!(load_known_people(), fallback);
    assert!(load_username_map().is_empty());
}

#[test]
fn load_known_people_from_list_config() {
    let _g = guard();
    let tmp = TempDir::new().unwrap();
    let path = tmp.path().join("known_names.json");
    std::fs::write(&path, r#"["Alice", "Ben"]"#).unwrap();
    set_known_names_path(path);
    reset_known_names_cache();
    set_known_people_override(None);

    assert_eq!(
        load_known_people(),
        vec!["Alice".to_string(), "Ben".to_string()]
    );
    assert!(load_username_map().is_empty());
}

#[test]
fn load_known_people_from_dict_config() {
    let _g = guard();
    let tmp = TempDir::new().unwrap();
    let path = tmp.path().join("known_names.json");
    std::fs::write(
        &path,
        r#"{"names": ["Alice"], "username_map": {"jdoe": "John"}}"#,
    )
    .unwrap();
    set_known_names_path(path);
    reset_known_names_cache();
    set_known_people_override(None);

    assert_eq!(load_known_people(), vec!["Alice".to_string()]);
    let um = load_username_map();
    assert_eq!(um.get("jdoe"), Some(&"John".to_string()));
}

#[test]
fn extract_people_uses_username_map() {
    let _g = guard();
    let tmp = TempDir::new().unwrap();
    let path = tmp.path().join("known_names.json");
    std::fs::write(
        &path,
        r#"{"names": ["Alice"], "username_map": {"jdoe": "John"}}"#,
    )
    .unwrap();
    set_known_names_path(path);
    reset_known_names_cache();
    set_known_people_override(Some(vec!["Alice".to_string()]));

    let people = extract_people(&lines(&["Working in /Users/jdoe/project\n"]));
    assert!(people.contains(&"John".to_string()));
    set_known_people_override(None);
}

#[test]
fn extract_people_detects_names_from_content() {
    let _g = guard();
    set_known_people_override(Some(vec!["Alice".to_string(), "Ben".to_string()]));
    let people = extract_people(&lines(&["> Alice reviewed the change with Ben\n"]));
    assert_eq!(people, vec!["Alice".to_string(), "Ben".to_string()]);
    set_known_people_override(None);
}

// ── force_reload + invalid json ────────────────────────────────────────────

#[test]
fn load_known_names_force_reload() {
    let _g = guard();
    let tmp = TempDir::new().unwrap();
    let path = tmp.path().join("known_names.json");
    std::fs::write(&path, r#"["Alice"]"#).unwrap();
    set_known_names_path(path.clone());
    reset_known_names_cache();

    let first = load_known_names_config(false);
    assert!(first.is_some());
    assert_eq!(
        first.unwrap().as_array().unwrap()[0].as_str().unwrap(),
        "Alice"
    );

    std::fs::write(&path, r#"["Bob"]"#).unwrap();
    let reloaded = load_known_names_config(true);
    assert!(reloaded.is_some());
    assert_eq!(
        reloaded.unwrap().as_array().unwrap()[0].as_str().unwrap(),
        "Bob"
    );
}

#[test]
fn load_known_names_invalid_json() {
    let _g = guard();
    let tmp = TempDir::new().unwrap();
    let path = tmp.path().join("known_names.json");
    std::fs::write(&path, "not json {{{").unwrap();
    set_known_names_path(path);
    reset_known_names_cache();

    let result = load_known_names_config(false);
    assert!(result.is_none());
}

#[test]
fn load_known_names_caching() {
    let _g = guard();
    let tmp = TempDir::new().unwrap();
    let path = tmp.path().join("known_names.json");
    std::fs::write(&path, r#"["Alice"]"#).unwrap();
    set_known_names_path(path.clone());
    reset_known_names_cache();

    let _first = load_known_names_config(false);
    std::fs::write(&path, r#"["Changed"]"#).unwrap();
    let second = load_known_names_config(false);
    assert_eq!(
        second.unwrap().as_array().unwrap()[0].as_str().unwrap(),
        "Alice"
    );
}

// ── is_true_session_start ──────────────────────────────────────────────────

#[test]
fn is_true_session_start_yes() {
    let ls = lines(&[
        "Claude Code v1.0",
        "Some content",
        "More content",
        "",
        "",
        "",
    ]);
    assert!(is_true_session_start(&ls, 0));
}

#[test]
fn is_true_session_start_no_ctrl_e() {
    let ls = lines(&[
        "Claude Code v1.0",
        "Ctrl+E to show 5 previous messages",
        "",
        "",
        "",
        "",
    ]);
    assert!(!is_true_session_start(&ls, 0));
}

#[test]
fn is_true_session_start_no_previous_messages() {
    let ls = lines(&[
        "Claude Code v1.0",
        "Some text",
        "previous messages here",
        "",
        "",
        "",
    ]);
    assert!(!is_true_session_start(&ls, 0));
}

// ── find_session_boundaries ────────────────────────────────────────────────

#[test]
fn find_session_boundaries_two_sessions() {
    let ls = lines(&[
        "Claude Code v1.0",
        "content 1",
        "",
        "",
        "",
        "",
        "",
        "Claude Code v1.0",
        "content 2",
        "",
        "",
        "",
        "",
        "",
    ]);
    let boundaries = find_session_boundaries(&ls);
    assert_eq!(boundaries, vec![0, 7]);
}

#[test]
fn find_session_boundaries_none() {
    let ls = lines(&["Just some text", "No sessions here"]);
    assert_eq!(find_session_boundaries(&ls), Vec::<usize>::new());
}

#[test]
fn find_session_boundaries_context_restore_skipped() {
    let ls = lines(&[
        "Claude Code v1.0",
        "content",
        "",
        "",
        "",
        "",
        "",
        "Claude Code v1.0",
        "Ctrl+E to show 5 previous messages",
        "",
        "",
        "",
        "",
    ]);
    let boundaries = find_session_boundaries(&ls);
    assert_eq!(boundaries.len(), 1);
}

// ── extract_timestamp ──────────────────────────────────────────────────────

#[test]
fn extract_timestamp_found() {
    let ls = lines(&["⏺ 2:30 PM Wednesday, March 25, 2026"]);
    let (human, iso) = extract_timestamp(&ls);
    assert_eq!(human.as_deref(), Some("2026-03-25_230PM"));
    assert_eq!(iso.as_deref(), Some("2026-03-25"));
}

#[test]
fn extract_timestamp_not_found() {
    let ls = lines(&["No timestamp here"]);
    let (human, iso) = extract_timestamp(&ls);
    assert!(human.is_none());
    assert!(iso.is_none());
}

#[test]
fn extract_timestamp_only_checks_first_50() {
    let mut ls: Vec<String> = (0..51).map(|_| "filler\n".to_string()).collect();
    ls.push("⏺ 1:00 AM Monday, January 01, 2026".to_string());
    let (human, _) = extract_timestamp(&ls);
    assert!(human.is_none());
}

// ── extract_subject ────────────────────────────────────────────────────────

#[test]
fn extract_subject_found() {
    let ls = lines(&["> How do we handle authentication?"]);
    let subject = extract_subject(&ls);
    assert!(subject.to_lowercase().contains("authentication"));
}

#[test]
fn extract_subject_skips_commands() {
    let ls = lines(&["> cd /some/dir", "> git status", "> What is the plan?"]);
    let subject = extract_subject(&ls);
    assert!(subject.to_lowercase().contains("plan"));
}

#[test]
fn extract_subject_fallback() {
    let ls = lines(&["No prompts at all", "Just text"]);
    assert_eq!(extract_subject(&ls), "session");
}

#[test]
fn extract_subject_short_prompt_skipped() {
    let ls = lines(&["> ok", "> yes", "> What about the deployment strategy?"]);
    let subject = extract_subject(&ls);
    assert!(subject.to_lowercase().contains("deployment"));
}

#[test]
fn extract_subject_truncated() {
    let ls = lines(&[&format!("> {}", "a".repeat(100))]);
    let subject = extract_subject(&ls);
    assert!(subject.len() <= 60);
}

// ── split_file ─────────────────────────────────────────────────────────────

fn make_mega_file(
    dir: &std::path::Path,
    n_sessions: usize,
    lines_per_session: usize,
) -> std::path::PathBuf {
    let mut content = String::new();
    for i in 0..n_sessions {
        content.push_str(&format!("Claude Code v1.{i}\n"));
        content.push_str(&format!("> What about topic {i} and how it works?\n"));
        for j in 0..(lines_per_session - 2) {
            content.push_str(&format!("Line {j} of session {i}\n"));
        }
    }
    let path = dir.join("mega.txt");
    std::fs::write(&path, content).unwrap();
    path
}

#[test]
fn split_file_creates_output() {
    let _g = guard();
    let tmp = TempDir::new().unwrap();
    let mega = make_mega_file(tmp.path(), 3, 15);
    let out_dir = tmp.path().join("output");
    std::fs::create_dir_all(&out_dir).unwrap();
    let written = split_file(&mega, Some(&out_dir), false).unwrap();
    assert!(written.len() >= 2);
    for p in &written {
        assert!(p.exists(), "{} should exist", p.display());
    }
}

#[test]
fn split_file_dry_run() {
    let _g = guard();
    let tmp = TempDir::new().unwrap();
    let mega = make_mega_file(tmp.path(), 3, 15);
    let out_dir = tmp.path().join("output");
    std::fs::create_dir_all(&out_dir).unwrap();
    let written = split_file(&mega, Some(&out_dir), true).unwrap();
    assert!(written.len() >= 2);
    for p in &written {
        assert!(!p.exists(), "{} should NOT exist", p.display());
    }
}

#[test]
fn split_file_not_mega() {
    let _g = guard();
    let tmp = TempDir::new().unwrap();
    let path = tmp.path().join("single.txt");
    let mut content = String::from("Claude Code v1.0\nJust one session\n");
    for _ in 0..20 {
        content.push_str("line\n");
    }
    std::fs::write(&path, content).unwrap();
    let written = split_file(&path, Some(tmp.path()), false).unwrap();
    assert!(written.is_empty());
}

#[test]
fn split_file_output_dir_none() {
    let _g = guard();
    let tmp = TempDir::new().unwrap();
    let mega = make_mega_file(tmp.path(), 3, 15);
    let written = split_file(&mega, None, false).unwrap();
    assert!(written.len() >= 2);
    for p in &written {
        assert_eq!(p.parent(), Some(tmp.path()));
    }
}

#[test]
fn split_file_tiny_fragments_skipped() {
    let _g = guard();
    let tmp = TempDir::new().unwrap();
    let mut content = String::new();
    for _ in 0..2 {
        content.push_str("Claude Code v1.0\nline\n");
    }
    content.push_str("Claude Code v1.0\n");
    for _ in 0..20 {
        content.push_str("line\n");
    }
    let path = tmp.path().join("tiny.txt");
    std::fs::write(&path, content).unwrap();
    let written = split_file(&path, Some(tmp.path()), false).unwrap();
    for p in &written {
        let meta = std::fs::metadata(p).unwrap();
        assert!(meta.len() > 0);
    }
}

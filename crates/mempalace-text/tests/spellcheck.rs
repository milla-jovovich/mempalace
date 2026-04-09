#![allow(clippy::unwrap_used, clippy::expect_used, clippy::format_push_string)]

use std::collections::HashSet;
use std::sync::Mutex;

use mempalace_text::spellcheck::{
    clear_speller, edit_distance, get_system_words, load_known_names, set_known_names_override,
    set_speller_fn, set_system_words_override, should_skip, spellcheck_transcript,
    spellcheck_transcript_line, spellcheck_user_text,
};

static GLOBAL_GUARD: Mutex<()> = Mutex::new(());

fn guard() -> std::sync::MutexGuard<'static, ()> {
    GLOBAL_GUARD
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

fn set<I: IntoIterator<Item = &'static str>>(iter: I) -> HashSet<String> {
    iter.into_iter().map(str::to_string).collect()
}

// ─── should_skip ────────────────────────────────────────────────────────────

#[test]
fn short_tokens_skipped() {
    let empty = HashSet::new();
    assert!(should_skip("hi", &empty));
    assert!(should_skip("ok", &empty));
    assert!(should_skip("I", &empty));
}

#[test]
fn digits_skipped() {
    let empty = HashSet::new();
    assert!(should_skip("3am", &empty));
    assert!(should_skip("top10", &empty));
    assert!(should_skip("bge-large-v1.5", &empty));
}

#[test]
fn camelcase_skipped() {
    let empty = HashSet::new();
    assert!(should_skip("ChromaDB", &empty));
    assert!(should_skip("MemPalace", &empty));
}

#[test]
fn allcaps_skipped() {
    let empty = HashSet::new();
    assert!(should_skip("NDCG", &empty));
    assert!(should_skip("MAX_RESULTS", &empty));
}

#[test]
fn technical_skipped() {
    let empty = HashSet::new();
    assert!(should_skip("bge-large", &empty));
    assert!(should_skip("train_test", &empty));
}

#[test]
fn url_skipped() {
    let empty = HashSet::new();
    assert!(should_skip("https://example.com", &empty));
    assert!(should_skip("www.google.com", &empty));
}

#[test]
fn code_or_emoji_skipped() {
    let empty = HashSet::new();
    assert!(should_skip("`code`", &empty));
    assert!(should_skip("**bold**", &empty));
}

#[test]
fn known_name_skipped() {
    let known = set(["mempalace"]);
    assert!(should_skip("mempalace", &known));
}

#[test]
fn normal_word_not_skipped() {
    let empty = HashSet::new();
    assert!(!should_skip("hello", &empty));
    assert!(!should_skip("question", &empty));
}

// ─── edit_distance ─────────────────────────────────────────────────────────

#[test]
fn edit_identical() {
    assert_eq!(edit_distance("hello", "hello"), 0);
}

#[test]
fn edit_empty_strings() {
    assert_eq!(edit_distance("", "abc"), 3);
    assert_eq!(edit_distance("abc", ""), 3);
    assert_eq!(edit_distance("", ""), 0);
}

#[test]
fn edit_single_edit() {
    assert_eq!(edit_distance("cat", "bat"), 1);
    assert_eq!(edit_distance("cat", "cats"), 1);
    assert_eq!(edit_distance("cats", "cat"), 1);
}

#[test]
fn edit_known_distance() {
    assert_eq!(edit_distance("kitten", "sitting"), 3);
}

// ─── get_system_words ──────────────────────────────────────────────────────

#[test]
fn get_system_words_returns_set() {
    let _g = guard();
    set_system_words_override(None);
    let result = get_system_words();
    let _size: usize = result.len();
}

// ─── spellcheck_user_text ──────────────────────────────────────────────────

#[test]
fn passthrough_when_no_speller() {
    let _g = guard();
    clear_speller();
    let text = "somee misspeledd textt";
    assert_eq!(spellcheck_user_text(text, None), text);
}

#[test]
fn corrects_with_speller_installed() {
    let _g = guard();
    set_speller_fn(|word| match word {
        "knoe" => "know".to_string(),
        "befor" => "before".to_string(),
        other => other.to_string(),
    });
    set_system_words_override(Some(HashSet::new()));
    set_known_names_override(Some(HashSet::new()));

    let result = spellcheck_user_text("knoe the question befor", None);
    assert!(result.contains("know"));
    assert!(result.contains("before"));

    clear_speller();
    set_system_words_override(None);
    set_known_names_override(None);
}

#[test]
fn preserves_technical_terms() {
    let _g = guard();
    set_speller_fn(|_| "WRONG".to_string());
    set_system_words_override(Some(HashSet::new()));
    set_known_names_override(Some(HashSet::new()));

    let empty = HashSet::new();
    let result = spellcheck_user_text("ChromaDB bge-large", Some(&empty));
    assert!(result.contains("ChromaDB"));
    assert!(result.contains("bge-large"));
    assert!(!result.contains("WRONG"));

    clear_speller();
    set_system_words_override(None);
    set_known_names_override(None);
}

// ─── transcript helpers ───────────────────────────────────────────────────

#[test]
fn transcript_line_user_turn() {
    let _g = guard();
    set_speller_fn(|w| match w {
        "helo" => "hello".to_string(),
        other => other.to_string(),
    });
    set_system_words_override(Some(HashSet::new()));
    set_known_names_override(Some(HashSet::new()));

    let result = spellcheck_transcript_line("> helo world");
    assert!(result.contains("hello"), "expected `hello`, got `{result}`");

    clear_speller();
    set_system_words_override(None);
    set_known_names_override(None);
}

#[test]
fn transcript_line_assistant_turn() {
    let _g = guard();
    let line = "This is an assistant response";
    assert_eq!(spellcheck_transcript_line(line), line);
}

#[test]
fn transcript_line_empty_user_turn() {
    let _g = guard();
    let line = "> ";
    assert_eq!(spellcheck_transcript_line(line), line);
}

#[test]
fn transcript_processes_content() {
    let _g = guard();
    set_speller_fn(|w| match w {
        "usre" => "user".to_string(),
        other => other.to_string(),
    });
    set_system_words_override(Some(HashSet::new()));
    set_known_names_override(Some(HashSet::new()));

    let content = "Assistant line\n> usre line\nAnother assistant line";
    let result = spellcheck_transcript(content);
    let lines: Vec<&str> = result.split('\n').collect();
    assert_eq!(lines[0], "Assistant line");
    assert!(
        lines[1].contains("user"),
        "expected `user`, got `{}`",
        lines[1]
    );
    assert_eq!(lines[2], "Another assistant line");

    clear_speller();
    set_system_words_override(None);
    set_known_names_override(None);
}

// ─── load_known_names / speller edge cases (test_spellcheck_extra.py) ─────

#[test]
fn load_known_names_returns_override() {
    let _g = guard();
    let expected = set(["alice", "ali", "bob"]);
    set_known_names_override(Some(expected.clone()));
    let names = load_known_names();
    assert!(names.contains("alice"));
    assert!(names.contains("ali"));
    assert!(names.contains("bob"));
    set_known_names_override(None);
}

#[test]
fn load_known_names_empty_on_missing_registry() {
    let _g = guard();
    set_known_names_override(Some(HashSet::new()));
    let names = load_known_names();
    assert!(names.is_empty());
    set_known_names_override(None);
}

#[test]
fn capitalized_word_skipped() {
    let _g = guard();
    set_speller_fn(|_| "WRONG".to_string());
    set_system_words_override(Some(HashSet::new()));
    set_known_names_override(Some(HashSet::new()));

    let result = spellcheck_user_text("Alice went home", None);
    assert!(result.contains("Alice"));
    assert!(!result.contains("WRONG"));

    clear_speller();
    set_system_words_override(None);
    set_known_names_override(None);
}

#[test]
fn system_word_not_corrected() {
    let _g = guard();
    set_speller_fn(|_| "WRONG".to_string());
    set_system_words_override(Some(set(["coherently"])));
    set_known_names_override(Some(HashSet::new()));

    let result = spellcheck_user_text("coherently", None);
    assert!(result.contains("coherently"));

    clear_speller();
    set_system_words_override(None);
    set_known_names_override(None);
}

#[test]
fn high_edit_distance_rejected() {
    let _g = guard();
    set_speller_fn(|_| "completely_different_word".to_string());
    set_system_words_override(Some(HashSet::new()));
    set_known_names_override(Some(HashSet::new()));

    let result = spellcheck_user_text("hello", None);
    assert!(result.contains("hello"));

    clear_speller();
    set_system_words_override(None);
    set_known_names_override(None);
}

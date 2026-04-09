//! Spell-correct user messages before palace filing.
//!
//! Port of Python `mempalace/spellcheck.py`.
//!
//! # Preserves
//!
//! - Technical terms (words with digits, hyphens, underscores)
//! - CamelCase and ALL_CAPS identifiers
//! - Known entity names (from [`EntityRegistry`] if available)
//! - URLs and file paths
//! - Words shorter than 4 chars (common abbreviations, pronouns)
//! - Proper nouns (capitalised words)
//!
//! # Corrects
//!
//! - Genuine typos in lowercase, flowing text — via an optional [`Speller`]
//!   backend. If no backend is installed, text passes through unchanged
//!   (same behaviour as the Python module when `autocorrect` is missing).

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::{LazyLock, OnceLock, RwLock};

use regex::Regex;

use crate::entity_registry::EntityRegistry;

// ── Skip-pattern regexes ────────────────────────────────────────────────────

static HAS_DIGIT: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\d").unwrap());
static IS_CAMEL: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[A-Z][a-z]+[A-Z]").unwrap());
static IS_ALLCAPS: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[A-Z_@#$%^&*()+=\[\]{}|<>?.:/\\]+$").unwrap());
static IS_TECHNICAL: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[-_]").unwrap());
static IS_URL: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)https?://|www\.|/Users/|~/|\.[a-z]{2,4}$").unwrap());
static IS_CODE_OR_EMOJI: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[`*_#{}\[\]\\]").unwrap());

/// Minimum token length we will consider correcting.
const MIN_LENGTH: usize = 4;

/// Path to system wordlist (Unix). Mirrors the Python `_SYSTEM_DICT` constant.
static SYSTEM_DICT: LazyLock<PathBuf> = LazyLock::new(|| PathBuf::from("/usr/share/dict/words"));

// ── Speller backend (pluggable, mirrors Python's `_get_speller`) ──────────

/// A pluggable spell-correction backend.
///
/// A [`Speller`] takes a lowercased token and returns its suggested
/// correction (or the same token if it has no suggestion).
pub trait Speller: Send + Sync {
    /// Return a suggested correction for `word`. Return `word` unchanged
    /// if no correction is available.
    fn correct(&self, word: &str) -> String;
}

/// A speller backed by a function / closure.
pub struct FnSpeller<F: Fn(&str) -> String + Send + Sync>(pub F);

impl<F: Fn(&str) -> String + Send + Sync> std::fmt::Debug for FnSpeller<F> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("FnSpeller").finish()
    }
}

impl<F: Fn(&str) -> String + Send + Sync> Speller for FnSpeller<F> {
    fn correct(&self, word: &str) -> String {
        (self.0)(word)
    }
}

/// Global speller slot. `None` (default) means "no autocorrect installed",
/// which matches Python's passthrough behaviour when `autocorrect` is
/// missing.
static GLOBAL_SPELLER: LazyLock<RwLock<Option<Box<dyn Speller>>>> =
    LazyLock::new(|| RwLock::new(None));

/// Install a [`Speller`] backend. Subsequent calls to
/// [`spellcheck_user_text`] will route corrections through it.
///
/// Pass `None` to uninstall the speller (and return to passthrough mode).
pub fn set_speller(speller: Option<Box<dyn Speller>>) {
    if let Ok(mut slot) = GLOBAL_SPELLER.write() {
        *slot = speller;
    }
}

/// Install a closure as the speller. Convenience wrapper around
/// [`set_speller`].
pub fn set_speller_fn<F>(f: F)
where
    F: Fn(&str) -> String + Send + Sync + 'static,
{
    set_speller(Some(Box::new(FnSpeller(f))));
}

/// Remove any installed speller — text will pass through unchanged.
pub fn clear_speller() {
    set_speller(None);
}

/// Return `true` if a speller is currently installed.
pub fn speller_installed() -> bool {
    GLOBAL_SPELLER
        .read()
        .map(|slot| slot.is_some())
        .unwrap_or(false)
}

// ── System word cache ─────────────────────────────────────────────────────

static SYSTEM_WORDS: OnceLock<HashSet<String>> = OnceLock::new();
static SYSTEM_WORDS_OVERRIDE: LazyLock<RwLock<Option<HashSet<String>>>> =
    LazyLock::new(|| RwLock::new(None));

/// Load `/usr/share/dict/words` once and cache it. If the file does not
/// exist, returns an empty set (mirrors Python).
pub fn get_system_words() -> HashSet<String> {
    if let Ok(guard) = SYSTEM_WORDS_OVERRIDE.read() {
        if let Some(ref override_set) = *guard {
            return override_set.clone();
        }
    }
    SYSTEM_WORDS
        .get_or_init(|| {
            let path: &Path = SYSTEM_DICT.as_path();
            if !path.exists() {
                return HashSet::new();
            }
            std::fs::read_to_string(path)
                .map(|text| {
                    text.lines()
                        .map(str::trim)
                        .filter(|l| !l.is_empty())
                        .map(str::to_lowercase)
                        .collect()
                })
                .unwrap_or_default()
        })
        .clone()
}

/// Override the system word set (test helper, mirrors `monkeypatch` in Python).
pub fn set_system_words_override(words: Option<HashSet<String>>) {
    if let Ok(mut slot) = SYSTEM_WORDS_OVERRIDE.write() {
        *slot = words;
    }
}

// ── Known-name loading (from EntityRegistry) ───────────────────────────────

static KNOWN_NAMES_OVERRIDE: LazyLock<RwLock<Option<HashSet<String>>>> =
    LazyLock::new(|| RwLock::new(None));

/// Override the known-names result (test helper, mirrors `monkeypatch`).
pub fn set_known_names_override(names: Option<HashSet<String>>) {
    if let Ok(mut slot) = KNOWN_NAMES_OVERRIDE.write() {
        *slot = names;
    }
}

/// Pull all registered names from [`EntityRegistry`]. Returns an empty set
/// on any failure.
pub fn load_known_names() -> HashSet<String> {
    if let Ok(guard) = KNOWN_NAMES_OVERRIDE.read() {
        if let Some(ref override_set) = *guard {
            return override_set.clone();
        }
    }

    let mut names: HashSet<String> = HashSet::new();
    let reg = EntityRegistry::load(None);
    for (_, entity) in reg.people() {
        if let Some(canonical) = entity.get("canonical").and_then(|v| v.as_str()) {
            names.insert(canonical.to_lowercase());
        }
        if let Some(aliases) = entity.get("aliases").and_then(|v| v.as_array()) {
            for alias in aliases {
                if let Some(s) = alias.as_str() {
                    names.insert(s.to_lowercase());
                }
            }
        }
    }
    for project in reg.projects() {
        names.insert(project.to_lowercase());
    }
    names
}

// ── Skip logic ─────────────────────────────────────────────────────────────

/// Return `true` if this token should be left untouched by the speller.
/// Mirrors Python `_should_skip`.
pub fn should_skip(token: &str, known_names: &HashSet<String>) -> bool {
    if token.chars().count() < MIN_LENGTH {
        return true;
    }
    if HAS_DIGIT.is_match(token) {
        return true;
    }
    if IS_CAMEL.is_match(token) {
        return true;
    }
    if IS_ALLCAPS.is_match(token) {
        return true;
    }
    if IS_TECHNICAL.is_match(token) {
        return true;
    }
    if IS_URL.is_match(token) {
        return true;
    }
    if IS_CODE_OR_EMOJI.is_match(token) {
        return true;
    }
    if known_names.contains(&token.to_lowercase()) {
        return true;
    }
    false
}

// ── Edit distance ─────────────────────────────────────────────────────────

/// Levenshtein edit distance between `a` and `b`. Mirrors Python.
pub fn edit_distance(a: &str, b: &str) -> usize {
    if a == b {
        return 0;
    }
    let a_chars: Vec<char> = a.chars().collect();
    let b_chars: Vec<char> = b.chars().collect();
    if a_chars.is_empty() {
        return b_chars.len();
    }
    if b_chars.is_empty() {
        return a_chars.len();
    }

    let mut prev: Vec<usize> = (0..=b_chars.len()).collect();
    for (i, &ca) in a_chars.iter().enumerate() {
        let mut curr: Vec<usize> = Vec::with_capacity(b_chars.len() + 1);
        curr.push(i + 1);
        for (j, &cb) in b_chars.iter().enumerate() {
            let diag = prev[j] + usize::from(ca != cb);
            let insertion = prev[j + 1] + 1;
            let deletion = curr[j] + 1;
            curr.push(diag.min(insertion).min(deletion));
        }
        prev = curr;
    }
    prev[b_chars.len()]
}

// ── Core correction ───────────────────────────────────────────────────────

static TOKEN_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\S+").unwrap());

/// Characters we strip from the tail of a token before checking, and
/// re-attach after. Mirrors Python `rstrip(".,!?;:'\")")`.
const TRAILING_PUNCT: &[char] = &['.', ',', '!', '?', ';', ':', '\'', '"', ')'];

/// Spell-correct a user message.
///
/// If `known_names` is `None`, the function attempts to load known names
/// from [`EntityRegistry`] automatically. If no speller is installed,
/// text is returned unchanged.
pub fn spellcheck_user_text(text: &str, known_names: Option<&HashSet<String>>) -> String {
    let slot = match GLOBAL_SPELLER.read() {
        Ok(s) => s,
        Err(_) => return text.to_string(),
    };
    let speller = match &*slot {
        Some(s) => s,
        None => return text.to_string(),
    };

    let loaded_names: HashSet<String>;
    let names: &HashSet<String> = match known_names {
        Some(n) => n,
        None => {
            loaded_names = load_known_names();
            &loaded_names
        }
    };

    let sys_words = get_system_words();

    TOKEN_RE
        .replace_all(text, |caps: &regex::Captures<'_>| {
            let token = &caps[0];
            fix_token(token, names, &sys_words, speller.as_ref())
        })
        .into_owned()
}

fn fix_token(
    token: &str,
    known_names: &HashSet<String>,
    sys_words: &HashSet<String>,
    speller: &dyn Speller,
) -> String {
    let stripped = token.trim_end_matches(TRAILING_PUNCT);
    let punct = &token[stripped.len()..];

    if stripped.is_empty() || should_skip(stripped, known_names) {
        return token.to_string();
    }

    let Some(first_char) = stripped.chars().next() else {
        return token.to_string();
    };
    if first_char.is_uppercase() {
        return token.to_string();
    }

    if sys_words.contains(&stripped.to_lowercase()) {
        return token.to_string();
    }

    let corrected = speller.correct(stripped);

    if corrected != stripped {
        let dist = edit_distance(stripped, &corrected);
        let max_edits = if stripped.chars().count() <= 7 { 2 } else { 3 };
        if dist > max_edits {
            return token.to_string();
        }
    }

    format!("{corrected}{punct}")
}

// ── Transcript-level helpers ──────────────────────────────────────────────

/// Spell-correct a single transcript line. Only lines starting with `>`
/// are processed.
pub fn spellcheck_transcript_line(line: &str) -> String {
    let stripped = line.trim_start();
    if !stripped.starts_with('>') {
        return line.to_string();
    }

    let leading_ws = line.len() - stripped.len();
    let prefix_len = leading_ws + 2;
    if prefix_len > line.len() {
        return line.to_string();
    }

    let message = &line[prefix_len..];
    if message.trim().is_empty() {
        return line.to_string();
    }

    let corrected = spellcheck_user_text(message, None);
    format!("{}{}", &line[..prefix_len], corrected)
}

/// Spell-correct all user turns in a transcript.
pub fn spellcheck_transcript(content: &str) -> String {
    content
        .split('\n')
        .map(spellcheck_transcript_line)
        .collect::<Vec<_>>()
        .join("\n")
}

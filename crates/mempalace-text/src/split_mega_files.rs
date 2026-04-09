//! Split concatenated Claude Code transcript files into per-session files.
//!
//! Port of Python `mempalace/split_mega_files.py`.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::sync::{LazyLock, RwLock};

use regex::Regex;
use serde_json::Value as JsonValue;
use thiserror::Error;

// ── Errors ────────────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum Error {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("file exceeds size limit: {0} bytes > {1} bytes")]
    FileTooLarge(u64, u64),
}

pub type Result<T> = std::result::Result<T, Error>;

// ── Constants ─────────────────────────────────────────────────────────────

pub const MAX_FILE_SIZE: u64 = 500 * 1024 * 1024;

pub const FALLBACK_KNOWN_PEOPLE: &[&str] =
    &["Alice", "Ben", "Riley", "Max", "Sam", "Devon", "Jordan"];

static KNOWN_NAMES_PATH: LazyLock<RwLock<PathBuf>> = LazyLock::new(|| {
    let home = mempalace_core::home_dir().unwrap_or_else(|| PathBuf::from("/tmp"));
    RwLock::new(home.join(".mempalace").join("known_names.json"))
});

static KNOWN_NAMES_CACHE: LazyLock<RwLock<Option<JsonValue>>> = LazyLock::new(|| RwLock::new(None));

static KNOWN_PEOPLE_OVERRIDE: LazyLock<RwLock<Option<Vec<String>>>> =
    LazyLock::new(|| RwLock::new(None));

/// Override the path used for the known-names config file. Test helper,
/// mirrors Python's `monkeypatch.setattr(smf, "_KNOWN_NAMES_PATH", …)`.
pub fn set_known_names_path(path: PathBuf) {
    if let Ok(mut slot) = KNOWN_NAMES_PATH.write() {
        *slot = path;
    }
    reset_known_names_cache();
}

/// Reset the cached config file contents, forcing the next load to re-read.
pub fn reset_known_names_cache() {
    if let Ok(mut slot) = KNOWN_NAMES_CACHE.write() {
        *slot = None;
    }
}

/// Override the `KNOWN_PEOPLE` list used by [`extract_people`]. Test
/// helper, mirrors Python's `monkeypatch.setattr(smf, "KNOWN_PEOPLE", …)`.
pub fn set_known_people_override(people: Option<Vec<String>>) {
    if let Ok(mut slot) = KNOWN_PEOPLE_OVERRIDE.write() {
        *slot = people;
    }
}

fn known_names_path() -> PathBuf {
    KNOWN_NAMES_PATH
        .read()
        .map(|g| g.clone())
        .unwrap_or_else(|_| PathBuf::from("/tmp/known_names.json"))
}

/// Load and cache the optional known-names config file. Returns the raw
/// JSON value, or `None` if the file is missing or malformed.
pub fn load_known_names_config(force_reload: bool) -> Option<JsonValue> {
    if force_reload {
        reset_known_names_cache();
    }

    if let Ok(guard) = KNOWN_NAMES_CACHE.read() {
        if let Some(ref cached) = *guard {
            return Some(cached.clone());
        }
    }

    let path = known_names_path();
    if !path.exists() {
        return None;
    }

    let text = match std::fs::read_to_string(&path) {
        Ok(t) => t,
        Err(_) => return None,
    };
    let parsed: Option<JsonValue> = serde_json::from_str(&text).ok();
    if let Some(ref value) = parsed {
        if let Ok(mut slot) = KNOWN_NAMES_CACHE.write() {
            *slot = Some(value.clone());
        }
    }
    parsed
}

/// Load the list of known people from the config file, falling back to
/// [`FALLBACK_KNOWN_PEOPLE`] if no config is present.
pub fn load_known_people() -> Vec<String> {
    match load_known_names_config(false) {
        Some(JsonValue::Array(arr)) => arr
            .into_iter()
            .filter_map(|v| v.as_str().map(str::to_string))
            .collect(),
        Some(JsonValue::Object(map)) => map
            .get("names")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(str::to_string))
                    .collect()
            })
            .unwrap_or_default(),
        _ => FALLBACK_KNOWN_PEOPLE
            .iter()
            .map(|s| (*s).to_string())
            .collect(),
    }
}

/// Load the optional username→real-name mapping from the config file.
pub fn load_username_map() -> std::collections::HashMap<String, String> {
    match load_known_names_config(false) {
        Some(JsonValue::Object(map)) => map
            .get("username_map")
            .and_then(|v| v.as_object())
            .map(|obj| {
                obj.iter()
                    .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                    .collect()
            })
            .unwrap_or_default(),
        _ => std::collections::HashMap::new(),
    }
}

fn known_people() -> Vec<String> {
    if let Ok(guard) = KNOWN_PEOPLE_OVERRIDE.read() {
        if let Some(ref override_vec) = *guard {
            return override_vec.clone();
        }
    }
    load_known_people()
}

// ── Session boundary detection ────────────────────────────────────────────

/// True if `lines[idx]` is the start of a fresh session, rather than a
/// context restore. Mirrors Python `is_true_session_start`.
pub fn is_true_session_start(lines: &[String], idx: usize) -> bool {
    let end = (idx + 6).min(lines.len());
    let nearby: String = lines[idx..end].concat();
    !nearby.contains("Ctrl+E") && !nearby.contains("previous messages")
}

/// Return the line indices where real (non-restore) sessions begin.
pub fn find_session_boundaries(lines: &[String]) -> Vec<usize> {
    let mut out = Vec::new();
    for (i, line) in lines.iter().enumerate() {
        if line.contains("Claude Code v") && is_true_session_start(lines, i) {
            out.push(i);
        }
    }
    out
}

// ── Timestamp / people / subject extraction ───────────────────────────────

static TS_PATTERN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"⏺\s+(\d{1,2}:\d{2}\s+[AP]M)\s+\w+,\s+(\w+)\s+(\d{1,2}),\s+(\d{4})").unwrap()
});

static DIR_PATTERN: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"/Users/(\w+)/").unwrap());

static USER_PROMPT_SKIP: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(\./|cd |ls |python|bash|git |cat |source |export |claude|\./activate)").unwrap()
});

static NON_WORD: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[^\w\s-]").unwrap());
static WHITESPACE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\s+").unwrap());
static NOT_FILENAME_SAFE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[^\w\.\-]").unwrap());
static MULTI_UNDERSCORE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"_+").unwrap());
static NOT_STEM_SAFE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[^\w-]").unwrap());

fn month_code(month: &str) -> &'static str {
    match month {
        "January" => "01",
        "February" => "02",
        "March" => "03",
        "April" => "04",
        "May" => "05",
        "June" => "06",
        "July" => "07",
        "August" => "08",
        "September" => "09",
        "October" => "10",
        "November" => "11",
        "December" => "12",
        _ => "00",
    }
}

/// Find the first `⏺ H:MM AM/PM Weekday, Month DD, YYYY` line. Returns
/// `(human, iso)` or `(None, None)` if not found.
pub fn extract_timestamp(lines: &[String]) -> (Option<String>, Option<String>) {
    let scan_end = lines.len().min(50);
    for line in &lines[..scan_end] {
        if let Some(cap) = TS_PATTERN.captures(line) {
            let time_str = cap.get(1).map(|m| m.as_str()).unwrap_or("");
            let month = cap.get(2).map(|m| m.as_str()).unwrap_or("");
            let day = cap.get(3).map(|m| m.as_str()).unwrap_or("");
            let year = cap.get(4).map(|m| m.as_str()).unwrap_or("");

            let mon = month_code(month);
            let day_z = if day.len() < 2 {
                format!("0{day}")
            } else {
                day.to_string()
            };
            let time_safe = time_str.replace(':', "").replace(' ', "");
            let iso = format!("{year}-{mon}-{day_z}");
            let human = format!("{year}-{mon}-{day_z}_{time_safe}");
            return (Some(human), Some(iso));
        }
    }
    (None, None)
}

/// Detect people mentioned as speakers or by name in the first 100 lines.
pub fn extract_people(lines: &[String]) -> Vec<String> {
    let mut found: BTreeSet<String> = BTreeSet::new();
    let scan_end = lines.len().min(100);
    let text: String = lines[..scan_end].concat();

    for person in known_people() {
        let pattern_src = format!(r"(?i)\b{}\b", regex::escape(&person));
        if let Ok(re) = Regex::new(&pattern_src) {
            if re.is_match(&text) {
                found.insert(person);
            }
        }
    }

    if let Some(cap) = DIR_PATTERN.captures(&text) {
        if let Some(username) = cap.get(1) {
            let user_map = load_username_map();
            if let Some(real_name) = user_map.get(username.as_str()) {
                found.insert(real_name.clone());
            }
        }
    }

    found.into_iter().collect()
}

/// Find the first meaningful user prompt (a `>` line that isn't a shell
/// command). Returns a filename-safe subject.
pub fn extract_subject(lines: &[String]) -> String {
    for line in lines {
        if let Some(rest) = line.strip_prefix("> ") {
            let prompt = rest.trim();
            if prompt.is_empty() || prompt.len() <= 5 {
                continue;
            }
            if USER_PROMPT_SKIP.is_match(prompt) {
                continue;
            }
            let cleaned = NON_WORD.replace_all(prompt, "").to_string();
            let collapsed = WHITESPACE.replace_all(cleaned.trim(), "-").to_string();
            return collapsed.chars().take(60).collect();
        }
    }
    "session".to_string()
}

// ── split_file ────────────────────────────────────────────────────────────

/// Split a single mega-file into per-session files. Returns the list of
/// output paths written (or that would be written, in `dry_run` mode).
///
/// Mirrors Python `split_file`. Files larger than [`MAX_FILE_SIZE`] are
/// skipped and an empty vector is returned.
pub fn split_file(
    filepath: &Path,
    output_dir: Option<&Path>,
    dry_run: bool,
) -> Result<Vec<PathBuf>> {
    let metadata = std::fs::metadata(filepath)?;
    if metadata.len() > MAX_FILE_SIZE {
        return Ok(Vec::new());
    }

    let raw = std::fs::read_to_string(filepath).unwrap_or_default();
    let lines: Vec<String> = split_keep_newlines(&raw);

    let mut boundaries = find_session_boundaries(&lines);
    if boundaries.len() < 2 {
        return Ok(Vec::new());
    }
    boundaries.push(lines.len());

    let out_dir: PathBuf = output_dir
        .map(Path::to_path_buf)
        .or_else(|| filepath.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| PathBuf::from("."));

    let stem = filepath
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_default();
    let src_stem_raw = NOT_STEM_SAFE.replace_all(&stem, "_").to_string();
    let src_stem: String = src_stem_raw.chars().take(40).collect();

    let mut written = Vec::new();

    for (i, window) in boundaries.windows(2).enumerate() {
        let start = window[0];
        let end = window[1];
        let chunk: &[String] = &lines[start..end];
        if chunk.len() < 10 {
            continue;
        }

        let (ts_human, _) = extract_timestamp(chunk);
        let people = extract_people(chunk);
        let subject = extract_subject(chunk);

        let ts_part = ts_human.unwrap_or_else(|| format!("part{:02}", i + 1));
        let people_part: String = if people.is_empty() {
            "unknown".to_string()
        } else {
            people.iter().take(3).cloned().collect::<Vec<_>>().join("-")
        };

        let raw_name = format!("{src_stem}__{ts_part}_{people_part}_{subject}.txt");
        let sanitised = NOT_FILENAME_SAFE.replace_all(&raw_name, "_").to_string();
        let name = MULTI_UNDERSCORE.replace_all(&sanitised, "_").to_string();

        let out_path = out_dir.join(&name);

        if !dry_run {
            let content: String = chunk.concat();
            if let Some(parent) = out_path.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::write(&out_path, content)?;
        }

        written.push(out_path);
    }

    Ok(written)
}

/// Split a string on `\n` keeping the trailing newline on each line —
/// mirrors Python's `splitlines(keepends=True)`.
fn split_keep_newlines(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut start = 0usize;
    let bytes = text.as_bytes();
    for (i, &b) in bytes.iter().enumerate() {
        if b == b'\n' {
            let end = i + 1;
            out.push(text[start..end].to_string());
            start = end;
        }
    }
    if start < bytes.len() {
        out.push(text[start..].to_string());
    }
    out
}

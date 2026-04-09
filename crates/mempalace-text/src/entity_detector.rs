//! Entity auto-detection. Port of Python mempalace/entity_detector.py. Phase 3 sub-agent C.

use std::collections::{HashMap, HashSet};
use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use regex::Regex;
use thiserror::Error;

// ─── Error ──────────────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum ModuleError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("Regex compilation error: {0}")]
    Regex(#[from] regex::Error),
}

// ─── Pattern templates (no compile-time flags; added dynamically) ────────────

const PERSON_VERB_TEMPLATES: &[&str] = &[
    r"\b{name}\s+said\b",
    r"\b{name}\s+asked\b",
    r"\b{name}\s+told\b",
    r"\b{name}\s+replied\b",
    r"\b{name}\s+laughed\b",
    r"\b{name}\s+smiled\b",
    r"\b{name}\s+cried\b",
    r"\b{name}\s+felt\b",
    r"\b{name}\s+thinks?\b",
    r"\b{name}\s+wants?\b",
    r"\b{name}\s+loves?\b",
    r"\b{name}\s+hates?\b",
    r"\b{name}\s+knows?\b",
    r"\b{name}\s+decided\b",
    r"\b{name}\s+pushed\b",
    r"\b{name}\s+wrote\b",
    r"\bhey\s+{name}\b",
    r"\bthanks?\s+{name}\b",
    r"\bhi\s+{name}\b",
    r"\bdear\s+{name}\b",
];

const PRONOUN_PATTERN_STRS: &[&str] = &[
    r"\bshe\b",
    r"\bher\b",
    r"\bhers\b",
    r"\bhe\b",
    r"\bhim\b",
    r"\bhis\b",
    r"\bthey\b",
    r"\bthem\b",
    r"\btheir\b",
];

const DIALOGUE_PATTERN_TEMPLATES: &[&str] = &[
    r"^>\s*{name}[:\s]",
    r"^{name}:\s",
    r"^\[{name}\]",
    r#""{name}\s+said"#,
];

const PROJECT_VERB_TEMPLATES: &[&str] = &[
    r"\bbuilding\s+{name}\b",
    r"\bbuilt\s+{name}\b",
    r"\bship(?:ping|ped)?\s+{name}\b",
    r"\blaunch(?:ing|ed)?\s+{name}\b",
    r"\bdeploy(?:ing|ed)?\s+{name}\b",
    r"\binstall(?:ing|ed)?\s+{name}\b",
    r"\bthe\s+{name}\s+architecture\b",
    r"\bthe\s+{name}\s+pipeline\b",
    r"\bthe\s+{name}\s+system\b",
    r"\bthe\s+{name}\s+repo\b",
    r"\b{name}\s+v\d+\b",
    r"\b{name}\.py\b",
    r"\b{name}-core\b",
    r"\b{name}-local\b",
    r"\bimport\s+{name}\b",
    r"\bpip\s+install\s+{name}\b",
];

// ─── Compiled pronoun patterns (compiled once) ───────────────────────────────

#[allow(clippy::expect_used)]
static PRONOUN_PATTERNS: LazyLock<Vec<Regex>> = LazyLock::new(|| {
    PRONOUN_PATTERN_STRS
        .iter()
        .map(|p| Regex::new(p).expect("static pronoun pattern is valid"))
        .collect()
});

// ─── Candidate extraction regexes ───────────────────────────────────────────

#[allow(clippy::expect_used)]
static SINGLE_WORD_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\b([A-Z][a-z]{1,19})\b").expect("static regex"));

#[allow(clippy::expect_used)]
static MULTI_WORD_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b").expect("static regex"));

// ─── Stop-word set ───────────────────────────────────────────────────────────

pub static STOPWORDS: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "as",
        "is",
        "was",
        "are",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "they",
        "them",
        "their",
        "we",
        "our",
        "you",
        "your",
        "i",
        "my",
        "me",
        "he",
        "she",
        "his",
        "her",
        "who",
        "what",
        "when",
        "where",
        "why",
        "how",
        "which",
        "if",
        "then",
        "so",
        "not",
        "no",
        "yes",
        "ok",
        "okay",
        "just",
        "very",
        "really",
        "also",
        "already",
        "still",
        "even",
        "only",
        "here",
        "there",
        "now",
        "too",
        "up",
        "out",
        "about",
        "like",
        "use",
        "get",
        "got",
        "make",
        "made",
        "take",
        "put",
        "come",
        "go",
        "see",
        "know",
        "think",
        "true",
        "false",
        "none",
        "null",
        "new",
        "old",
        "all",
        "any",
        "some",
        "return",
        "print",
        "def",
        "class",
        "import",
        "step",
        "usage",
        "run",
        "check",
        "find",
        "add",
        "set",
        "list",
        "args",
        "dict",
        "str",
        "int",
        "bool",
        "path",
        "file",
        "type",
        "name",
        "note",
        "example",
        "option",
        "result",
        "error",
        "warning",
        "info",
        "every",
        "each",
        "more",
        "less",
        "next",
        "last",
        "first",
        "second",
        "stack",
        "layer",
        "mode",
        "test",
        "stop",
        "start",
        "copy",
        "move",
        "source",
        "target",
        "output",
        "input",
        "data",
        "item",
        "key",
        "value",
        "returns",
        "raises",
        "yields",
        "self",
        "cls",
        "kwargs",
        "world",
        "well",
        "want",
        "topic",
        "choose",
        "social",
        "cars",
        "phones",
        "healthcare",
        "ex",
        "machina",
        "deus",
        "human",
        "humans",
        "people",
        "things",
        "something",
        "nothing",
        "everything",
        "anything",
        "someone",
        "everyone",
        "anyone",
        "way",
        "time",
        "day",
        "life",
        "place",
        "thing",
        "part",
        "kind",
        "sort",
        "case",
        "point",
        "idea",
        "fact",
        "sense",
        "question",
        "answer",
        "reason",
        "number",
        "version",
        "system",
        "hey",
        "hi",
        "hello",
        "thanks",
        "thank",
        "right",
        "let",
        "click",
        "hit",
        "press",
        "tap",
        "drag",
        "drop",
        "open",
        "close",
        "save",
        "load",
        "launch",
        "install",
        "download",
        "upload",
        "scroll",
        "select",
        "enter",
        "submit",
        "cancel",
        "confirm",
        "delete",
        "paste",
        "write",
        "read",
        "search",
        "show",
        "hide",
        "desktop",
        "documents",
        "downloads",
        "users",
        "home",
        "library",
        "applications",
        "preferences",
        "settings",
        "terminal",
        "actor",
        "vector",
        "remote",
        "control",
        "duration",
        "fetch",
        "agents",
        "tools",
        "others",
        "guards",
        "ethics",
        "regulation",
        "learning",
        "thinking",
        "memory",
        "language",
        "intelligence",
        "technology",
        "society",
        "culture",
        "future",
        "history",
        "science",
        "model",
        "models",
        "network",
        "networks",
        "training",
        "inference",
    ]
    .iter()
    .copied()
    .collect()
});

// ─── Extension sets ──────────────────────────────────────────────────────────

pub static PROSE_EXTENSIONS: LazyLock<HashSet<&'static str>> =
    LazyLock::new(|| [".txt", ".md", ".rst", ".csv"].iter().copied().collect());

pub static READABLE_EXTENSIONS: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        ".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".csv", ".rst", ".toml",
        ".sh", ".rb", ".go", ".rs",
    ]
    .iter()
    .copied()
    .collect()
});

static SKIP_DIRS: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        ".next",
        "coverage",
        ".mempalace",
    ]
    .iter()
    .copied()
    .collect()
});

// ─── Public types ────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct EntityScore {
    pub person_score: i32,
    pub project_score: i32,
    pub person_signals: Vec<String>,
    pub project_signals: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EntityClass {
    Person,
    Project,
    Uncertain,
}

#[derive(Debug, Clone)]
pub struct DetectedEntity {
    pub name: String,
    pub entity_type: EntityClass,
    pub confidence: f64,
    pub frequency: u32,
    pub signals: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct EntityDetectionResult {
    pub people: Vec<DetectedEntity>,
    pub projects: Vec<DetectedEntity>,
    pub uncertain: Vec<DetectedEntity>,
}

#[derive(Debug, Clone)]
pub struct ConfirmedEntities {
    pub people: Vec<String>,
    pub projects: Vec<String>,
}

// ─── Internal pattern group ──────────────────────────────────────────────────

struct EntityPatterns {
    dialogue: Vec<Regex>,
    person_verbs: Vec<Regex>,
    project_verbs: Vec<Regex>,
    direct: Regex,
    versioned: Regex,
    code_ref: Regex,
}

fn build_entity_patterns(name: &str) -> Result<EntityPatterns, ModuleError> {
    let n = regex::escape(name);

    let dialogue: Result<Vec<Regex>, _> = DIALOGUE_PATTERN_TEMPLATES
        .iter()
        .map(|t| {
            let pat = format!("(?im){}", t.replace("{name}", &n));
            Regex::new(&pat)
        })
        .collect();

    let person_verbs: Result<Vec<Regex>, _> = PERSON_VERB_TEMPLATES
        .iter()
        .map(|t| {
            let pat = format!("(?i){}", t.replace("{name}", &n));
            Regex::new(&pat)
        })
        .collect();

    let project_verbs: Result<Vec<Regex>, _> = PROJECT_VERB_TEMPLATES
        .iter()
        .map(|t| {
            let pat = format!("(?i){}", t.replace("{name}", &n));
            Regex::new(&pat)
        })
        .collect();

    let direct = Regex::new(&format!(
        r"(?i)\bhey\s+{n}\b|\bthanks?\s+{n}\b|\bhi\s+{n}\b"
    ))?;
    let versioned = Regex::new(&format!(r"(?i)\b{n}[-v]\w+"))?;
    let code_ref = Regex::new(&format!(r"(?i)\b{n}\.(py|js|ts|yaml|yml|json|sh)\b"))?;

    Ok(EntityPatterns {
        dialogue: dialogue?,
        person_verbs: person_verbs?,
        project_verbs: project_verbs?,
        direct,
        versioned,
        code_ref,
    })
}

/// Build all compiled regex patterns for a given entity name (public API).
pub fn build_patterns(name: &str) -> Vec<Regex> {
    match build_entity_patterns(name) {
        Ok(p) => {
            let mut all = p.dialogue;
            all.extend(p.person_verbs);
            all.extend(p.project_verbs);
            all.push(p.direct);
            all.push(p.versioned);
            all.push(p.code_ref);
            all
        }
        Err(_) => Vec::new(),
    }
}

// ─── Candidate extraction ────────────────────────────────────────────────────

/// Extract capitalized proper-noun candidates from text.
/// Returns `{name: frequency}` for names appearing ≥3 times.
pub fn extract_candidates(text: &str) -> HashMap<String, u32> {
    let mut counts: HashMap<String, u32> = HashMap::new();

    for cap in SINGLE_WORD_RE.find_iter(text) {
        let word = cap.as_str();
        if word.len() > 1 && !STOPWORDS.contains(word.to_lowercase().as_str()) {
            *counts.entry(word.to_owned()).or_insert(0) += 1;
        }
    }

    for cap in MULTI_WORD_RE.find_iter(text) {
        let phrase = cap.as_str();
        let all_stop = phrase
            .split_whitespace()
            .any(|w| STOPWORDS.contains(w.to_lowercase().as_str()));
        if !all_stop {
            *counts.entry(phrase.to_owned()).or_insert(0) += 1;
        }
    }

    counts.retain(|_, v| *v >= 3);
    counts
}

// ─── Signal scoring ──────────────────────────────────────────────────────────

/// Score a candidate as person vs project by checking signal patterns.
pub fn score_entity(name: &str, text: &str, lines: &[&str]) -> Result<EntityScore, ModuleError> {
    let patterns = build_entity_patterns(name)?;
    let mut person_score: i32 = 0;
    let mut project_score: i32 = 0;
    let mut person_signals: Vec<String> = Vec::new();
    let mut project_signals: Vec<String> = Vec::new();

    // Dialogue markers (weight ×3)
    for rx in &patterns.dialogue {
        let matches = rx.find_iter(text).count() as i32;
        if matches > 0 {
            person_score += matches * 3;
            person_signals.push(format!("dialogue marker ({matches}x)"));
        }
    }

    // Person verbs (weight ×2)
    for rx in &patterns.person_verbs {
        let matches = rx.find_iter(text).count() as i32;
        if matches > 0 {
            person_score += matches * 2;
            person_signals.push(format!("'{name}...' action ({matches}x)"));
        }
    }

    // Pronoun proximity
    let name_lower = name.to_lowercase();
    let name_line_indices: Vec<usize> = lines
        .iter()
        .enumerate()
        .filter(|(_, line)| line.to_lowercase().contains(&name_lower))
        .map(|(i, _)| i)
        .collect();

    let mut pronoun_hits: i32 = 0;
    for idx in name_line_indices {
        let start = idx.saturating_sub(2);
        let end = (idx + 3).min(lines.len());
        let window_text = lines[start..end].join(" ").to_lowercase();
        if PRONOUN_PATTERNS.iter().any(|rx| rx.is_match(&window_text)) {
            pronoun_hits += 1;
        }
    }
    if pronoun_hits > 0 {
        person_score += pronoun_hits * 2;
        person_signals.push(format!("pronoun nearby ({pronoun_hits}x)"));
    }

    // Direct address (weight ×4)
    let direct = patterns.direct.find_iter(text).count() as i32;
    if direct > 0 {
        person_score += direct * 4;
        person_signals.push(format!("addressed directly ({direct}x)"));
    }

    // Project verbs (weight ×2)
    for rx in &patterns.project_verbs {
        let matches = rx.find_iter(text).count() as i32;
        if matches > 0 {
            project_score += matches * 2;
            project_signals.push(format!("project verb ({matches}x)"));
        }
    }

    // Versioned (weight ×3)
    let versioned = patterns.versioned.find_iter(text).count() as i32;
    if versioned > 0 {
        project_score += versioned * 3;
        project_signals.push(format!("versioned/hyphenated ({versioned}x)"));
    }

    // Code file reference (weight ×3)
    let code_ref = patterns.code_ref.find_iter(text).count() as i32;
    if code_ref > 0 {
        project_score += code_ref * 3;
        project_signals.push(format!("code file reference ({code_ref}x)"));
    }

    person_signals.truncate(3);
    project_signals.truncate(3);

    Ok(EntityScore {
        person_score,
        project_score,
        person_signals,
        project_signals,
    })
}

// ─── Classification ──────────────────────────────────────────────────────────

/// Classify entity as person / project / uncertain based on signal scores.
pub fn classify_entity(name: &str, frequency: u32, scores: &EntityScore) -> DetectedEntity {
    let ps = scores.person_score;
    let prs = scores.project_score;
    let total = ps + prs;

    if total == 0 {
        let confidence = (frequency as f64 / 50.0).min(0.4);
        let confidence = (confidence * 100.0).round() / 100.0;
        return DetectedEntity {
            name: name.to_owned(),
            entity_type: EntityClass::Uncertain,
            confidence,
            frequency,
            signals: vec![format!("appears {frequency}x, no strong type signals")],
        };
    }

    let person_ratio = ps as f64 / total as f64;

    let mut signal_categories: HashSet<&str> = HashSet::new();
    for s in &scores.person_signals {
        if s.contains("dialogue") {
            signal_categories.insert("dialogue");
        } else if s.contains("action") {
            signal_categories.insert("action");
        } else if s.contains("pronoun") {
            signal_categories.insert("pronoun");
        } else if s.contains("addressed") {
            signal_categories.insert("addressed");
        }
    }
    let has_two_signal_types = signal_categories.len() >= 2;

    let (entity_type, confidence, signals) =
        if person_ratio >= 0.7 && has_two_signal_types && ps >= 5 {
            let conf = (0.5 + person_ratio * 0.5).min(0.99);
            let sigs = if scores.person_signals.is_empty() {
                vec![format!("appears {frequency}x")]
            } else {
                scores.person_signals.clone()
            };
            (EntityClass::Person, conf, sigs)
        } else if person_ratio >= 0.7 && (!has_two_signal_types || ps < 5) {
            let mut sigs = scores.person_signals.clone();
            sigs.push(format!("appears {frequency}x — pronoun-only match"));
            (EntityClass::Uncertain, 0.4, sigs)
        } else if person_ratio <= 0.3 {
            let conf = (0.5 + (1.0 - person_ratio) * 0.5).min(0.99);
            let sigs = if scores.project_signals.is_empty() {
                vec![format!("appears {frequency}x")]
            } else {
                scores.project_signals.clone()
            };
            (EntityClass::Project, conf, sigs)
        } else {
            let mut sigs: Vec<String> = scores
                .person_signals
                .iter()
                .chain(scores.project_signals.iter())
                .take(3)
                .cloned()
                .collect();
            sigs.push("mixed signals — needs review".to_owned());
            (EntityClass::Uncertain, 0.5, sigs)
        };

    let confidence = (confidence * 100.0).round() / 100.0;

    DetectedEntity {
        name: name.to_owned(),
        entity_type,
        confidence,
        frequency,
        signals,
    }
}

// ─── Main detection ──────────────────────────────────────────────────────────

/// Scan files and detect entity candidates. Reads first 5 KB of each file.
pub fn detect_entities(file_paths: &[PathBuf], max_files: usize) -> EntityDetectionResult {
    const MAX_BYTES_PER_FILE: usize = 5_000;
    let mut all_text: Vec<String> = Vec::new();
    let mut all_lines: Vec<String> = Vec::new();

    for filepath in file_paths.iter().take(max_files) {
        let bytes = match std::fs::read(filepath) {
            Ok(b) => b,
            Err(_) => continue,
        };
        let truncated = &bytes[..bytes.len().min(MAX_BYTES_PER_FILE)];
        let content = String::from_utf8_lossy(truncated).into_owned();
        for line in content.lines() {
            all_lines.push(line.to_owned());
        }
        all_text.push(content);
    }

    let combined_text = all_text.join("\n");
    let candidates = extract_candidates(&combined_text);

    if candidates.is_empty() {
        return EntityDetectionResult {
            people: Vec::new(),
            projects: Vec::new(),
            uncertain: Vec::new(),
        };
    }

    let line_refs: Vec<&str> = all_lines.iter().map(String::as_str).collect();
    let mut people: Vec<DetectedEntity> = Vec::new();
    let mut projects: Vec<DetectedEntity> = Vec::new();
    let mut uncertain: Vec<DetectedEntity> = Vec::new();

    let mut sorted_candidates: Vec<(String, u32)> = candidates.into_iter().collect();
    sorted_candidates.sort_by(|a, b| b.1.cmp(&a.1));

    for (name, frequency) in sorted_candidates {
        let scores = match score_entity(&name, &combined_text, &line_refs) {
            Ok(s) => s,
            Err(_) => continue,
        };
        let entity = classify_entity(&name, frequency, &scores);
        match entity.entity_type {
            EntityClass::Person => people.push(entity),
            EntityClass::Project => projects.push(entity),
            EntityClass::Uncertain => uncertain.push(entity),
        }
    }

    people.sort_by(|a, b| {
        b.confidence
            .partial_cmp(&a.confidence)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    projects.sort_by(|a, b| {
        b.confidence
            .partial_cmp(&a.confidence)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    uncertain.sort_by(|a, b| b.frequency.cmp(&a.frequency));

    people.truncate(15);
    projects.truncate(10);
    uncertain.truncate(8);

    EntityDetectionResult {
        people,
        projects,
        uncertain,
    }
}

// ─── Scan helper ─────────────────────────────────────────────────────────────

/// Collect prose file paths for entity detection.
/// Prefers .txt/.md/.rst/.csv; falls back to all readable files when prose < 3.
pub fn scan_for_detection(project_dir: &Path, max_files: usize) -> Vec<PathBuf> {
    let mut prose_files: Vec<PathBuf> = Vec::new();
    let mut all_files: Vec<PathBuf> = Vec::new();

    walk_files(project_dir, &mut prose_files, &mut all_files);

    let files = if prose_files.len() >= 3 {
        prose_files
    } else {
        let mut combined = prose_files;
        combined.extend(all_files);
        combined
    };

    files.into_iter().take(max_files).collect()
}

fn walk_files(dir: &Path, prose: &mut Vec<PathBuf>, all: &mut Vec<PathBuf>) {
    let entries = match std::fs::read_dir(dir) {
        Ok(e) => e,
        Err(_) => return,
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            let skip = path
                .file_name()
                .and_then(|n| n.to_str())
                .map(|n| SKIP_DIRS.contains(n))
                .unwrap_or(false);
            if !skip {
                walk_files(&path, prose, all);
            }
        } else if path.is_file() {
            let ext = path
                .extension()
                .and_then(|e| e.to_str())
                .map(|e| format!(".{}", e.to_lowercase()))
                .unwrap_or_default();
            if PROSE_EXTENSIONS.contains(ext.as_str()) {
                prose.push(path);
            } else if READABLE_EXTENSIONS.contains(ext.as_str()) {
                all.push(path);
            }
        }
    }
}

// ─── Interactive confirm ─────────────────────────────────────────────────────

/// Print a list of entities with confidence bars.
pub fn print_entity_list(
    entities: &[DetectedEntity],
    label: &str,
    writer: &mut dyn Write,
) -> Result<(), std::io::Error> {
    writeln!(writer, "\n  {label}:")?;
    if entities.is_empty() {
        writeln!(writer, "    (none detected)")?;
        return Ok(());
    }
    for (i, e) in entities.iter().enumerate() {
        let bar_filled = (e.confidence * 5.0).round() as usize;
        let bar_empty = 5usize.saturating_sub(bar_filled);
        let bar = "●".repeat(bar_filled) + &"○".repeat(bar_empty);
        let signals_str = e
            .signals
            .iter()
            .take(2)
            .cloned()
            .collect::<Vec<_>>()
            .join(", ");
        writeln!(
            writer,
            "    {:2}. {:<20} [{}] {}",
            i + 1,
            e.name,
            bar,
            signals_str
        )?;
    }
    Ok(())
}

fn read_trimmed(reader: &mut dyn BufRead) -> Result<String, std::io::Error> {
    let mut line = String::new();
    reader.read_line(&mut line)?;
    Ok(line.trim().to_owned())
}

/// Interactive confirmation of detected entities.
/// Pass `yes=true` to auto-accept without prompting.
pub fn confirm_entities(
    detected: &EntityDetectionResult,
    yes: bool,
    reader: &mut dyn BufRead,
    writer: &mut dyn Write,
) -> Result<ConfirmedEntities, ModuleError> {
    writeln!(writer, "\n{}", "=".repeat(58))?;
    writeln!(writer, "  MemPalace — Entity Detection")?;
    writeln!(writer, "{}", "=".repeat(58))?;
    writeln!(writer, "\n  Scanned your files. Here's what we found:\n")?;

    print_entity_list(&detected.people, "PEOPLE", writer)?;
    print_entity_list(&detected.projects, "PROJECTS", writer)?;

    if !detected.uncertain.is_empty() {
        print_entity_list(&detected.uncertain, "UNCERTAIN (need your call)", writer)?;
    }

    let mut confirmed_people: Vec<String> =
        detected.people.iter().map(|e| e.name.clone()).collect();
    let mut confirmed_projects: Vec<String> =
        detected.projects.iter().map(|e| e.name.clone()).collect();

    if yes {
        writeln!(
            writer,
            "\n  Auto-accepting {} people, {} projects.",
            confirmed_people.len(),
            confirmed_projects.len()
        )?;
        return Ok(ConfirmedEntities {
            people: confirmed_people,
            projects: confirmed_projects,
        });
    }

    writeln!(writer, "\n{}", "─".repeat(58))?;
    writeln!(writer, "  Options:")?;
    writeln!(writer, "    [enter]  Accept all")?;
    writeln!(
        writer,
        "    [edit]   Remove wrong entries or reclassify uncertain"
    )?;
    writeln!(writer, "    [add]    Add missing people or projects")?;
    writeln!(writer)?;
    write!(writer, "  Your choice [enter/edit/add]: ")?;
    writer.flush()?;
    let choice = read_trimmed(reader)?.to_lowercase();

    if choice == "edit" {
        if !detected.uncertain.is_empty() {
            writeln!(writer, "\n  Uncertain entities — classify each:")?;
            for e in &detected.uncertain {
                write!(writer, "    {} — (p)erson, (r)roject, or (s)kip? ", e.name)?;
                writer.flush()?;
                let ans = read_trimmed(reader)?.to_lowercase();
                if ans == "p" {
                    confirmed_people.push(e.name.clone());
                } else if ans == "r" {
                    confirmed_projects.push(e.name.clone());
                }
            }
        }

        writeln!(
            writer,
            "\n  Current people: {}",
            if confirmed_people.is_empty() {
                "(none)".to_owned()
            } else {
                confirmed_people.join(", ")
            }
        )?;
        write!(
            writer,
            "  Numbers to REMOVE from people (comma-separated, or enter to skip): "
        )?;
        writer.flush()?;
        let remove_str = read_trimmed(reader)?;
        if !remove_str.is_empty() {
            let to_remove: HashSet<usize> = remove_str
                .split(',')
                .filter_map(|s| s.trim().parse::<usize>().ok())
                .filter(|&n| n >= 1)
                .map(|n| n - 1)
                .collect();
            confirmed_people = confirmed_people
                .into_iter()
                .enumerate()
                .filter(|(i, _)| !to_remove.contains(i))
                .map(|(_, v)| v)
                .collect();
        }

        writeln!(
            writer,
            "\n  Current projects: {}",
            if confirmed_projects.is_empty() {
                "(none)".to_owned()
            } else {
                confirmed_projects.join(", ")
            }
        )?;
        write!(
            writer,
            "  Numbers to REMOVE from projects (comma-separated, or enter to skip): "
        )?;
        writer.flush()?;
        let remove_str = read_trimmed(reader)?;
        if !remove_str.is_empty() {
            let to_remove: HashSet<usize> = remove_str
                .split(',')
                .filter_map(|s| s.trim().parse::<usize>().ok())
                .filter(|&n| n >= 1)
                .map(|n| n - 1)
                .collect();
            confirmed_projects = confirmed_projects
                .into_iter()
                .enumerate()
                .filter(|(i, _)| !to_remove.contains(i))
                .map(|(_, v)| v)
                .collect();
        }
    }

    let do_add = if choice == "add" {
        true
    } else {
        write!(writer, "\n  Add any missing? [y/N]: ")?;
        writer.flush()?;
        read_trimmed(reader)?.to_lowercase() == "y"
    };

    if do_add {
        loop {
            write!(writer, "  Name (or enter to stop): ")?;
            writer.flush()?;
            let name = read_trimmed(reader)?;
            if name.is_empty() {
                break;
            }
            write!(writer, "  Is '{name}' a (p)erson or p(r)oject? ")?;
            writer.flush()?;
            let kind = read_trimmed(reader)?.to_lowercase();
            if kind == "p" {
                confirmed_people.push(name);
            } else if kind == "r" {
                confirmed_projects.push(name);
            }
        }
    }

    writeln!(writer, "\n{}", "=".repeat(58))?;
    writeln!(writer, "  Confirmed:")?;
    writeln!(
        writer,
        "  People:   {}",
        if confirmed_people.is_empty() {
            "(none)".to_owned()
        } else {
            confirmed_people.join(", ")
        }
    )?;
    writeln!(
        writer,
        "  Projects: {}",
        if confirmed_projects.is_empty() {
            "(none)".to_owned()
        } else {
            confirmed_projects.join(", ")
        }
    )?;
    writeln!(writer, "{}\n", "=".repeat(58))?;

    Ok(ConfirmedEntities {
        people: confirmed_people,
        projects: confirmed_projects,
    })
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]

    use super::*;
    use tempfile::tempdir;

    // ── extract_candidates ──────────────────────────────────────────────────

    #[test]
    fn test_extract_candidates_finds_frequent_names() {
        let text = "Riley said hello. Riley laughed. Riley smiled. Riley waved.";
        let result = extract_candidates(text);
        assert!(result.contains_key("Riley"));
        assert!(*result.get("Riley").unwrap() >= 3);
    }

    #[test]
    fn test_extract_candidates_ignores_stopwords() {
        let text = "The The The The The The";
        let result = extract_candidates(text);
        assert!(!result.contains_key("The"));
    }

    #[test]
    fn test_extract_candidates_requires_min_frequency() {
        let text = "Riley said hi. Devon waved.";
        let result = extract_candidates(text);
        assert!(!result.contains_key("Riley"));
        assert!(!result.contains_key("Devon"));
    }

    #[test]
    fn test_extract_candidates_finds_multi_word_names() {
        let text = "Claude Code is great. Claude Code rocks. Claude Code works. Claude Code rules.";
        let result = extract_candidates(text);
        assert!(result.contains_key("Claude Code"));
    }

    #[test]
    fn test_extract_candidates_empty_text() {
        let result = extract_candidates("");
        assert!(result.is_empty());
    }

    // ── score_entity ────────────────────────────────────────────────────────

    #[test]
    fn test_score_entity_person_verbs() {
        let text = "Riley said hello. Riley asked why. Riley told me.";
        let lines: Vec<&str> = text.lines().collect();
        let result = score_entity("Riley", text, &lines).unwrap();
        assert!(result.person_score > 0);
        assert!(!result.person_signals.is_empty());
    }

    #[test]
    fn test_score_entity_project_verbs() {
        let text = "We are building ChromaDb. We deployed ChromaDb. Install ChromaDb.";
        let lines: Vec<&str> = text.lines().collect();
        let result = score_entity("ChromaDb", text, &lines).unwrap();
        assert!(result.project_score > 0);
        assert!(!result.project_signals.is_empty());
    }

    #[test]
    fn test_score_entity_dialogue_markers() {
        let text = "Riley: Hey, how are you?\nRiley: I'm fine.";
        let lines: Vec<&str> = text.lines().collect();
        let result = score_entity("Riley", text, &lines).unwrap();
        assert!(result.person_score > 0);
    }

    #[test]
    fn test_score_entity_code_ref() {
        let text = "Check out ChromaDb.py for details. Also ChromaDb.js is good.";
        let lines: Vec<&str> = text.lines().collect();
        let result = score_entity("ChromaDb", text, &lines).unwrap();
        assert!(result.project_score > 0);
    }

    #[test]
    fn test_score_entity_no_signals() {
        let text = "Nothing interesting here at all.";
        let lines: Vec<&str> = text.lines().collect();
        let result = score_entity("Riley", text, &lines).unwrap();
        assert_eq!(result.person_score, 0);
        assert_eq!(result.project_score, 0);
    }

    // ── classify_entity ─────────────────────────────────────────────────────

    #[test]
    fn test_classify_entity_no_signals_gives_uncertain() {
        let scores = EntityScore {
            person_score: 0,
            project_score: 0,
            person_signals: vec![],
            project_signals: vec![],
        };
        let result = classify_entity("Foo", 10, &scores);
        assert_eq!(result.entity_type, EntityClass::Uncertain);
        assert_eq!(result.name, "Foo");
    }

    #[test]
    fn test_classify_entity_strong_project() {
        let scores = EntityScore {
            person_score: 0,
            project_score: 10,
            person_signals: vec![],
            project_signals: vec![
                "project verb (5x)".to_owned(),
                "code file reference (2x)".to_owned(),
            ],
        };
        let result = classify_entity("ChromaDb", 5, &scores);
        assert_eq!(result.entity_type, EntityClass::Project);
    }

    #[test]
    fn test_classify_entity_strong_person_needs_two_signal_types() {
        let scores = EntityScore {
            person_score: 10,
            project_score: 0,
            person_signals: vec![
                "dialogue marker (3x)".to_owned(),
                "'Riley...' action (4x)".to_owned(),
            ],
            project_signals: vec![],
        };
        let result = classify_entity("Riley", 8, &scores);
        assert_eq!(result.entity_type, EntityClass::Person);
    }

    #[test]
    fn test_classify_entity_pronoun_only_is_uncertain() {
        let scores = EntityScore {
            person_score: 8,
            project_score: 0,
            person_signals: vec!["pronoun nearby (4x)".to_owned()],
            project_signals: vec![],
        };
        let result = classify_entity("Riley", 5, &scores);
        assert_eq!(result.entity_type, EntityClass::Uncertain);
    }

    #[test]
    fn test_classify_entity_mixed_signals() {
        let scores = EntityScore {
            person_score: 5,
            project_score: 5,
            person_signals: vec!["pronoun nearby (2x)".to_owned()],
            project_signals: vec!["project verb (2x)".to_owned()],
        };
        let result = classify_entity("Lantern", 5, &scores);
        assert_eq!(result.entity_type, EntityClass::Uncertain);
        assert!(result
            .signals
            .last()
            .map(|s| s.contains("mixed signals"))
            .unwrap_or(false));
    }

    // ── detect_entities (integration) ───────────────────────────────────────

    #[test]
    fn test_detect_entities_with_person_file() {
        let dir = tempdir().unwrap();
        let f = dir.path().join("notes.txt");
        let content = [
            "Riley said hello today.",
            "Riley asked about the project.",
            "Riley told me she was happy.",
            "Riley: I think we should go.",
            "Hey Riley, thanks for the help.",
            "Riley laughed and smiled.",
            "Riley decided to join.",
            "Riley pushed the change.",
        ]
        .join("\n");
        std::fs::write(&f, &content).unwrap();
        let result = detect_entities(&[f], 10);
        let all_names: Vec<&str> = result
            .people
            .iter()
            .chain(result.projects.iter())
            .chain(result.uncertain.iter())
            .map(|e| e.name.as_str())
            .collect();
        assert!(all_names.contains(&"Riley"));
    }

    #[test]
    fn test_detect_entities_with_project_file() {
        let dir = tempdir().unwrap();
        let f = dir.path().join("readme.txt");
        let content = [
            "The Lantern project is great.",
            "Building Lantern was fun.",
            "We deployed Lantern today.",
            "Install Lantern with pip install Lantern.",
            "Check Lantern.py for the source.",
            "Lantern v2 is faster.",
        ]
        .join("\n");
        std::fs::write(&f, &content).unwrap();
        let result = detect_entities(&[f], 10);
        let all_names: Vec<&str> = result
            .people
            .iter()
            .chain(result.projects.iter())
            .chain(result.uncertain.iter())
            .map(|e| e.name.as_str())
            .collect();
        assert!(all_names.contains(&"Lantern"));
    }

    #[test]
    fn test_detect_entities_empty_files() {
        let dir = tempdir().unwrap();
        let f = dir.path().join("empty.txt");
        std::fs::write(&f, "").unwrap();
        let result = detect_entities(&[f], 10);
        assert!(result.people.is_empty());
        assert!(result.projects.is_empty());
        assert!(result.uncertain.is_empty());
    }

    #[test]
    fn test_detect_entities_handles_missing_file() {
        let dir = tempdir().unwrap();
        let missing = dir.path().join("nonexistent.txt");
        let result = detect_entities(&[missing], 10);
        assert!(result.people.is_empty());
        assert!(result.projects.is_empty());
        assert!(result.uncertain.is_empty());
    }

    #[test]
    fn test_detect_entities_respects_max_files() {
        let dir = tempdir().unwrap();
        let mut files = Vec::new();
        for i in 0..5 {
            let f = dir.path().join(format!("file{i}.txt"));
            std::fs::write(&f, "Riley said hello. ".repeat(10)).unwrap();
            files.push(f);
        }
        let result = detect_entities(&files, 2);
        // Should complete without error
        let _ = result;
    }

    // ── scan_for_detection ──────────────────────────────────────────────────

    #[test]
    fn test_scan_for_detection_finds_prose() {
        let dir = tempdir().unwrap();
        std::fs::write(dir.path().join("notes.md"), "hello").unwrap();
        std::fs::write(dir.path().join("data.txt"), "world").unwrap();
        std::fs::write(dir.path().join("code.py"), "import os").unwrap();
        let files = scan_for_detection(dir.path(), 10);
        let exts: std::collections::HashSet<_> = files
            .iter()
            .filter_map(|f| {
                f.extension()
                    .and_then(|e| e.to_str())
                    .map(|e| format!(".{e}"))
            })
            .collect();
        assert!(exts.contains(".md") || exts.contains(".txt"));
    }

    #[test]
    fn test_scan_for_detection_skips_git_dir() {
        let dir = tempdir().unwrap();
        let git_dir = dir.path().join(".git");
        std::fs::create_dir(&git_dir).unwrap();
        std::fs::write(git_dir.join("config.txt"), "git config").unwrap();
        std::fs::write(dir.path().join("readme.md"), "hello").unwrap();
        let files = scan_for_detection(dir.path(), 10);
        let file_strs: Vec<_> = files
            .iter()
            .map(|f| f.to_string_lossy().into_owned())
            .collect();
        assert!(!file_strs.iter().any(|f| f.contains(".git")));
    }

    // ── module-level constants ──────────────────────────────────────────────

    #[test]
    fn test_stopwords_contains_common_words() {
        assert!(STOPWORDS.contains("the"));
        assert!(STOPWORDS.contains("import"));
        assert!(STOPWORDS.contains("class"));
    }

    #[test]
    fn test_prose_extensions() {
        assert!(PROSE_EXTENSIONS.contains(".txt"));
        assert!(PROSE_EXTENSIONS.contains(".md"));
    }

    // ── print_entity_list ──────────────────────────────────────────────────

    #[test]
    fn test_print_entity_list_with_entities() {
        let entities = vec![
            DetectedEntity {
                name: "Alice".to_owned(),
                confidence: 0.9,
                entity_type: EntityClass::Person,
                frequency: 5,
                signals: vec!["dialogue marker (3x)".to_owned()],
            },
            DetectedEntity {
                name: "Bob".to_owned(),
                confidence: 0.5,
                entity_type: EntityClass::Person,
                frequency: 3,
                signals: vec![],
            },
        ];
        let mut output = Vec::new();
        print_entity_list(&entities, "PEOPLE", &mut output).unwrap();
        let out = String::from_utf8(output).unwrap();
        assert!(out.contains("PEOPLE"));
        assert!(out.contains("Alice"));
        assert!(out.contains("Bob"));
    }

    #[test]
    fn test_print_entity_list_empty() {
        let mut output = Vec::new();
        print_entity_list(&[], "PEOPLE", &mut output).unwrap();
        let out = String::from_utf8(output).unwrap();
        assert!(out.contains("none detected"));
    }

    // ── confirm_entities ───────────────────────────────────────────────────

    #[test]
    fn test_confirm_entities_yes_mode() {
        let detected = EntityDetectionResult {
            people: vec![DetectedEntity {
                name: "Alice".to_owned(),
                confidence: 0.9,
                entity_type: EntityClass::Person,
                frequency: 5,
                signals: vec!["test".to_owned()],
            }],
            projects: vec![DetectedEntity {
                name: "Acme".to_owned(),
                confidence: 0.8,
                entity_type: EntityClass::Project,
                frequency: 4,
                signals: vec!["test".to_owned()],
            }],
            uncertain: vec![DetectedEntity {
                name: "Foo".to_owned(),
                confidence: 0.4,
                entity_type: EntityClass::Uncertain,
                frequency: 3,
                signals: vec!["test".to_owned()],
            }],
        };
        let result =
            confirm_entities(&detected, true, &mut "".as_bytes(), &mut Vec::new()).unwrap();
        assert_eq!(result.people, vec!["Alice"]);
        assert_eq!(result.projects, vec!["Acme"]);
    }

    #[test]
    fn test_confirm_entities_accept_all() {
        let detected = EntityDetectionResult {
            people: vec![DetectedEntity {
                name: "Alice".to_owned(),
                confidence: 0.9,
                entity_type: EntityClass::Person,
                frequency: 5,
                signals: vec!["test".to_owned()],
            }],
            projects: vec![],
            uncertain: vec![],
        };
        // choice = "" (accept), then "n" to "Add missing?"
        let input = "\nn\n";
        let result =
            confirm_entities(&detected, false, &mut input.as_bytes(), &mut Vec::new()).unwrap();
        assert!(result.people.contains(&"Alice".to_owned()));
    }

    #[test]
    fn test_confirm_entities_edit_reclassify_uncertain() {
        let detected = EntityDetectionResult {
            people: vec![],
            projects: vec![],
            uncertain: vec![
                DetectedEntity {
                    name: "Foo".to_owned(),
                    confidence: 0.4,
                    entity_type: EntityClass::Uncertain,
                    frequency: 3,
                    signals: vec!["test".to_owned()],
                },
                DetectedEntity {
                    name: "Bar".to_owned(),
                    confidence: 0.4,
                    entity_type: EntityClass::Uncertain,
                    frequency: 3,
                    signals: vec!["test".to_owned()],
                },
            ],
        };
        // choice=edit, Foo→p, Bar→s, no people removals, no project removals, n to add
        let input = "edit\np\ns\n\n\nn\n";
        let result =
            confirm_entities(&detected, false, &mut input.as_bytes(), &mut Vec::new()).unwrap();
        assert!(result.people.contains(&"Foo".to_owned()));
        assert!(!result.people.contains(&"Bar".to_owned()));
        assert!(!result.projects.contains(&"Bar".to_owned()));
    }

    #[test]
    fn test_confirm_entities_add_mode() {
        let detected = EntityDetectionResult {
            people: vec![],
            projects: vec![],
            uncertain: vec![],
        };
        let input = "add\nNewPerson\np\nNewProj\nr\n\n";
        let result =
            confirm_entities(&detected, false, &mut input.as_bytes(), &mut Vec::new()).unwrap();
        assert!(result.people.contains(&"NewPerson".to_owned()));
        assert!(result.projects.contains(&"NewProj".to_owned()));
    }

    // ── scan_for_detection fallback ────────────────────────────────────────

    #[test]
    fn test_scan_for_detection_fallback_to_all_readable() {
        let dir = tempdir().unwrap();
        std::fs::write(dir.path().join("one.md"), "hello").unwrap();
        std::fs::write(dir.path().join("two.txt"), "world").unwrap();
        std::fs::write(dir.path().join("code.py"), "import os").unwrap();
        std::fs::write(dir.path().join("app.js"), "console.log()").unwrap();
        let files = scan_for_detection(dir.path(), 10);
        let exts: std::collections::HashSet<_> = files
            .iter()
            .filter_map(|f| {
                f.extension()
                    .and_then(|e| e.to_str())
                    .map(|e| format!(".{e}"))
            })
            .collect();
        assert!(exts.contains(".py") || exts.contains(".js"));
    }

    #[test]
    fn test_scan_for_detection_max_files() {
        let dir = tempdir().unwrap();
        for i in 0..20 {
            std::fs::write(
                dir.path().join(format!("note{i}.md")),
                format!("content {i}"),
            )
            .unwrap();
        }
        let files = scan_for_detection(dir.path(), 5);
        assert!(files.len() <= 5);
    }
}

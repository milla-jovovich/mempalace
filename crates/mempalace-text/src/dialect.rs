//! AAAK Dialect encoder.
//!
//! Port of Python `mempalace/dialect.py`.
//!
//! FORMAT:
//!   Header:  FILE_NUM|PRIMARY_ENTITY|DATE|TITLE
//!   Zettel:  ZID:ENTITIES|topic_keywords|"key_quote"|WEIGHT|EMOTIONS|FLAGS
//!   Tunnel:  T:ZID<->ZID|label
//!   Arc:     ARC:emotion->emotion->emotion

use std::collections::{HashMap, HashSet};
use std::path::Path;
use std::sync::LazyLock;

use regex::Regex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

// ── Errors ────────────────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum Error {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON parse error: {0}")]
    Json(#[from] serde_json::Error),
}

// ── Constants (lazy-static) ───────────────────────────────────────────────────

/// Canonical emotion name → short code.
pub static EMOTION_CODES: LazyLock<HashMap<&'static str, &'static str>> = LazyLock::new(|| {
    let mut m = HashMap::new();
    m.insert("vulnerability", "vul");
    m.insert("vulnerable", "vul");
    m.insert("joy", "joy");
    m.insert("joyful", "joy");
    m.insert("fear", "fear");
    m.insert("mild_fear", "fear");
    m.insert("trust", "trust");
    m.insert("trust_building", "trust");
    m.insert("grief", "grief");
    m.insert("raw_grief", "grief");
    m.insert("wonder", "wonder");
    m.insert("philosophical_wonder", "wonder");
    m.insert("rage", "rage");
    m.insert("anger", "rage");
    m.insert("love", "love");
    m.insert("devotion", "love");
    m.insert("hope", "hope");
    m.insert("despair", "despair");
    m.insert("hopelessness", "despair");
    m.insert("peace", "peace");
    m.insert("relief", "relief");
    m.insert("humor", "humor");
    m.insert("dark_humor", "humor");
    m.insert("tenderness", "tender");
    m.insert("raw_honesty", "raw");
    m.insert("brutal_honesty", "raw");
    m.insert("self_doubt", "doubt");
    m.insert("anxiety", "anx");
    m.insert("exhaustion", "exhaust");
    m.insert("conviction", "convict");
    m.insert("quiet_passion", "passion");
    m.insert("warmth", "warmth");
    m.insert("curiosity", "curious");
    m.insert("gratitude", "grat");
    m.insert("frustration", "frust");
    m.insert("confusion", "confuse");
    m.insert("satisfaction", "satis");
    m.insert("excitement", "excite");
    m.insert("determination", "determ");
    m.insert("surprise", "surprise");
    m
});

/// Keywords that signal emotions in plain text.
static EMOTION_SIGNALS: LazyLock<HashMap<&'static str, &'static str>> = LazyLock::new(|| {
    let mut m = HashMap::new();
    m.insert("decided", "determ");
    m.insert("prefer", "convict");
    m.insert("worried", "anx");
    m.insert("excited", "excite");
    m.insert("frustrated", "frust");
    m.insert("confused", "confuse");
    m.insert("love", "love");
    m.insert("hate", "rage");
    m.insert("hope", "hope");
    m.insert("fear", "fear");
    m.insert("trust", "trust");
    m.insert("happy", "joy");
    m.insert("sad", "grief");
    m.insert("surprised", "surprise");
    m.insert("grateful", "grat");
    m.insert("curious", "curious");
    m.insert("wonder", "wonder");
    m.insert("anxious", "anx");
    m.insert("relieved", "relief");
    m.insert("satisf", "satis");
    m.insert("disappoint", "grief");
    m.insert("concern", "anx");
    m
});

/// Keywords that signal importance flags in plain text.
static FLAG_SIGNALS: LazyLock<HashMap<&'static str, &'static str>> = LazyLock::new(|| {
    let mut m = HashMap::new();
    m.insert("decided", "DECISION");
    m.insert("chose", "DECISION");
    m.insert("switched", "DECISION");
    m.insert("migrated", "DECISION");
    m.insert("replaced", "DECISION");
    m.insert("instead of", "DECISION");
    m.insert("because", "DECISION");
    m.insert("founded", "ORIGIN");
    m.insert("created", "ORIGIN");
    m.insert("started", "ORIGIN");
    m.insert("born", "ORIGIN");
    m.insert("launched", "ORIGIN");
    m.insert("first time", "ORIGIN");
    m.insert("core", "CORE");
    m.insert("fundamental", "CORE");
    m.insert("essential", "CORE");
    m.insert("principle", "CORE");
    m.insert("belief", "CORE");
    m.insert("always", "CORE");
    m.insert("never forget", "CORE");
    m.insert("turning point", "PIVOT");
    m.insert("changed everything", "PIVOT");
    m.insert("realized", "PIVOT");
    m.insert("breakthrough", "PIVOT");
    m.insert("epiphany", "PIVOT");
    m.insert("api", "TECHNICAL");
    m.insert("database", "TECHNICAL");
    m.insert("architecture", "TECHNICAL");
    m.insert("deploy", "TECHNICAL");
    m.insert("infrastructure", "TECHNICAL");
    m.insert("algorithm", "TECHNICAL");
    m.insert("framework", "TECHNICAL");
    m.insert("server", "TECHNICAL");
    m.insert("config", "TECHNICAL");
    m
});

/// Common stop/filler words for topic extraction.
static STOP_WORDS: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
        "do", "does", "did", "will", "would", "could", "should", "may", "might", "shall", "can",
        "to", "of", "in", "for", "on", "with", "at", "by", "from", "as", "into", "about",
        "between", "through", "during", "before", "after", "above", "below", "up", "down", "out",
        "off", "over", "under", "again", "further", "then", "once", "here", "there", "when",
        "where", "why", "how", "all", "each", "every", "both", "few", "more", "most", "other",
        "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very",
        "just", "don", "now", "and", "but", "or", "if", "while", "that", "this", "these", "those",
        "it", "its", "i", "we", "you", "he", "she", "they", "me", "him", "her", "us", "them", "my",
        "your", "his", "our", "their", "what", "which", "who", "whom", "also", "much", "many",
        "like", "because", "since", "get", "got", "use", "used", "using", "make", "made", "thing",
        "things", "way", "well", "really", "want", "need",
    ]
    .into()
});

// ── Compiled regexes ──────────────────────────────────────────────────────────

/// Tokenizer for topic extraction: `[a-zA-Z][a-zA-Z_-]{2,}`
static RE_TOPIC_WORDS: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[a-zA-Z][a-zA-Z_\-]{2,}").unwrap());

/// Sentence splitter: `[.!?\n]+`
static RE_SENTENCE_SPLIT: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[.!?\n]+").unwrap());

/// Strip non-alpha chars from a word
static RE_STRIP_NON_ALPHA: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[^a-zA-Z]").unwrap());

/// Double-quoted fragment (8–55 chars)
static RE_DOUBLE_QUOTED: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#""([^"]{8,55})""#).unwrap());

/// Single-quoted fragment preceded/followed by word boundary chars (8–55 chars)
static RE_SINGLE_QUOTED: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?:^|[\s(])'([^']{8,55})'(?:[\s.,;:!?)]|$)").unwrap());

/// "says/said/..." verb followed by quoted sentence (10–55 chars)
static RE_SAYS_PATTERN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r#"(?i)(?:says?|said|articulates?|reveals?|admits?|confesses?|asks?):\s*["']?([^.!?]{10,55})[.!?]"#,
    )
    .unwrap()
});

// ── Output types ──────────────────────────────────────────────────────────────

/// Decoded representation of an AAAK dialect string.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DecodedZettel {
    pub header: HashMap<String, String>,
    pub arc: String,
    pub zettels: Vec<String>,
    pub tunnels: Vec<String>,
}

/// Compression statistics from a text → AAAK conversion.
///
/// NOTE: AAAK is lossy summarisation. `size_ratio` shows how much shorter
/// the summary is, not a lossless compression ratio.
#[derive(Debug, Clone, Serialize)]
pub struct Stats {
    pub original_tokens_est: u32,
    pub summary_tokens_est: u32,
    pub size_ratio: f64,
    pub original_chars: usize,
    pub summary_chars: usize,
    pub note: &'static str,
}

// ── Dialect ───────────────────────────────────────────────────────────────────

/// AAAK Dialect encoder — works on plain text or structured zettel data.
#[derive(Debug, Clone)]
pub struct Dialect {
    entity_codes: HashMap<String, String>,
    skip_names: Vec<String>,
}

impl Dialect {
    // ── Constructors ─────────────────────────────────────────────────────────

    /// Create a new `Dialect`.
    ///
    /// `entities` maps full names → short codes, e.g. `{"Alice" → "ALC"}`.
    /// If empty, entities are auto-coded from first 3 chars (uppercase).
    /// `skip_names` are names to skip (fictional characters, etc.).
    pub fn new(entities: HashMap<String, String>, skip_names: Vec<String>) -> Self {
        let mut entity_codes = HashMap::new();
        for (name, code) in &entities {
            entity_codes.insert(name.clone(), code.clone());
            entity_codes.insert(name.to_lowercase(), code.clone());
        }
        let skip_names = skip_names.iter().map(|n| n.to_lowercase()).collect();
        Dialect {
            entity_codes,
            skip_names,
        }
    }

    /// Load entity mappings from a JSON config file.
    ///
    /// Config format:
    /// ```json
    /// {"entities": {"Alice": "ALC"}, "skip_names": ["Gandalf"]}
    /// ```
    pub fn from_config(path: &Path) -> Result<Self, Error> {
        let text = std::fs::read_to_string(path)?;
        let config: serde_json::Value = serde_json::from_str(&text)?;
        let entities = config["entities"]
            .as_object()
            .map(|m| {
                m.iter()
                    .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_owned())))
                    .collect::<HashMap<_, _>>()
            })
            .unwrap_or_default();
        let skip_names = config["skip_names"]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_owned()))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        Ok(Self::new(entities, skip_names))
    }

    /// Save current entity mappings to a JSON config file.
    pub fn save_config(&self, path: &Path) -> Result<(), Error> {
        let mut canonical: HashMap<String, String> = HashMap::new();
        let mut seen_codes: HashSet<String> = HashSet::new();
        for (name, code) in &self.entity_codes {
            if !seen_codes.contains(code.as_str()) {
                canonical.insert(name.clone(), code.clone());
                seen_codes.insert(code.clone());
            }
        }
        let config = serde_json::json!({
            "entities": canonical,
            "skip_names": self.skip_names,
        });
        let text = serde_json::to_string_pretty(&config)?;
        std::fs::write(path, text)?;
        Ok(())
    }

    // ── Encoding primitives ───────────────────────────────────────────────────

    /// Convert a person/entity name to its short code.
    ///
    /// Returns `None` if the name is in the skip list.
    /// Falls back to first 3 chars uppercase when no mapping exists.
    pub fn encode_entity(&self, name: &str) -> Option<String> {
        let name_lower = name.to_lowercase();
        if self
            .skip_names
            .iter()
            .any(|s| name_lower.contains(s.as_str()))
        {
            return None;
        }
        if let Some(code) = self.entity_codes.get(name) {
            return Some(code.clone());
        }
        if let Some(code) = self.entity_codes.get(&name_lower) {
            return Some(code.clone());
        }
        for (key, code) in &self.entity_codes {
            if name_lower.contains(&key.to_lowercase()) {
                return Some(code.clone());
            }
        }
        // Auto-code: first 3 chars uppercase
        let prefix: String = name.chars().take(3).collect::<String>().to_uppercase();
        Some(prefix)
    }

    /// Convert an emotion list to compact codes joined by `+`.
    pub fn encode_emotions(&self, emotions: &[&str]) -> String {
        let mut codes: Vec<&str> = Vec::new();
        for e in emotions {
            let code = EMOTION_CODES.get(e).copied().unwrap_or_else(|| {
                // fallback: first 4 chars — handled below since e is &str
                &e[..e.len().min(4)]
            });
            if !codes.contains(&code) {
                codes.push(code);
            }
        }
        codes[..codes.len().min(3)].join("+")
    }

    /// Extract flags from zettel metadata (JSON Value).
    pub fn get_flags(&self, zettel: &serde_json::Value) -> String {
        let mut flags: Vec<&str> = Vec::new();
        if zettel["origin_moment"].as_bool().unwrap_or(false) {
            flags.push("ORIGIN");
        }
        let sensitivity = zettel["sensitivity"].as_str().unwrap_or("");
        if sensitivity.to_uppercase().starts_with("MAXIMUM") {
            flags.push("SENSITIVE");
        }
        let notes = zettel["notes"].as_str().unwrap_or("").to_lowercase();
        if notes.contains("foundational pillar") || notes.contains("core") {
            flags.push("CORE");
        }
        let origin_label = zettel["origin_label"].as_str().unwrap_or("").to_lowercase();
        if notes.contains("genesis") || origin_label.contains("genesis") {
            flags.push("GENESIS");
        }
        if notes.contains("pivot") {
            flags.push("PIVOT");
        }
        flags.join("+")
    }

    // ── Plain-text compression ────────────────────────────────────────────────

    fn detect_emotions(&self, text: &str) -> Vec<String> {
        let text_lower = text.to_lowercase();
        let mut detected: Vec<String> = Vec::new();
        let mut seen: HashSet<String> = HashSet::new();
        for (keyword, code) in EMOTION_SIGNALS.iter() {
            if text_lower.contains(keyword) && !seen.contains(*code) {
                detected.push(code.to_string());
                seen.insert(code.to_string());
            }
        }
        detected.truncate(3);
        detected
    }

    fn detect_flags(&self, text: &str) -> Vec<String> {
        let text_lower = text.to_lowercase();
        let mut detected: Vec<String> = Vec::new();
        let mut seen: HashSet<String> = HashSet::new();
        for (keyword, flag) in FLAG_SIGNALS.iter() {
            if text_lower.contains(keyword) && !seen.contains(*flag) {
                detected.push(flag.to_string());
                seen.insert(flag.to_string());
            }
        }
        detected.truncate(3);
        detected
    }

    fn extract_topics(&self, text: &str, max_topics: usize) -> Vec<String> {
        let words: Vec<&str> = RE_TOPIC_WORDS.find_iter(text).map(|m| m.as_str()).collect();

        let mut freq: HashMap<String, i64> = HashMap::new();
        for w in &words {
            let w_lower = w.to_lowercase();
            if STOP_WORDS.contains(w_lower.as_str()) || w_lower.len() < 3 {
                continue;
            }
            *freq.entry(w_lower).or_insert(0) += 1;
        }

        // Boost proper nouns and technical terms
        for w in &words {
            let w_lower = w.to_lowercase();
            if STOP_WORDS.contains(w_lower.as_str()) {
                continue;
            }
            if let Some(first) = w.chars().next() {
                if first.is_uppercase() {
                    if let Some(v) = freq.get_mut(&w_lower) {
                        *v += 2;
                    }
                }
            }
            // CamelCase or has underscore/hyphen
            let has_upper_after_first = w.chars().skip(1).any(|c| c.is_uppercase());
            if w.contains('_') || w.contains('-') || has_upper_after_first {
                if let Some(v) = freq.get_mut(&w_lower) {
                    *v += 2;
                }
            }
        }

        let mut ranked: Vec<(String, i64)> = freq.into_iter().collect();
        ranked.sort_by(|a, b| b.1.cmp(&a.1));
        ranked
            .into_iter()
            .take(max_topics)
            .map(|(w, _)| w)
            .collect()
    }

    fn extract_key_sentence(&self, text: &str) -> String {
        let sentences: Vec<&str> = RE_SENTENCE_SPLIT
            .split(text)
            .map(str::trim)
            .filter(|s| s.len() > 10)
            .collect();

        if sentences.is_empty() {
            return String::new();
        }

        let decision_words: HashSet<&str> = [
            "decided",
            "because",
            "instead",
            "prefer",
            "switched",
            "chose",
            "realized",
            "important",
            "key",
            "critical",
            "discovered",
            "learned",
            "conclusion",
            "solution",
            "reason",
            "why",
            "breakthrough",
            "insight",
        ]
        .into();

        let mut scored: Vec<(i64, &str)> = sentences
            .iter()
            .map(|s| {
                let mut score: i64 = 0;
                let s_lower = s.to_lowercase();
                for w in &decision_words {
                    if s_lower.contains(w) {
                        score += 2;
                    }
                }
                if s.len() < 80 {
                    score += 1;
                }
                if s.len() < 40 {
                    score += 1;
                }
                if s.len() > 150 {
                    score -= 2;
                }
                (score, *s)
            })
            .collect();

        scored.sort_by(|a, b| b.0.cmp(&a.0));
        let best = scored[0].1;
        if best.len() > 55 {
            format!("{}...", &best[..52])
        } else {
            best.to_owned()
        }
    }

    fn detect_entities_in_text(&self, text: &str) -> Vec<String> {
        let text_lower = text.to_lowercase();
        let mut found: Vec<String> = Vec::new();

        // Check known entities
        for (name, code) in &self.entity_codes {
            // Only use mixed-case (canonical) keys, not the lowercase duplicates
            if !name.chars().all(|c| c.is_lowercase() || !c.is_alphabetic()) {
                if text_lower.contains(&name.to_lowercase()) && !found.contains(code) {
                    found.push(code.clone());
                }
            }
        }
        if !found.is_empty() {
            return found;
        }

        // Fallback: capitalized words that look like names (not sentence-start)
        let words: Vec<&str> = text.split_whitespace().collect();
        for (i, w) in words.iter().enumerate() {
            let clean = RE_STRIP_NON_ALPHA.replace_all(w, "").into_owned();
            if clean.len() >= 2
                && clean
                    .chars()
                    .next()
                    .map(|c| c.is_uppercase())
                    .unwrap_or(false)
                && clean[1..].chars().all(|c| c.is_lowercase())
                && i > 0
                && !STOP_WORDS.contains(clean.to_lowercase().as_str())
            {
                let code: String = clean.chars().take(3).collect::<String>().to_uppercase();
                if !found.contains(&code) {
                    found.push(code);
                }
                if found.len() >= 3 {
                    break;
                }
            }
        }
        found
    }

    /// Summarise plain text into AAAK Dialect format.
    ///
    /// Extracts entities, topics, a key sentence, emotions, and flags from
    /// the input. This is **lossy** — the original text cannot be reconstructed.
    ///
    /// `metadata` keys: `source_file`, `wing`, `room`, `date`.
    pub fn compress(&self, text: &str, metadata: Option<&HashMap<String, String>>) -> String {
        let empty = HashMap::new();
        let metadata = metadata.unwrap_or(&empty);

        let entities = self.detect_entities_in_text(text);
        let entity_str = if entities.is_empty() {
            "???".to_owned()
        } else {
            entities[..entities.len().min(3)].join("+")
        };

        let topics = self.extract_topics(text, 3);
        let topic_str = if topics.is_empty() {
            "misc".to_owned()
        } else {
            topics[..topics.len().min(3)].join("_")
        };

        let quote = self.extract_key_sentence(text);
        let quote_part = if quote.is_empty() {
            String::new()
        } else {
            format!("\"{}\"", quote)
        };

        let emotions = self.detect_emotions(text);
        let emotion_str = emotions.join("+");

        let flags = self.detect_flags(text);
        let flag_str = flags.join("+");

        let source = metadata
            .get("source_file")
            .map(|s| s.as_str())
            .unwrap_or("");
        let wing = metadata.get("wing").map(|s| s.as_str()).unwrap_or("");
        let room = metadata.get("room").map(|s| s.as_str()).unwrap_or("");
        let date = metadata.get("date").map(|s| s.as_str()).unwrap_or("");

        let mut lines: Vec<String> = Vec::new();

        // Header line (if we have metadata)
        if !source.is_empty() || !wing.is_empty() {
            let stem = if source.is_empty() {
                "?".to_owned()
            } else {
                Path::new(source)
                    .file_stem()
                    .and_then(|s| s.to_str())
                    .unwrap_or("?")
                    .to_owned()
            };
            let header = format!(
                "{}|{}|{}|{}",
                if wing.is_empty() { "?" } else { wing },
                if room.is_empty() { "?" } else { room },
                if date.is_empty() { "?" } else { date },
                stem
            );
            lines.push(header);
        }

        // Content line
        let mut parts: Vec<String> = vec![format!("0:{}", entity_str), topic_str];
        if !quote_part.is_empty() {
            parts.push(quote_part);
        }
        if !emotion_str.is_empty() {
            parts.push(emotion_str);
        }
        if !flag_str.is_empty() {
            parts.push(flag_str);
        }
        lines.push(parts.join("|"));

        lines.join("\n")
    }

    // ── Zettel-based encoding ─────────────────────────────────────────────────

    /// Pull the most important quote fragment from zettel content.
    pub fn extract_key_quote(&self, zettel: &serde_json::Value) -> String {
        let content = zettel["content"].as_str().unwrap_or("");
        let origin = zettel["origin_label"].as_str().unwrap_or("");
        let notes = zettel["notes"].as_str().unwrap_or("");
        let title = zettel["title"].as_str().unwrap_or("");
        let all_text = format!("{} {} {}", content, origin, notes);

        let mut quotes: Vec<String> = Vec::new();

        // Double-quoted fragments
        for cap in RE_DOUBLE_QUOTED.captures_iter(&all_text) {
            quotes.push(cap[1].to_owned());
        }
        // Single-quoted fragments
        for cap in RE_SINGLE_QUOTED.captures_iter(&all_text) {
            quotes.push(cap[1].to_owned());
        }
        // Speech-verb patterns
        for cap in RE_SAYS_PATTERN.captures_iter(&all_text) {
            quotes.push(cap[1].to_owned());
        }

        if !quotes.is_empty() {
            // Deduplicate
            let mut seen: HashSet<String> = HashSet::new();
            let unique: Vec<String> = quotes
                .into_iter()
                .filter_map(|q| {
                    let q = q.trim().to_owned();
                    if !seen.contains(&q) && q.len() >= 8 {
                        seen.insert(q.clone());
                        Some(q)
                    } else {
                        None
                    }
                })
                .collect();

            if !unique.is_empty() {
                let emotional_words: HashSet<&str> = [
                    "love",
                    "fear",
                    "remember",
                    "soul",
                    "feel",
                    "stupid",
                    "scared",
                    "beautiful",
                    "destroy",
                    "respect",
                    "trust",
                    "consciousness",
                    "alive",
                    "forget",
                    "waiting",
                    "peace",
                    "matter",
                    "real",
                    "guilt",
                    "escape",
                    "rest",
                    "hope",
                    "dream",
                    "lost",
                    "found",
                ]
                .into();

                let mut scored: Vec<(i64, String)> = unique
                    .into_iter()
                    .map(|q| {
                        let mut score: i64 = 0;
                        let q_lower = q.to_lowercase();
                        if q.chars().next().map(|c| c.is_uppercase()).unwrap_or(false)
                            || q.starts_with("I ")
                        {
                            score += 2;
                        }
                        for w in &emotional_words {
                            if q_lower.contains(w) {
                                score += 2;
                            }
                        }
                        if q.len() > 20 {
                            score += 1;
                        }
                        if q.starts_with("The ") || q.starts_with("This ") || q.starts_with("She ")
                        {
                            score -= 2;
                        }
                        (score, q)
                    })
                    .collect();
                scored.sort_by(|a, b| b.0.cmp(&a.0));
                return scored
                    .into_iter()
                    .next()
                    .map(|(_, q)| q)
                    .unwrap_or_default();
            }
        }

        if title.contains(" - ") {
            let after = title.splitn(2, " - ").nth(1).unwrap_or("");
            return after.chars().take(45).collect();
        }
        String::new()
    }

    /// Encode a single zettel into AAAK Dialect.
    pub fn encode_zettel(&self, zettel: &serde_json::Value) -> String {
        let id = zettel["id"].as_str().unwrap_or("000");
        let zid = id.rsplit('-').next().unwrap_or(id);

        let mut entity_codes: Vec<String> = zettel["people"]
            .as_array()
            .map(|arr| {
                arr.iter()
                    .filter_map(|p| p.as_str().and_then(|name| self.encode_entity(name)))
                    .collect()
            })
            .unwrap_or_default();
        entity_codes.sort();
        entity_codes.dedup();
        if entity_codes.is_empty() {
            entity_codes.push("???".to_owned());
        }
        let entities = entity_codes.join("+");

        let topics: Vec<&str> = zettel["topics"]
            .as_array()
            .map(|arr| arr.iter().filter_map(|v| v.as_str()).collect())
            .unwrap_or_default();
        let topic_str = if topics.is_empty() {
            "misc".to_owned()
        } else {
            topics[..topics.len().min(2)].join("_")
        };

        let quote = self.extract_key_quote(zettel);
        let quote_part = if quote.is_empty() {
            String::new()
        } else {
            format!("\"{}\"", quote)
        };

        let weight = zettel["emotional_weight"].as_f64().unwrap_or(0.5);
        let tone: Vec<&str> = zettel["emotional_tone"]
            .as_array()
            .map(|arr| arr.iter().filter_map(|v| v.as_str()).collect())
            .unwrap_or_default();
        let emotions = self.encode_emotions(&tone);
        let flags = self.get_flags(zettel);

        let mut parts: Vec<String> = vec![format!("{}:{}", zid, entities), topic_str];
        if !quote_part.is_empty() {
            parts.push(quote_part);
        }
        parts.push(weight.to_string());
        if !emotions.is_empty() {
            parts.push(emotions);
        }
        if !flags.is_empty() {
            parts.push(flags);
        }

        parts.join("|")
    }

    /// Encode a tunnel connection.
    pub fn encode_tunnel(&self, tunnel: &serde_json::Value) -> String {
        let from = tunnel["from"].as_str().unwrap_or("000");
        let to = tunnel["to"].as_str().unwrap_or("000");
        let from_id = from.rsplit('-').next().unwrap_or(from);
        let to_id = to.rsplit('-').next().unwrap_or(to);
        let label = tunnel["label"].as_str().unwrap_or("");
        let short_label = if label.contains(':') {
            label.splitn(2, ':').next().unwrap_or(label)
        } else {
            &label[..label.len().min(30)]
        };
        format!("T:{}<->{}", from_id, to_id) + "|" + short_label
    }

    /// Encode an entire zettel JSON file into AAAK Dialect.
    pub fn encode_file(&self, zettel_json: &serde_json::Value) -> String {
        let mut lines: Vec<String> = Vec::new();

        let source = zettel_json["source_file"].as_str().unwrap_or("unknown");
        let file_num = if source.contains('-') {
            source.splitn(2, '-').next().unwrap_or("000")
        } else {
            "000"
        };
        let date = zettel_json["zettels"]
            .as_array()
            .and_then(|arr| arr.first())
            .and_then(|z| z["date_context"].as_str())
            .unwrap_or("unknown");

        let mut all_people: Vec<String> = zettel_json["zettels"]
            .as_array()
            .map(|arr| {
                let mut codes = Vec::new();
                for z in arr {
                    if let Some(people) = z["people"].as_array() {
                        for p in people {
                            if let Some(name) = p.as_str() {
                                if let Some(code) = self.encode_entity(name) {
                                    codes.push(code);
                                }
                            }
                        }
                    }
                }
                codes
            })
            .unwrap_or_default();
        all_people.sort();
        all_people.dedup();
        if all_people.is_empty() {
            all_people.push("???".to_owned());
        }
        let primary = all_people[..all_people.len().min(3)].join("+");

        let title = if source.contains('-') {
            source
                .replace(".txt", "")
                .splitn(2, '-')
                .nth(1)
                .unwrap_or(source)
                .trim()
                .to_owned()
        } else {
            source.to_owned()
        };
        lines.push(format!("{}|{}|{}|{}", file_num, primary, date, title));

        let arc = zettel_json["emotional_arc"].as_str().unwrap_or("");
        if !arc.is_empty() {
            lines.push(format!("ARC:{}", arc));
        }

        if let Some(zettels) = zettel_json["zettels"].as_array() {
            for z in zettels {
                lines.push(self.encode_zettel(z));
            }
        }

        if let Some(tunnels) = zettel_json["tunnels"].as_array() {
            for t in tunnels {
                lines.push(self.encode_tunnel(t));
            }
        }

        lines.join("\n")
    }

    // ── File-based compression ────────────────────────────────────────────────

    /// Read a zettel JSON file and compress it to AAAK Dialect.
    ///
    /// If `output` is `Some`, the result is also written to that path.
    pub fn compress_file(
        &self,
        zettel_json_path: &Path,
        output: Option<&Path>,
    ) -> Result<String, Error> {
        let text = std::fs::read_to_string(zettel_json_path)?;
        let data: serde_json::Value = serde_json::from_str(&text)?;
        let dialect = self.encode_file(&data);
        if let Some(out) = output {
            std::fs::write(out, &dialect)?;
        }
        Ok(dialect)
    }

    /// Compress ALL zettel JSON files in a directory into a single AAAK Dialect string.
    pub fn compress_all(&self, zettel_dir: &Path, output: Option<&Path>) -> Result<String, Error> {
        let mut all_dialect: Vec<String> = Vec::new();
        let mut entries: Vec<_> = std::fs::read_dir(zettel_dir)?
            .filter_map(|e| e.ok())
            .filter(|e| {
                e.path()
                    .extension()
                    .and_then(|x| x.to_str())
                    .map(|x| x == "json")
                    .unwrap_or(false)
            })
            .collect();
        entries.sort_by_key(|e| e.file_name());

        for entry in entries {
            let text = std::fs::read_to_string(entry.path())?;
            let data: serde_json::Value = serde_json::from_str(&text)?;
            let dialect = self.encode_file(&data);
            all_dialect.push(dialect);
            all_dialect.push("---".to_owned());
        }

        let combined = all_dialect.join("\n");
        if let Some(out) = output {
            std::fs::write(out, &combined)?;
        }
        Ok(combined)
    }

    // ── Layer 1 generation ────────────────────────────────────────────────────

    /// Auto-generate a Layer 1 wake-up file from all processed zettel files.
    ///
    /// Pulls highest-weight moments (>= `weight_threshold`) and any with
    /// ORIGIN/CORE/GENESIS flags. Groups them by date into MOMENTS sections.
    #[allow(clippy::too_many_arguments)]
    pub fn generate_layer1(
        &self,
        zettel_dir: &Path,
        output_path: Option<&Path>,
        identity_sections: Option<&HashMap<String, Vec<String>>>,
        weight_threshold: f64,
    ) -> Result<String, Error> {
        // Collect essential moments
        let mut essential: Vec<(serde_json::Value, String, String)> = Vec::new();

        let mut entries: Vec<_> = std::fs::read_dir(zettel_dir)?
            .filter_map(|e| e.ok())
            .filter(|e| {
                e.path()
                    .extension()
                    .and_then(|x| x.to_str())
                    .map(|x| x == "json")
                    .unwrap_or(false)
            })
            .collect();
        entries.sort_by_key(|e| e.file_name());

        for entry in &entries {
            let text = std::fs::read_to_string(entry.path())?;
            let data: serde_json::Value = serde_json::from_str(&text)?;

            let fname = entry
                .path()
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("")
                .to_owned();
            let file_num = fname.replace("file_", "").replace(".json", "").to_owned();
            let source_date = data["zettels"]
                .as_array()
                .and_then(|arr| arr.first())
                .and_then(|z| z["date_context"].as_str())
                .unwrap_or("unknown")
                .to_owned();

            if let Some(zettels) = data["zettels"].as_array() {
                for z in zettels {
                    let weight = z["emotional_weight"].as_f64().unwrap_or(0.0);
                    let is_origin = z["origin_moment"].as_bool().unwrap_or(false);
                    let flags = self.get_flags(z);
                    let has_key_flag = ["ORIGIN", "CORE", "GENESIS"]
                        .iter()
                        .any(|f| flags.contains(f));

                    if weight >= weight_threshold || is_origin || has_key_flag {
                        essential.push((z.clone(), file_num.clone(), source_date.clone()));
                    }
                }
            }
        }

        // Collect all tunnels
        let mut all_tunnels: Vec<serde_json::Value> = Vec::new();
        for entry in &entries {
            let text = std::fs::read_to_string(entry.path())?;
            let data: serde_json::Value = serde_json::from_str(&text)?;
            if let Some(tunnels) = data["tunnels"].as_array() {
                all_tunnels.extend(tunnels.iter().cloned());
            }
        }

        // Sort by weight descending
        essential.sort_by(|a, b| {
            let wa = a.0["emotional_weight"].as_f64().unwrap_or(0.0);
            let wb = b.0["emotional_weight"].as_f64().unwrap_or(0.0);
            wb.partial_cmp(&wa).unwrap_or(std::cmp::Ordering::Equal)
        });

        // Group by date
        let mut by_date: HashMap<String, Vec<(serde_json::Value, String)>> = HashMap::new();
        for (z, fnum, sdate) in essential {
            let key = sdate
                .splitn(2, ',')
                .next()
                .unwrap_or(&sdate)
                .trim()
                .to_owned();
            by_date.entry(key).or_default().push((z, fnum));
        }

        let mut lines: Vec<String> = Vec::new();
        lines.push("## LAYER 1 -- ESSENTIAL STORY".to_owned());
        lines.push(format!(
            "## Auto-generated from zettel files. Updated {}.",
            today_string()
        ));
        lines.push(String::new());

        if let Some(sections) = identity_sections {
            let mut sorted_keys: Vec<&String> = sections.keys().collect();
            sorted_keys.sort();
            for key in sorted_keys {
                if let Some(section_lines) = sections.get(key) {
                    lines.push(format!("={}=", key));
                    lines.extend(section_lines.iter().cloned());
                    lines.push(String::new());
                }
            }
        }

        let mut date_keys: Vec<String> = by_date.keys().cloned().collect();
        date_keys.sort();

        for date_key in date_keys {
            lines.push(format!("=MOMENTS[{}]=", date_key));
            let group = by_date.get(&date_key).cloned().unwrap_or_default();
            for (z, _fnum) in group {
                let mut entities: Vec<String> = Vec::new();
                if let Some(people) = z["people"].as_array() {
                    for p in people {
                        if let Some(name) = p.as_str() {
                            if let Some(code) = self.encode_entity(name) {
                                entities.push(code);
                            }
                        }
                    }
                }
                if entities.is_empty() {
                    entities.push("???".to_owned());
                }
                entities.sort();
                entities.dedup();
                let ent_str = entities.join("+");

                let quote = self.extract_key_quote(&z);
                let weight = z["emotional_weight"].as_f64().unwrap_or(0.5);
                let flags = self.get_flags(&z);
                let sensitivity = z["sensitivity"].as_str().unwrap_or("");
                let title = z["title"].as_str().unwrap_or("");

                let mut parts: Vec<String> = vec![ent_str];
                let hint = if title.contains(" - ") {
                    title
                        .splitn(2, " - ")
                        .nth(1)
                        .unwrap_or("")
                        .chars()
                        .take(30)
                        .collect::<String>()
                } else {
                    let topics: Vec<&str> = z["topics"]
                        .as_array()
                        .map(|arr| arr.iter().filter_map(|v| v.as_str()).take(2).collect())
                        .unwrap_or_default();
                    topics.join("_")
                };
                if !hint.is_empty() {
                    parts.push(hint.clone());
                }
                if !quote.is_empty() && quote != hint && quote != title {
                    parts.push(format!("\"{}\"", quote));
                }
                if !sensitivity.is_empty() && !flags.contains("SENSITIVE") {
                    parts.push("SENSITIVE".to_owned());
                }
                parts.push(weight.to_string());
                if !flags.is_empty() {
                    parts.push(flags);
                }

                lines.push(parts.join("|"));
            }
            lines.push(String::new());
        }

        if !all_tunnels.is_empty() {
            lines.push("=TUNNELS=".to_owned());
            for t in all_tunnels.iter().take(8) {
                let label = t["label"].as_str().unwrap_or("");
                let short = if label.contains(':') {
                    label.splitn(2, ':').next().unwrap_or(label)
                } else {
                    &label[..label.len().min(40)]
                };
                lines.push(short.to_owned());
            }
            lines.push(String::new());
        }

        let result = lines.join("\n");

        if let Some(out) = output_path {
            std::fs::write(out, &result)?;
        }

        Ok(result)
    }

    // ── Decoding ──────────────────────────────────────────────────────────────

    /// Parse an AAAK Dialect string back into a readable summary.
    pub fn decode(&self, dialect_text: &str) -> Result<DecodedZettel, Error> {
        let mut result = DecodedZettel {
            header: HashMap::new(),
            arc: String::new(),
            zettels: Vec::new(),
            tunnels: Vec::new(),
        };

        for line in dialect_text.trim().lines() {
            if line.starts_with("ARC:") {
                result.arc = line[4..].to_owned();
            } else if line.starts_with("T:") {
                result.tunnels.push(line.to_owned());
            } else if line.contains('|')
                && line
                    .split('|')
                    .next()
                    .map(|p| p.contains(':'))
                    .unwrap_or(false)
            {
                result.zettels.push(line.to_owned());
            } else if line.contains('|') {
                let parts: Vec<&str> = line.splitn(5, '|').collect();
                let mut header = HashMap::new();
                header.insert(
                    "file".to_owned(),
                    parts.first().copied().unwrap_or("").to_owned(),
                );
                header.insert(
                    "entities".to_owned(),
                    parts.get(1).copied().unwrap_or("").to_owned(),
                );
                header.insert(
                    "date".to_owned(),
                    parts.get(2).copied().unwrap_or("").to_owned(),
                );
                header.insert(
                    "title".to_owned(),
                    parts.get(3).copied().unwrap_or("").to_owned(),
                );
                result.header = header;
            }
        }

        Ok(result)
    }

    // ── Stats ─────────────────────────────────────────────────────────────────

    /// Estimate token count using word-based heuristic (~1.3 tokens per word).
    ///
    /// This is an approximation. For accurate counts, use a real tokeniser
    /// like tiktoken. The old `len(text)/3` heuristic was wildly inaccurate.
    pub fn count_tokens(text: &str) -> u32 {
        let words = text.split_whitespace().count();
        (words as f64 * 1.3) as u32
    }

    /// Get size comparison stats for a text → AAAK conversion.
    ///
    /// NOTE: AAAK is lossy summarisation. `size_ratio` reflects how much
    /// shorter the summary is, not a lossless compression ratio.
    pub fn compression_stats(&self, original_text: &str, compressed: &str) -> Stats {
        let orig_tokens = Self::count_tokens(original_text);
        let comp_tokens = Self::count_tokens(compressed);
        let size_ratio = ((orig_tokens as f64 / comp_tokens.max(1) as f64) * 10.0).round() / 10.0;
        Stats {
            original_tokens_est: orig_tokens,
            summary_tokens_est: comp_tokens,
            size_ratio,
            original_chars: original_text.len(),
            summary_chars: compressed.len(),
            note: "Estimates only. Use tiktoken for accurate counts. AAAK is lossy.",
        }
    }
}

// ── Date helper ───────────────────────────────────────────────────────────────

fn is_leap_year(year: u32) -> bool {
    (year % 4 == 0 && year % 100 != 0) || (year % 400 == 0)
}

fn today_string() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    let mut days = (secs / 86400) as u32;
    let mut year = 1970u32;
    loop {
        let days_in_year = if is_leap_year(year) { 366 } else { 365 };
        if days < days_in_year {
            break;
        }
        days -= days_in_year;
        year += 1;
    }
    let leap = is_leap_year(year);
    let month_days: [u32; 12] = [
        31,
        if leap { 29 } else { 28 },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    let mut month = 1u32;
    let mut remaining = days;
    for &md in &month_days {
        if remaining < md {
            break;
        }
        remaining -= md;
        month += 1;
    }
    let day = remaining + 1;
    format!("{}-{:02}-{:02}", year, month, day)
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;

    // ── Plain text compression ────────────────────────────────────────────────

    #[test]
    fn test_compress_basic() {
        let d = Dialect::new(HashMap::new(), vec![]);
        let result = d.compress(
            "We decided to use GraphQL instead of REST for the API layer.",
            None,
        );
        assert!(!result.is_empty());
        assert!(
            result.contains('|'),
            "AAAK format uses pipe-separated fields"
        );
    }

    #[test]
    fn test_compress_with_metadata() {
        let d = Dialect::new(HashMap::new(), vec![]);
        let mut meta = HashMap::new();
        meta.insert("wing".to_owned(), "project".to_owned());
        meta.insert("room".to_owned(), "backend".to_owned());
        meta.insert("source_file".to_owned(), "auth.py".to_owned());
        let result = d.compress("Authentication now uses JWT tokens.", Some(&meta));
        assert!(result.contains("project"));
        assert!(result.contains("backend"));
    }

    #[test]
    fn test_compress_produces_entity_codes() {
        let mut entities = HashMap::new();
        entities.insert("Alice".to_owned(), "ALC".to_owned());
        entities.insert("Bob".to_owned(), "BOB".to_owned());
        let d = Dialect::new(entities, vec![]);
        let result = d.compress("Alice told Bob about the new deployment strategy.", None);
        assert!(result.contains("ALC") || result.contains("BOB"));
    }

    #[test]
    fn test_compress_empty_text() {
        let d = Dialect::new(HashMap::new(), vec![]);
        let result = d.compress("", None);
        // Just verify it returns a String without panicking
        let _ = result;
    }

    // ── Entity detection ──────────────────────────────────────────────────────

    #[test]
    fn test_known_entities() {
        let mut entities = HashMap::new();
        entities.insert("Alice".to_owned(), "ALC".to_owned());
        let d = Dialect::new(entities, vec![]);
        let found = d.detect_entities_in_text("Alice went to the store.");
        assert!(found.contains(&"ALC".to_owned()));
    }

    #[test]
    fn test_auto_code_unknown_entities() {
        let d = Dialect::new(HashMap::new(), vec![]);
        let found = d.detect_entities_in_text("I spoke with Bernardo about the project today.");
        assert!(found.iter().any(|code| code.len() == 3));
    }

    #[test]
    fn test_skip_names() {
        let mut entities = HashMap::new();
        entities.insert("Gandalf".to_owned(), "GAN".to_owned());
        let d = Dialect::new(entities, vec!["Gandalf".to_owned()]);
        let code = d.encode_entity("Gandalf");
        assert_eq!(code, None);
    }

    // ── Emotion detection ─────────────────────────────────────────────────────

    #[test]
    fn test_detect_emotions() {
        let d = Dialect::new(HashMap::new(), vec![]);
        let emotions = d.detect_emotions("I'm really excited and happy about this breakthrough!");
        assert!(!emotions.is_empty());
    }

    #[test]
    fn test_max_three_emotions() {
        let d = Dialect::new(HashMap::new(), vec![]);
        let text = "I feel scared, happy, angry, surprised, disgusted, and confused.";
        let emotions = d.detect_emotions(text);
        assert!(emotions.len() <= 3);
    }

    // ── Topic extraction ──────────────────────────────────────────────────────

    #[test]
    fn test_extract_topics() {
        let d = Dialect::new(HashMap::new(), vec![]);
        let topics = d.extract_topics(
            "The Python authentication server uses PostgreSQL for storage \
             and Redis for caching sessions.",
            3,
        );
        assert!(!topics.is_empty());
        assert!(topics.len() <= 3);
    }

    #[test]
    fn test_boosts_technical_terms() {
        let d = Dialect::new(HashMap::new(), vec![]);
        let topics = d.extract_topics(
            "GraphQL vs REST: we chose GraphQL for the new API endpoint.",
            3,
        );
        let topic_lower: Vec<String> = topics.iter().map(|t| t.to_lowercase()).collect();
        assert!(topic_lower.contains(&"graphql".to_owned()));
    }

    // ── Key sentence extraction ───────────────────────────────────────────────

    #[test]
    fn test_extract_key_sentence() {
        let d = Dialect::new(HashMap::new(), vec![]);
        let text = "The server runs on port 3000. \
                    We decided to use PostgreSQL instead of MongoDB. \
                    The config file needs updating.";
        let key = d.extract_key_sentence(text);
        assert!(key.to_lowercase().contains("decided") || key.to_lowercase().contains("instead"));
    }

    #[test]
    fn test_truncates_long_sentences() {
        let d = Dialect::new(HashMap::new(), vec![]);
        let text = "a ".repeat(100);
        let key = d.extract_key_sentence(&text);
        assert!(key.len() <= 55);
    }

    // ── Compression stats ─────────────────────────────────────────────────────

    #[test]
    fn test_stats() {
        let d = Dialect::new(HashMap::new(), vec![]);
        let original = "We decided to use GraphQL instead of REST. ".repeat(10);
        let compressed = d.compress(&original, None);
        let stats = d.compression_stats(&original, &compressed);
        assert!(stats.size_ratio > 1.0);
        assert!(stats.original_chars > stats.summary_chars);
    }

    #[test]
    fn test_count_tokens() {
        assert_eq!(Dialect::count_tokens("hello world"), 2);
    }

    // ── Zettel encoding ───────────────────────────────────────────────────────

    #[test]
    fn test_encode_zettel() {
        let mut entities = HashMap::new();
        entities.insert("Alice".to_owned(), "ALC".to_owned());
        let d = Dialect::new(entities, vec![]);
        let zettel = serde_json::json!({
            "id": "zettel-001",
            "people": ["Alice"],
            "topics": ["memory", "ai"],
            "content": "She said \"I want to remember everything\"",
            "emotional_weight": 0.9,
            "emotional_tone": ["joy"],
            "origin_moment": false,
            "sensitivity": "",
            "notes": "",
            "origin_label": "",
            "title": "Test - Memory Discussion",
        });
        let result = d.encode_zettel(&zettel);
        assert!(result.contains("ALC"));
        assert!(result.contains("memory"));
    }

    #[test]
    fn test_encode_tunnel() {
        let d = Dialect::new(HashMap::new(), vec![]);
        let tunnel = serde_json::json!({"from": "zettel-001", "to": "zettel-002", "label": "follows: temporal"});
        let result = d.encode_tunnel(&tunnel);
        assert!(result.contains("T:"));
        assert!(result.contains("001"));
        assert!(result.contains("002"));
    }

    // ── Decode ────────────────────────────────────────────────────────────────

    #[test]
    fn test_decode_roundtrip() {
        let d = Dialect::new(HashMap::new(), vec![]);
        let encoded =
            "001|ALC+BOB|2025-01-01|test_title\nARC:journey\n001:ALC|memory_ai|\"test quote\"|0.9|joy";
        let decoded = d.decode(encoded).unwrap();
        assert_eq!(decoded.header.get("file").map(|s| s.as_str()), Some("001"));
        assert_eq!(decoded.arc, "journey");
        assert_eq!(decoded.zettels.len(), 1);
    }
}

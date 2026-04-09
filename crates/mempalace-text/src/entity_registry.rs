//! Entity registry with Wikipedia lookup.
//!
//! Port of Python `mempalace/entity_registry.py`.

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use regex::Regex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

// ── Errors ─────────────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum Error {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("Network error: {0}")]
    Network(String),
}

// ── Common English words ────────────────────────────────────────────────────

pub static COMMON_ENGLISH_WORDS: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        // Words that are also common personal names
        "ever",
        "grace",
        "will",
        "bill",
        "mark",
        "april",
        "may",
        "june",
        "joy",
        "hope",
        "faith",
        "chance",
        "chase",
        "hunter",
        "dash",
        "flash",
        "star",
        "sky",
        "river",
        "brook",
        "lane",
        "art",
        "clay",
        "gil",
        "nat",
        "max",
        "rex",
        "ray",
        "jay",
        "rose",
        "violet",
        "lily",
        "ivy",
        "ash",
        "reed",
        "sage",
        // Words that look like names at start of sentence
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "january",
        "february",
        "march",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ]
    .into()
});

// ── Context pattern lists ───────────────────────────────────────────────────

pub static PERSON_CONTEXT_PATTERNS: LazyLock<Vec<&'static str>> = LazyLock::new(|| {
    vec![
        r"\b{name}\s+said\b",
        r"\b{name}\s+told\b",
        r"\b{name}\s+asked\b",
        r"\b{name}\s+laughed\b",
        r"\b{name}\s+smiled\b",
        r"\b{name}\s+was\b",
        r"\b{name}\s+is\b",
        r"\b{name}\s+called\b",
        r"\b{name}\s+texted\b",
        r"\bwith\s+{name}\b",
        r"\bsaw\s+{name}\b",
        r"\bcalled\s+{name}\b",
        r"\btook\s+{name}\b",
        r"\bpicked\s+up\s+{name}\b",
        r"\bdrop(?:ped)?\s+(?:off\s+)?{name}\b",
        r"\b{name}(?:'s|s')\b",
        r"\bhey\s+{name}\b",
        r"\bthanks?\s+{name}\b",
        r"^{name}[:\s]",
        r"\bmy\s+(?:son|daughter|kid|child|brother|sister|friend|partner|colleague|coworker)\s+{name}\b",
    ]
});

static CONCEPT_CONTEXT_PATTERNS: LazyLock<Vec<&'static str>> = LazyLock::new(|| {
    vec![
        r"\bhave\s+you\s+{name}\b",
        r"\bif\s+you\s+{name}\b",
        r"\b{name}\s+since\b",
        r"\b{name}\s+again\b",
        r"\bnot\s+{name}\b",
        r"\b{name}\s+more\b",
        r"\bwould\s+{name}\b",
        r"\bcould\s+{name}\b",
        r"\bwill\s+{name}\b",
        r"(?:the\s+)?{name}\s+(?:of|in|at|for|to)\b",
    ]
});

// ── Wikipedia hint phrases ──────────────────────────────────────────────────

static NAME_INDICATOR_PHRASES: &[&str] = &[
    "given name",
    "personal name",
    "first name",
    "forename",
    "masculine name",
    "feminine name",
    "boy's name",
    "girl's name",
    "male name",
    "female name",
    "irish name",
    "welsh name",
    "scottish name",
    "gaelic name",
    "hebrew name",
    "arabic name",
    "norse name",
    "old english name",
    "is a name",
    "as a name",
    "name meaning",
    "name derived from",
    "legendary irish",
    "legendary welsh",
    "legendary scottish",
];

static PLACE_INDICATOR_PHRASES: &[&str] = &[
    "city in",
    "town in",
    "village in",
    "municipality",
    "capital of",
    "district of",
    "county",
    "province",
    "region of",
    "island of",
    "mountain in",
    "river in",
];

// ── Internal Wikipedia lookup result ───────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WikiLookupResult {
    pub inferred_type: String,
    pub confidence: f64,
    pub wiki_summary: Option<String>,
    pub wiki_title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub word: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub confirmed: Option<bool>,
}

fn wikipedia_lookup(
    word: &str,
    http_get: Option<&dyn Fn(&str) -> Result<String, Error>>,
) -> WikiLookupResult {
    let url = format!(
        "https://en.wikipedia.org/api/rest_v1/page/summary/{}",
        url_encode(word)
    );

    let body = if let Some(getter) = http_get {
        match getter(&url) {
            Ok(b) => b,
            Err(_) => {
                return WikiLookupResult {
                    inferred_type: "unknown".to_owned(),
                    confidence: 0.0,
                    wiki_summary: None,
                    wiki_title: None,
                    note: None,
                    word: None,
                    confirmed: None,
                };
            }
        }
    } else {
        match ureq::AgentBuilder::new()
            .timeout(std::time::Duration::from_secs(5))
            .build()
            .get(&url)
            .set("User-Agent", "MemPalace/1.0")
            .call()
        {
            Ok(resp) => match resp.into_string() {
                Ok(b) => b,
                Err(_) => {
                    return WikiLookupResult {
                        inferred_type: "unknown".to_owned(),
                        confidence: 0.0,
                        wiki_summary: None,
                        wiki_title: None,
                        note: None,
                        word: None,
                        confirmed: None,
                    };
                }
            },
            Err(ureq::Error::Status(404, _)) => {
                return WikiLookupResult {
                    inferred_type: "person".to_owned(),
                    confidence: 0.70,
                    wiki_summary: None,
                    wiki_title: None,
                    note: Some(
                        "not found in Wikipedia — likely a proper noun or unusual name".to_owned(),
                    ),
                    word: None,
                    confirmed: None,
                };
            }
            Err(e) => {
                return WikiLookupResult {
                    inferred_type: "unknown".to_owned(),
                    confidence: 0.0,
                    wiki_summary: None,
                    wiki_title: None,
                    note: Some(e.to_string()),
                    word: None,
                    confirmed: None,
                };
            }
        }
    };

    parse_wikipedia_body(&body, word)
}

fn parse_wikipedia_body(body: &str, word: &str) -> WikiLookupResult {
    let data: serde_json::Value = match serde_json::from_str(body) {
        Ok(v) => v,
        Err(_) => {
            return WikiLookupResult {
                inferred_type: "unknown".to_owned(),
                confidence: 0.0,
                wiki_summary: None,
                wiki_title: None,
                note: None,
                word: None,
                confirmed: None,
            };
        }
    };

    let page_type = data["type"].as_str().unwrap_or("");
    let extract = data["extract"].as_str().unwrap_or("").to_lowercase();
    let title = data["title"].as_str().unwrap_or(word).to_owned();

    if page_type == "disambiguation" {
        let desc = data["description"].as_str().unwrap_or("").to_lowercase();
        if desc.contains("name") || desc.contains("given name") {
            return WikiLookupResult {
                inferred_type: "person".to_owned(),
                confidence: 0.65,
                wiki_summary: Some(extract.chars().take(200).collect()),
                wiki_title: Some(title),
                note: Some("disambiguation page with name entries".to_owned()),
                word: None,
                confirmed: None,
            };
        }
        return WikiLookupResult {
            inferred_type: "ambiguous".to_owned(),
            confidence: 0.4,
            wiki_summary: Some(extract.chars().take(200).collect()),
            wiki_title: Some(title),
            note: None,
            word: None,
            confirmed: None,
        };
    }

    if NAME_INDICATOR_PHRASES.iter().any(|p| extract.contains(p)) {
        let word_lower = word.to_lowercase();
        let confidence = if extract.contains(&format!("{} is a", word_lower))
            || extract.contains(&format!("{}(name", word_lower))
        {
            0.90
        } else {
            0.80
        };
        return WikiLookupResult {
            inferred_type: "person".to_owned(),
            confidence,
            wiki_summary: Some(extract.chars().take(200).collect()),
            wiki_title: Some(title),
            note: None,
            word: None,
            confirmed: None,
        };
    }

    if PLACE_INDICATOR_PHRASES.iter().any(|p| extract.contains(p)) {
        return WikiLookupResult {
            inferred_type: "place".to_owned(),
            confidence: 0.80,
            wiki_summary: Some(extract.chars().take(200).collect()),
            wiki_title: Some(title),
            note: None,
            word: None,
            confirmed: None,
        };
    }

    WikiLookupResult {
        inferred_type: "concept".to_owned(),
        confidence: 0.60,
        wiki_summary: Some(extract.chars().take(200).collect()),
        wiki_title: Some(title),
        note: None,
        word: None,
        confirmed: None,
    }
}

fn url_encode(s: &str) -> String {
    let mut out = String::new();
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char);
            }
            b' ' => out.push('+'),
            _ => {
                out.push('%');
                out.push_str(&format!("{:02X}", b));
            }
        }
    }
    out
}

// ── LookupResult ──────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LookupResult {
    #[serde(rename = "type")]
    pub entity_type: String,
    pub inferred_type: Option<String>,
    pub confidence: f64,
    pub source: String,
    pub name: String,
    pub needs_disambiguation: bool,
    pub context: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub disambiguated_by: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub wiki_summary: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub wiki_title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub confirmed: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub word: Option<String>,
}

// ── EntityRegistry ─────────────────────────────────────────────────────────

/// Persistent personal entity registry.
///
/// Stored at `~/.mempalace/entity_registry.json`.
#[derive(Debug)]
pub struct EntityRegistry {
    data: serde_json::Value,
    path: PathBuf,
}

impl EntityRegistry {
    fn default_path() -> PathBuf {
        dirs_home().join(".mempalace").join("entity_registry.json")
    }

    // ── Load / Save ──────────────────────────────────────────────────────────

    /// Load or create the registry.
    ///
    /// Reads `<config_dir>/entity_registry.json`, or
    /// `~/.mempalace/entity_registry.json` if `config_dir` is `None`.
    /// Tolerates bad/missing JSON — returns a fresh empty registry.
    pub fn load(config_dir: Option<&Path>) -> Self {
        let path = if let Some(dir) = config_dir {
            dir.join("entity_registry.json")
        } else {
            Self::default_path()
        };

        if path.exists() {
            if let Ok(text) = std::fs::read_to_string(&path) {
                if let Ok(data) = serde_json::from_str::<serde_json::Value>(&text) {
                    return EntityRegistry { data, path };
                }
            }
        }
        EntityRegistry {
            data: Self::empty(),
            path,
        }
    }

    /// Persist the registry to disk.
    pub fn save(&self) -> Result<(), Error> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let text = serde_json::to_string_pretty(&self.data)?;
        std::fs::write(&self.path, text)?;
        Ok(())
    }

    fn empty() -> serde_json::Value {
        serde_json::json!({
            "version": 1,
            "mode": "personal",
            "people": {},
            "projects": [],
            "ambiguous_flags": [],
            "wiki_cache": {},
        })
    }

    // ── Properties ───────────────────────────────────────────────────────────

    pub fn mode(&self) -> &str {
        self.data["mode"].as_str().unwrap_or("personal")
    }

    pub fn people(&self) -> std::collections::HashMap<String, serde_json::Value> {
        self.data["people"]
            .as_object()
            .map(|m| m.iter().map(|(k, v)| (k.clone(), v.clone())).collect())
            .unwrap_or_default()
    }

    pub fn projects(&self) -> Vec<String> {
        self.data["projects"]
            .as_array()
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_owned()))
                    .collect()
            })
            .unwrap_or_default()
    }

    pub fn ambiguous_flags(&self) -> Vec<String> {
        self.data["ambiguous_flags"]
            .as_array()
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_owned()))
                    .collect()
            })
            .unwrap_or_default()
    }

    // ── Seed from onboarding ─────────────────────────────────────────────────

    /// Seed the registry from onboarding data.
    ///
    /// `people`: list of `{"name": str, "relationship": str, "context": str}` values.
    /// `aliases`: maps short name → canonical name, e.g. `{"Max": "Maxwell"}`.
    pub fn seed(
        &mut self,
        mode: &str,
        people: &[serde_json::Value],
        projects: &[String],
        aliases: Option<std::collections::HashMap<String, String>>,
    ) {
        self.data["mode"] = serde_json::Value::String(mode.to_owned());
        self.data["projects"] = serde_json::Value::Array(
            projects
                .iter()
                .map(|p| serde_json::Value::String(p.clone()))
                .collect(),
        );

        let aliases = aliases.unwrap_or_default();
        let reverse_aliases: std::collections::HashMap<&str, &str> = aliases
            .iter()
            .map(|(k, v)| (v.as_str(), k.as_str()))
            .collect();

        for entry in people {
            let name = entry["name"].as_str().unwrap_or("").trim().to_owned();
            if name.is_empty() {
                continue;
            }
            let context = entry["context"].as_str().unwrap_or("personal");
            let relationship = entry["relationship"].as_str().unwrap_or("");

            let alias_list: serde_json::Value =
                if let Some(alias) = reverse_aliases.get(name.as_str()) {
                    serde_json::json!([alias])
                } else {
                    serde_json::json!([])
                };

            self.data["people"][&name] = serde_json::json!({
                "source": "onboarding",
                "contexts": [context],
                "aliases": alias_list,
                "relationship": relationship,
                "confidence": 1.0,
            });

            if let Some(alias) = reverse_aliases.get(name.as_str()) {
                self.data["people"][alias] = serde_json::json!({
                    "source": "onboarding",
                    "contexts": [context],
                    "aliases": [&name],
                    "relationship": relationship,
                    "confidence": 1.0,
                    "canonical": &name,
                });
            }
        }

        // Flag ambiguous names
        let mut ambiguous: Vec<serde_json::Value> = Vec::new();
        if let Some(people_map) = self.data["people"].as_object() {
            for name in people_map.keys() {
                if COMMON_ENGLISH_WORDS.contains(name.to_lowercase().as_str()) {
                    ambiguous.push(serde_json::Value::String(name.to_lowercase()));
                }
            }
        }
        self.data["ambiguous_flags"] = serde_json::Value::Array(ambiguous);

        let _ = self.save();
    }

    // ── Lookup ───────────────────────────────────────────────────────────────

    /// Look up a word. Returns entity classification.
    ///
    /// `context`: surrounding sentence used for disambiguation.
    pub fn lookup(&self, word: &str, context: &str) -> LookupResult {
        let word_lower = word.to_lowercase();

        // 1. Exact match in people registry
        if let Some(people_map) = self.data["people"].as_object() {
            for (canonical, info) in people_map {
                let canonical_lower = canonical.to_lowercase();
                let aliases_match = info["aliases"]
                    .as_array()
                    .map(|arr| {
                        arr.iter().any(|a| {
                            a.as_str().map(|s| s.to_lowercase()) == Some(word_lower.clone())
                        })
                    })
                    .unwrap_or(false);

                if word_lower == canonical_lower || aliases_match {
                    let ambiguous_flags = self.ambiguous_flags();
                    if ambiguous_flags.contains(&word_lower) && !context.is_empty() {
                        if let Some(resolved) = self.disambiguate(&word_lower, context, info) {
                            return resolved;
                        }
                    }
                    return LookupResult {
                        entity_type: "person".to_owned(),
                        inferred_type: None,
                        confidence: info["confidence"].as_f64().unwrap_or(1.0),
                        source: info["source"].as_str().unwrap_or("onboarding").to_owned(),
                        name: canonical.clone(),
                        needs_disambiguation: false,
                        context: info["contexts"]
                            .as_array()
                            .map(|arr| {
                                arr.iter()
                                    .filter_map(|v| v.as_str().map(|s| s.to_owned()))
                                    .collect()
                            })
                            .unwrap_or_default(),
                        disambiguated_by: None,
                        wiki_summary: None,
                        wiki_title: None,
                        confirmed: None,
                        note: None,
                        word: None,
                    };
                }
            }
        }

        // 2. Project match
        for proj in self.projects() {
            if word_lower == proj.to_lowercase() {
                return LookupResult {
                    entity_type: "project".to_owned(),
                    inferred_type: None,
                    confidence: 1.0,
                    source: "onboarding".to_owned(),
                    name: proj,
                    needs_disambiguation: false,
                    context: vec![],
                    disambiguated_by: None,
                    wiki_summary: None,
                    wiki_title: None,
                    confirmed: None,
                    note: None,
                    word: None,
                };
            }
        }

        // 3. Wiki cache (confirmed entries)
        if let Some(cache) = self.data["wiki_cache"].as_object() {
            for (cached_word, cached_result) in cache {
                if word_lower == cached_word.to_lowercase()
                    && cached_result["confirmed"].as_bool().unwrap_or(false)
                {
                    return LookupResult {
                        entity_type: cached_result["inferred_type"]
                            .as_str()
                            .unwrap_or("unknown")
                            .to_owned(),
                        inferred_type: cached_result["inferred_type"]
                            .as_str()
                            .map(|s| s.to_owned()),
                        confidence: cached_result["confidence"].as_f64().unwrap_or(0.0),
                        source: "wiki".to_owned(),
                        name: word.to_owned(),
                        needs_disambiguation: false,
                        context: vec![],
                        disambiguated_by: None,
                        wiki_summary: None,
                        wiki_title: None,
                        confirmed: None,
                        note: None,
                        word: None,
                    };
                }
            }
        }

        LookupResult {
            entity_type: "unknown".to_owned(),
            inferred_type: None,
            confidence: 0.0,
            source: "none".to_owned(),
            name: word.to_owned(),
            needs_disambiguation: false,
            context: vec![],
            disambiguated_by: None,
            wiki_summary: None,
            wiki_title: None,
            confirmed: None,
            note: None,
            word: None,
        }
    }

    fn disambiguate(
        &self,
        word: &str,
        context: &str,
        person_info: &serde_json::Value,
    ) -> Option<LookupResult> {
        let name_lower = word.to_lowercase();
        let ctx_lower = context.to_lowercase();
        let escaped = regex::escape(&name_lower);

        let mut person_score: i64 = 0;
        for pat in PERSON_CONTEXT_PATTERNS.iter() {
            let pattern = pat.replace("{name}", &escaped);
            if let Ok(re) = Regex::new(&pattern) {
                if re.is_match(&ctx_lower) {
                    person_score += 1;
                }
            }
        }

        let mut concept_score: i64 = 0;
        for pat in CONCEPT_CONTEXT_PATTERNS.iter() {
            let pattern = pat.replace("{name}", &escaped);
            if let Ok(re) = Regex::new(&pattern) {
                if re.is_match(&ctx_lower) {
                    concept_score += 1;
                }
            }
        }

        if person_score > concept_score {
            return Some(LookupResult {
                entity_type: "person".to_owned(),
                inferred_type: None,
                confidence: (0.7 + person_score as f64 * 0.1_f64).min(0.95),
                source: person_info["source"]
                    .as_str()
                    .unwrap_or("onboarding")
                    .to_owned(),
                name: word.to_owned(),
                needs_disambiguation: false,
                context: person_info["contexts"]
                    .as_array()
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|v| v.as_str().map(|s| s.to_owned()))
                            .collect()
                    })
                    .unwrap_or_default(),
                disambiguated_by: Some("context_patterns".to_owned()),
                wiki_summary: None,
                wiki_title: None,
                confirmed: None,
                note: None,
                word: None,
            });
        } else if concept_score > person_score {
            return Some(LookupResult {
                entity_type: "concept".to_owned(),
                inferred_type: None,
                confidence: (0.7 + concept_score as f64 * 0.1_f64).min(0.90),
                source: "context_disambiguated".to_owned(),
                name: word.to_owned(),
                needs_disambiguation: false,
                context: vec![],
                disambiguated_by: Some("context_patterns".to_owned()),
                wiki_summary: None,
                wiki_title: None,
                confirmed: None,
                note: None,
                word: None,
            });
        }

        None
    }

    // ── Research unknown words ────────────────────────────────────────────────

    /// Research an unknown word via Wikipedia.
    ///
    /// Caches result. If `auto_confirm` is false, marks as unconfirmed.
    /// `http_get`: optional override for the HTTP call (used in tests).
    pub fn research(
        &mut self,
        word: &str,
        auto_confirm: bool,
        http_get: Option<Box<dyn Fn(&str) -> Result<String, Error>>>,
    ) -> Result<LookupResult, Error> {
        // Already cached?
        if let Some(cached) = self.data["wiki_cache"]
            .as_object()
            .and_then(|m| m.get(word))
        {
            let result = wiki_lookup_to_lookup_result(word, cached);
            return Ok(result);
        }

        let lookup_fn = http_get.as_deref();
        let mut wiki_result = wikipedia_lookup(word, lookup_fn);
        wiki_result.word = Some(word.to_owned());
        wiki_result.confirmed = Some(auto_confirm);

        let entry = serde_json::to_value(&wiki_result)?;
        self.data["wiki_cache"][word] = entry;
        let _ = self.save();

        Ok(wiki_lookup_to_lookup_result(
            word,
            &self.data["wiki_cache"][word],
        ))
    }

    /// Mark a researched word as confirmed and add to people registry.
    pub fn confirm_research(
        &mut self,
        word: &str,
        entity_type: &str,
        relationship: &str,
        context: &str,
    ) {
        if let Some(cache) = self.data["wiki_cache"].as_object_mut() {
            if let Some(entry) = cache.get_mut(word) {
                entry["confirmed"] = serde_json::Value::Bool(true);
                entry["confirmed_type"] = serde_json::Value::String(entity_type.to_owned());
            }
        }

        if entity_type == "person" {
            self.data["people"][word] = serde_json::json!({
                "source": "wiki",
                "contexts": [context],
                "aliases": [],
                "relationship": relationship,
                "confidence": 0.90,
            });
            let word_lower = word.to_lowercase();
            if COMMON_ENGLISH_WORDS.contains(word_lower.as_str()) {
                let flags = self.data["ambiguous_flags"]
                    .as_array()
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|v| v.as_str().map(|s| s.to_owned()))
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default();
                if !flags.contains(&word_lower) {
                    let mut new_flags = flags;
                    new_flags.push(word_lower);
                    self.data["ambiguous_flags"] = serde_json::Value::Array(
                        new_flags
                            .into_iter()
                            .map(serde_json::Value::String)
                            .collect(),
                    );
                }
            }
        }

        let _ = self.save();
    }

    // ── Learn from sessions ───────────────────────────────────────────────────

    /// Scan session text for new entity candidates.
    ///
    /// Returns list of newly discovered candidates for review.
    ///
    /// Note: full implementation requires `entity_detector` (separate module).
    /// This version returns an empty list until that module is implemented.
    pub fn learn_from_text(&mut self, _text: &str, _min_confidence: f64) -> Vec<String> {
        // entity_detector module is implemented by a parallel agent.
        // When available: extract_candidates, score_entity, classify_entity.
        vec![]
    }

    // ── Query helpers ─────────────────────────────────────────────────────────

    /// Extract known person names from a query string.
    pub fn extract_people_from_query(&self, query: &str) -> Vec<String> {
        let mut found: Vec<String> = Vec::new();

        if let Some(people_map) = self.data["people"].as_object() {
            for (canonical, info) in people_map {
                let mut names_to_check = vec![canonical.as_str()];
                let aliases: Vec<&str> = info["aliases"]
                    .as_array()
                    .map(|arr| arr.iter().filter_map(|v| v.as_str()).collect())
                    .unwrap_or_default();
                names_to_check.extend(aliases);

                for name in names_to_check {
                    let pattern = format!(r"(?i)\b{}\b", regex::escape(name));
                    if let Ok(re) = Regex::new(&pattern) {
                        if re.is_match(query) {
                            let ambiguous_flags = self.ambiguous_flags();
                            if ambiguous_flags.contains(&name.to_lowercase()) {
                                let result = self.disambiguate(name, query, info);
                                if let Some(r) = result {
                                    if r.entity_type == "person" && !found.contains(canonical) {
                                        found.push(canonical.clone());
                                    }
                                }
                            } else if !found.contains(canonical) {
                                found.push(canonical.clone());
                            }
                            break;
                        }
                    }
                }
            }
        }
        found
    }

    /// Find capitalized words in query that aren't in registry or common words.
    pub fn extract_unknown_candidates(&self, query: &str) -> Vec<String> {
        let re = Regex::new(r"\b[A-Z][a-z]{2,15}\b").unwrap();
        let candidates: HashSet<&str> = re.find_iter(query).map(|m| m.as_str()).collect();
        let mut unknown: Vec<String> = Vec::new();
        for word in candidates {
            if COMMON_ENGLISH_WORDS.contains(word.to_lowercase().as_str()) {
                continue;
            }
            let result = self.lookup(word, "");
            if result.entity_type == "unknown" {
                unknown.push(word.to_owned());
            }
        }
        unknown
    }

    // ── Summary ───────────────────────────────────────────────────────────────

    pub fn summary(&self) -> String {
        let people = self.people();
        let people_names: Vec<&str> = people.keys().map(|s| s.as_str()).collect();
        let display_names = if people_names.len() > 8 {
            format!("{}...", people_names[..8].join(", "))
        } else {
            people_names.join(", ")
        };
        let projects = self.projects();
        let ambiguous = self.ambiguous_flags();
        let wiki_count = self.data["wiki_cache"]
            .as_object()
            .map(|m| m.len())
            .unwrap_or(0);
        format!(
            "Mode: {}\nPeople: {} ({})\nProjects: {}\nAmbiguous flags: {}\nWiki cache: {} entries",
            self.mode(),
            people.len(),
            display_names,
            if projects.is_empty() {
                "(none)".to_owned()
            } else {
                projects.join(", ")
            },
            if ambiguous.is_empty() {
                "(none)".to_owned()
            } else {
                ambiguous.join(", ")
            },
            wiki_count,
        )
    }
}

// ── Helper: convert cached wiki entry → LookupResult ──────────────────────

fn wiki_lookup_to_lookup_result(word: &str, cached: &serde_json::Value) -> LookupResult {
    let inferred = cached["inferred_type"]
        .as_str()
        .unwrap_or("unknown")
        .to_owned();
    LookupResult {
        entity_type: inferred.clone(),
        inferred_type: Some(inferred),
        confidence: cached["confidence"].as_f64().unwrap_or(0.0),
        source: "wiki".to_owned(),
        name: word.to_owned(),
        needs_disambiguation: false,
        context: vec![],
        disambiguated_by: None,
        wiki_summary: cached["wiki_summary"].as_str().map(|s| s.to_owned()),
        wiki_title: cached["wiki_title"].as_str().map(|s| s.to_owned()),
        confirmed: cached["confirmed"].as_bool(),
        note: cached["note"].as_str().map(|s| s.to_owned()),
        word: Some(word.to_owned()),
    }
}

// ── Platform home dir ──────────────────────────────────────────────────────

fn dirs_home() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;
    use std::collections::HashMap;

    fn seed_riley(tmp: &Path) -> EntityRegistry {
        let mut r = EntityRegistry::load(Some(tmp));
        r.seed(
            "personal",
            &[serde_json::json!({"name": "Riley", "relationship": "daughter", "context": "personal"})],
            &[],
            None,
        );
        r
    }

    // ── COMMON_ENGLISH_WORDS ─────────────────────────────────────────────────

    #[test]
    fn test_common_english_words_has_expected_entries() {
        assert!(COMMON_ENGLISH_WORDS.contains("ever"));
        assert!(COMMON_ENGLISH_WORDS.contains("grace"));
        assert!(COMMON_ENGLISH_WORDS.contains("will"));
        assert!(COMMON_ENGLISH_WORDS.contains("may"));
        assert!(COMMON_ENGLISH_WORDS.contains("monday"));
    }

    #[test]
    fn test_common_english_words_is_lowercase() {
        for word in COMMON_ENGLISH_WORDS.iter() {
            assert_eq!(*word, word.to_lowercase(), "{word} should be lowercase");
        }
    }

    // ── PERSON_CONTEXT_PATTERNS ──────────────────────────────────────────────

    #[test]
    fn test_person_context_patterns_is_nonempty() {
        assert!(!PERSON_CONTEXT_PATTERNS.is_empty());
    }

    // ── Load / empty state ───────────────────────────────────────────────────

    #[test]
    fn test_load_from_nonexistent_dir() {
        let tmp = tempfile::tempdir().unwrap();
        let registry = EntityRegistry::load(Some(tmp.path()));
        assert_eq!(registry.people().len(), 0);
        assert!(registry.projects().is_empty());
        assert_eq!(registry.mode(), "personal");
        assert!(registry.ambiguous_flags().is_empty());
    }

    #[test]
    fn test_save_and_load_roundtrip() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        registry.seed(
            "work",
            &[serde_json::json!({"name": "Alice", "relationship": "colleague", "context": "work"})],
            &["MemPalace".to_owned()],
            None,
        );
        let loaded = EntityRegistry::load(Some(tmp.path()));
        assert_eq!(loaded.mode(), "work");
        assert!(loaded.people().contains_key("Alice"));
        assert!(loaded.projects().contains(&"MemPalace".to_owned()));
    }

    #[test]
    fn test_save_creates_file() {
        let tmp = tempfile::tempdir().unwrap();
        let registry = EntityRegistry::load(Some(tmp.path()));
        registry.save().unwrap();
        assert!(tmp.path().join("entity_registry.json").exists());
    }

    // ── seed ─────────────────────────────────────────────────────────────────

    #[test]
    fn test_seed_registers_people() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        registry.seed(
            "personal",
            &[
                serde_json::json!({"name": "Riley", "relationship": "daughter", "context": "personal"}),
                serde_json::json!({"name": "Devon", "relationship": "friend", "context": "personal"}),
            ],
            &["MemPalace".to_owned()],
            None,
        );
        let people = registry.people();
        assert!(people.contains_key("Riley"));
        assert!(people.contains_key("Devon"));
        assert_eq!(people["Riley"]["relationship"], "daughter");
        assert_eq!(people["Riley"]["source"], "onboarding");
        assert_eq!(people["Riley"]["confidence"], 1.0);
    }

    #[test]
    fn test_seed_registers_projects() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        registry.seed("work", &[], &["Acme".to_owned(), "Widget".to_owned()], None);
        assert_eq!(registry.projects(), vec!["Acme", "Widget"]);
    }

    #[test]
    fn test_seed_sets_mode() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        registry.seed("combo", &[], &[], None);
        assert_eq!(registry.mode(), "combo");
    }

    #[test]
    fn test_seed_flags_ambiguous_names() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        registry.seed(
            "personal",
            &[
                serde_json::json!({"name": "Grace", "relationship": "friend", "context": "personal"}),
                serde_json::json!({"name": "Riley", "relationship": "daughter", "context": "personal"}),
            ],
            &[],
            None,
        );
        let flags = registry.ambiguous_flags();
        assert!(flags.contains(&"grace".to_owned()));
        assert!(!flags.contains(&"riley".to_owned()));
    }

    #[test]
    fn test_seed_with_aliases() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        let mut aliases = HashMap::new();
        aliases.insert("Max".to_owned(), "Maxwell".to_owned());
        registry.seed(
            "personal",
            &[serde_json::json!({"name": "Maxwell", "relationship": "friend", "context": "personal"})],
            &[],
            Some(aliases),
        );
        let people = registry.people();
        assert!(people.contains_key("Maxwell"));
        assert!(people.contains_key("Max"));
        assert_eq!(people["Max"]["canonical"], "Maxwell");
    }

    #[test]
    fn test_seed_skips_empty_names() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        registry.seed(
            "personal",
            &[serde_json::json!({"name": "", "relationship": "", "context": "personal"})],
            &[],
            None,
        );
        assert_eq!(registry.people().len(), 0);
    }

    // ── lookup ───────────────────────────────────────────────────────────────

    #[test]
    fn test_lookup_known_person() {
        let tmp = tempfile::tempdir().unwrap();
        let registry = seed_riley(tmp.path());
        let result = registry.lookup("Riley", "");
        assert_eq!(result.entity_type, "person");
        assert_eq!(result.confidence, 1.0);
        assert_eq!(result.name, "Riley");
    }

    #[test]
    fn test_lookup_known_project() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        registry.seed("work", &[], &["MemPalace".to_owned()], None);
        let result = registry.lookup("MemPalace", "");
        assert_eq!(result.entity_type, "project");
        assert_eq!(result.confidence, 1.0);
    }

    #[test]
    fn test_lookup_unknown_word() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        registry.seed("personal", &[], &[], None);
        let result = registry.lookup("Xyzzy", "");
        assert_eq!(result.entity_type, "unknown");
        assert_eq!(result.confidence, 0.0);
    }

    #[test]
    fn test_lookup_case_insensitive() {
        let tmp = tempfile::tempdir().unwrap();
        let registry = seed_riley(tmp.path());
        let result = registry.lookup("riley", "");
        assert_eq!(result.entity_type, "person");
    }

    #[test]
    fn test_lookup_alias() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        let mut aliases = HashMap::new();
        aliases.insert("Max".to_owned(), "Maxwell".to_owned());
        registry.seed(
            "personal",
            &[serde_json::json!({"name": "Maxwell", "relationship": "friend", "context": "personal"})],
            &[],
            Some(aliases),
        );
        let result = registry.lookup("Max", "");
        assert_eq!(result.entity_type, "person");
    }

    // ── disambiguation ───────────────────────────────────────────────────────

    #[test]
    fn test_lookup_ambiguous_word_as_person() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        registry.seed(
            "personal",
            &[serde_json::json!({"name": "Grace", "relationship": "friend", "context": "personal"})],
            &[],
            None,
        );
        let result = registry.lookup("Grace", "I went with Grace today");
        assert_eq!(result.entity_type, "person");
    }

    #[test]
    fn test_lookup_ambiguous_word_as_concept() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        registry.seed(
            "personal",
            &[serde_json::json!({"name": "Ever", "relationship": "friend", "context": "personal"})],
            &[],
            None,
        );
        let result = registry.lookup("Ever", "have you ever tried this");
        assert_eq!(result.entity_type, "concept");
    }

    // ── research (Wikipedia) — mocked ────────────────────────────────────────

    #[test]
    fn test_research_caches_result() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        registry.seed("personal", &[], &[], None);

        let mock_body = r#"{"type":"standard","title":"Saoirse","extract":"saoirse is an irish given name meaning freedom.","description":"Irish name"}"#;
        let result = registry
            .research(
                "Saoirse",
                true,
                Some(Box::new(|_: &str| Ok(mock_body.to_owned()))),
            )
            .unwrap();
        assert_eq!(result.inferred_type.as_deref(), Some("person"));

        // Second call should use cache (mock panics if called)
        let cached = registry
            .research(
                "Saoirse",
                true,
                Some(Box::new(|_: &str| -> Result<String, Error> {
                    panic!("should not be called — cache should be used");
                })),
            )
            .unwrap();
        assert_eq!(cached.inferred_type.as_deref(), Some("person"));
    }

    #[test]
    fn test_confirm_research_adds_to_people() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        registry.seed("personal", &[], &[], None);

        let mock_body = r#"{"type":"standard","title":"Saoirse","extract":"saoirse is a name","description":""}"#;
        registry
            .research(
                "Saoirse",
                false,
                Some(Box::new(|_: &str| Ok(mock_body.to_owned()))),
            )
            .unwrap();

        registry.confirm_research("Saoirse", "person", "friend", "personal");
        let people = registry.people();
        assert!(people.contains_key("Saoirse"));
        assert_eq!(people["Saoirse"]["source"], "wiki");
    }

    // ── extract_people_from_query ─────────────────────────────────────────────

    #[test]
    fn test_extract_people_from_query() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        registry.seed(
            "personal",
            &[
                serde_json::json!({"name": "Riley", "relationship": "daughter", "context": "personal"}),
                serde_json::json!({"name": "Devon", "relationship": "friend", "context": "personal"}),
            ],
            &[],
            None,
        );
        let found = registry.extract_people_from_query("What did Riley say about the weather?");
        assert!(found.contains(&"Riley".to_owned()));
        assert!(!found.contains(&"Devon".to_owned()));
    }

    // ── extract_unknown_candidates ────────────────────────────────────────────

    #[test]
    fn test_extract_unknown_candidates() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        registry.seed("personal", &[], &[], None);
        let unknowns = registry.extract_unknown_candidates("Saoirse went to the store");
        assert!(unknowns.contains(&"Saoirse".to_owned()));
    }

    #[test]
    fn test_extract_unknown_candidates_skips_known() {
        let tmp = tempfile::tempdir().unwrap();
        let registry = seed_riley(tmp.path());
        let unknowns = registry.extract_unknown_candidates("Riley went to the store");
        assert!(!unknowns.contains(&"Riley".to_owned()));
    }

    // ── summary ───────────────────────────────────────────────────────────────

    #[test]
    fn test_summary() {
        let tmp = tempfile::tempdir().unwrap();
        let mut registry = EntityRegistry::load(Some(tmp.path()));
        registry.seed(
            "personal",
            &[serde_json::json!({"name": "Riley", "relationship": "daughter", "context": "personal"})],
            &["MemPalace".to_owned()],
            None,
        );
        let s = registry.summary();
        assert!(s.contains("personal"));
        assert!(s.contains("Riley"));
        assert!(s.contains("MemPalace"));
    }
}

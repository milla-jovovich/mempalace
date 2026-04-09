//! Guided onboarding — port of Python `mempalace/onboarding.py`.
//!
//! The Python version was an interactive CLI wizard. The Rust port
//! exposes the pure data operations (build/save wing config) so they
//! can be unit-tested and driven by any front-end (CLI, MCP, GUI).

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum OnboardingError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("invalid wing name: {0}")]
    InvalidWing(String),
}

pub type Result<T> = std::result::Result<T, OnboardingError>;

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct WingEntry {
    #[serde(rename = "type")]
    pub wing_type: String,
    pub keywords: Vec<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct WingConfig {
    pub default_wing: String,
    pub wings: BTreeMap<String, WingEntry>,
}

impl WingConfig {
    pub fn new_empty() -> Self {
        Self {
            default_wing: "wing_general".to_string(),
            wings: BTreeMap::new(),
        }
    }

    pub fn add_person(&mut self, name: &str) -> Result<String> {
        let wing = wing_name_from_person(name)?;
        let entry = WingEntry {
            wing_type: "person".to_string(),
            keywords: person_keywords(name),
        };
        self.wings.insert(wing.clone(), entry);
        Ok(wing)
    }

    pub fn add_project(&mut self, project: &str, extra_keywords: &[&str]) -> Result<String> {
        let wing = wing_name_from_project(project)?;
        let mut keywords: Vec<String> = vec![project.to_lowercase()];
        for k in extra_keywords {
            keywords.push((*k).to_lowercase());
        }
        keywords.sort();
        keywords.dedup();
        let entry = WingEntry {
            wing_type: "project".to_string(),
            keywords,
        };
        self.wings.insert(wing.clone(), entry);
        Ok(wing)
    }

    pub fn save<P: AsRef<Path>>(&self, path: P) -> Result<()> {
        let path = path.as_ref();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let text = serde_json::to_string_pretty(self)?;
        std::fs::write(path, text)?;
        Ok(())
    }

    pub fn load<P: AsRef<Path>>(path: P) -> Result<Self> {
        let text = std::fs::read_to_string(path.as_ref())?;
        Ok(serde_json::from_str(&text)?)
    }

    pub fn default_path() -> PathBuf {
        mempalace_core::home_dir()
            .unwrap_or_else(|| PathBuf::from("/tmp"))
            .join(".mempalace")
            .join("wing_config.json")
    }
}

pub fn wing_name_from_person(name: &str) -> Result<String> {
    let trimmed = name.trim();
    if trimmed.is_empty() {
        return Err(OnboardingError::InvalidWing(name.to_string()));
    }
    let slug: String = trimmed
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() {
                c.to_ascii_lowercase()
            } else {
                '_'
            }
        })
        .collect::<String>();
    let trimmed_slug = slug.trim_matches('_');
    if trimmed_slug.is_empty() {
        return Err(OnboardingError::InvalidWing(name.to_string()));
    }
    Ok(format!("wing_{trimmed_slug}"))
}

pub fn wing_name_from_project(project: &str) -> Result<String> {
    wing_name_from_person(project)
}

pub fn person_keywords(name: &str) -> Vec<String> {
    let lower = name.to_lowercase();
    let possessive = format!("{lower}'s");
    let mut kws = vec![lower, possessive];
    kws.sort();
    kws.dedup();
    kws
}

pub fn default_identity_template(name: &str) -> String {
    format!(
        "I am Atlas, a personal AI assistant for {name}.\n\
         Traits: warm, direct, remembers everything.\n\
         I file everything in the palace so nothing is lost."
    )
}

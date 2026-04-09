//! Vector palace abstraction.
//!
//! In Python, the palace is backed by ChromaDB. In the Rust port, the
//! palace is a trait-based abstraction so the layers / graph modules can
//! be tested against an in-memory backend while the production backend
//! uses `lancedb`.
//!
//! A concrete `LanceDbPalace` backend lives in [`crate::lancedb_backend`]
//! (gated behind the `lancedb-backend` feature). The default / test backend
//! is [`InMemoryPalace`].

use std::collections::{BTreeMap, HashMap};

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum PalaceError {
    #[error("backend error: {0}")]
    Backend(String),
    #[error("drawer `{0}` already exists")]
    Duplicate(String),
    #[error("drawer `{0}` not found")]
    NotFound(String),
}

pub type Result<T> = std::result::Result<T, PalaceError>;

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct DrawerMetadata {
    pub wing: Option<String>,
    pub room: Option<String>,
    pub hall: Option<String>,
    pub source_file: Option<String>,
    pub date: Option<String>,
    pub importance: Option<f64>,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

impl DrawerMetadata {
    pub fn extra_get(&self, key: &str) -> Option<&serde_json::Value> {
        self.extra.get(key)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DrawerRecord {
    pub id: String,
    pub content: String,
    pub metadata: DrawerMetadata,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResult {
    pub id: String,
    pub content: String,
    pub metadata: DrawerMetadata,
    pub similarity: f64,
}

#[derive(Debug, Clone, Default)]
pub struct SearchFilter {
    pub wing: Option<String>,
    pub room: Option<String>,
}

/// A palace backend — storage for drawer text and metadata, plus
/// semantic / filtered retrieval.
pub trait Palace: std::fmt::Debug + Send + Sync {
    fn count(&self) -> Result<usize>;
    fn add(&mut self, record: DrawerRecord) -> Result<()>;
    fn delete(&mut self, id: &str) -> Result<bool>;
    fn get(&self, id: &str) -> Result<Option<DrawerRecord>>;
    fn list(&self, limit: usize, offset: usize) -> Result<Vec<DrawerRecord>>;
    fn list_filtered(&self, filter: &SearchFilter, limit: usize) -> Result<Vec<DrawerRecord>>;
    fn search(
        &self,
        query: &str,
        filter: &SearchFilter,
        n_results: usize,
    ) -> Result<Vec<SearchResult>>;
}

// ── In-memory reference backend ─────────────────────────────────────────

#[derive(Debug, Default)]
pub struct InMemoryPalace {
    drawers: HashMap<String, DrawerRecord>,
    insertion_order: Vec<String>,
}

impl InMemoryPalace {
    pub fn new() -> Self {
        Self::default()
    }
}

impl Palace for InMemoryPalace {
    fn count(&self) -> Result<usize> {
        Ok(self.drawers.len())
    }

    fn add(&mut self, record: DrawerRecord) -> Result<()> {
        if self.drawers.contains_key(&record.id) {
            return Err(PalaceError::Duplicate(record.id));
        }
        self.insertion_order.push(record.id.clone());
        self.drawers.insert(record.id.clone(), record);
        Ok(())
    }

    fn delete(&mut self, id: &str) -> Result<bool> {
        let existed = self.drawers.remove(id).is_some();
        if existed {
            self.insertion_order.retain(|x| x != id);
        }
        Ok(existed)
    }

    fn get(&self, id: &str) -> Result<Option<DrawerRecord>> {
        Ok(self.drawers.get(id).cloned())
    }

    fn list(&self, limit: usize, offset: usize) -> Result<Vec<DrawerRecord>> {
        Ok(self
            .insertion_order
            .iter()
            .skip(offset)
            .take(limit)
            .filter_map(|id| self.drawers.get(id).cloned())
            .collect())
    }

    fn list_filtered(&self, filter: &SearchFilter, limit: usize) -> Result<Vec<DrawerRecord>> {
        Ok(self
            .insertion_order
            .iter()
            .filter_map(|id| self.drawers.get(id))
            .filter(|d| matches_filter(&d.metadata, filter))
            .take(limit)
            .cloned()
            .collect())
    }

    fn search(
        &self,
        query: &str,
        filter: &SearchFilter,
        n_results: usize,
    ) -> Result<Vec<SearchResult>> {
        let q = query.to_lowercase();
        let q_tokens: Vec<&str> = q.split_whitespace().collect();
        if q_tokens.is_empty() {
            return Ok(Vec::new());
        }

        let mut scored: Vec<SearchResult> = self
            .drawers
            .values()
            .filter(|d| matches_filter(&d.metadata, filter))
            .map(|d| {
                let content_lower = d.content.to_lowercase();
                let hits: usize = q_tokens
                    .iter()
                    .filter(|t| content_lower.contains(*t))
                    .count();
                #[allow(clippy::cast_precision_loss)]
                let similarity = (hits as f64) / (q_tokens.len() as f64);
                SearchResult {
                    id: d.id.clone(),
                    content: d.content.clone(),
                    metadata: d.metadata.clone(),
                    similarity,
                }
            })
            .filter(|r| r.similarity > 0.0)
            .collect();

        scored.sort_by(|a, b| {
            b.similarity
                .partial_cmp(&a.similarity)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        scored.truncate(n_results);
        Ok(scored)
    }
}

pub fn matches_filter(meta: &DrawerMetadata, filter: &SearchFilter) -> bool {
    if let Some(ref w) = filter.wing {
        if meta.wing.as_deref() != Some(w.as_str()) {
            return false;
        }
    }
    if let Some(ref r) = filter.room {
        if meta.room.as_deref() != Some(r.as_str()) {
            return false;
        }
    }
    true
}

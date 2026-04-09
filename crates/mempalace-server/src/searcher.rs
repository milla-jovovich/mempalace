//! Semantic search over the palace.
//!
//! Port of Python `mempalace/searcher.py`.

use std::path::Path;

use mempalace_store::palace::{Palace, SearchFilter};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SearchQuery {
    pub query: String,
    pub wing: Option<String>,
    pub room: Option<String>,
    pub n_results: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchHit {
    pub text: String,
    pub wing: String,
    pub room: String,
    pub source_file: String,
    pub similarity: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResponse {
    pub query: String,
    pub wing: Option<String>,
    pub room: Option<String>,
    pub results: Vec<SearchHit>,
}

pub fn search_memories(palace: &dyn Palace, q: &SearchQuery) -> SearchResponse {
    let filter = SearchFilter {
        wing: q.wing.clone(),
        room: q.room.clone(),
    };
    let n = if q.n_results == 0 { 5 } else { q.n_results };

    let results = palace.search(&q.query, &filter, n).unwrap_or_default();

    let hits: Vec<SearchHit> = results
        .into_iter()
        .map(|r| SearchHit {
            text: r.content,
            wing: r
                .metadata
                .wing
                .clone()
                .unwrap_or_else(|| "unknown".to_string()),
            room: r
                .metadata
                .room
                .clone()
                .unwrap_or_else(|| "unknown".to_string()),
            source_file: r
                .metadata
                .source_file
                .as_deref()
                .and_then(|p| Path::new(p).file_name())
                .map(|f| f.to_string_lossy().into_owned())
                .unwrap_or_else(|| "?".to_string()),
            similarity: (r.similarity * 1000.0).round() / 1000.0,
        })
        .collect();

    SearchResponse {
        query: q.query.clone(),
        wing: q.wing.clone(),
        room: q.room.clone(),
        results: hits,
    }
}

pub fn format_human(resp: &SearchResponse) -> String {
    let mut out = String::new();
    if resp.results.is_empty() {
        out.push_str(&format!("\n  No results found for: \"{}\"\n", resp.query));
        return out;
    }
    out.push_str(&format!("\n{}\n", "=".repeat(60)));
    out.push_str(&format!("  Results for: \"{}\"\n", resp.query));
    if let Some(w) = &resp.wing {
        out.push_str(&format!("  Wing: {w}\n"));
    }
    if let Some(r) = &resp.room {
        out.push_str(&format!("  Room: {r}\n"));
    }
    out.push_str(&format!("{}\n\n", "=".repeat(60)));
    for (i, h) in resp.results.iter().enumerate() {
        let idx = i + 1;
        out.push_str(&format!("  [{idx}] {} / {}\n", h.wing, h.room));
        out.push_str(&format!("      Source: {}\n", h.source_file));
        out.push_str(&format!("      Match:  {}\n\n", h.similarity));
        for line in h.text.trim().lines() {
            out.push_str(&format!("      {line}\n"));
        }
        out.push_str(&format!("\n  {}\n", "-".repeat(56)));
    }
    out.push('\n');
    out
}

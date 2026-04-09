//! 4-layer memory stack.
//!
//! Port of Python `mempalace/layers.py`.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use crate::palace::{Palace, SearchFilter};

pub const L1_MAX_DRAWERS: usize = 15;
pub const L1_MAX_CHARS: usize = 3200;

#[derive(Debug, Clone)]
pub struct Layer0 {
    pub path: PathBuf,
    cached: Option<String>,
}

impl Layer0 {
    pub fn new(identity_path: Option<PathBuf>) -> Self {
        let path = identity_path.unwrap_or_else(|| {
            mempalace_core::home_dir()
                .unwrap_or_else(|| PathBuf::from("/tmp"))
                .join(".mempalace")
                .join("identity.txt")
        });
        Self { path, cached: None }
    }

    pub fn render(&mut self) -> &str {
        if self.cached.is_none() {
            let text = if self.path.exists() {
                std::fs::read_to_string(&self.path)
                    .map(|s| s.trim().to_string())
                    .unwrap_or_else(|_| default_identity().to_string())
            } else {
                default_identity().to_string()
            };
            self.cached = Some(text);
        }
        self.cached.as_deref().unwrap_or_else(|| default_identity())
    }

    pub fn token_estimate(&mut self) -> usize {
        self.render().len() / 4
    }
}

fn default_identity() -> &'static str {
    "## L0 — IDENTITY\nNo identity configured. Create ~/.mempalace/identity.txt"
}

#[derive(Debug)]
pub struct Layer1<'p> {
    palace: &'p dyn Palace,
    pub wing: Option<String>,
}

impl<'p> Layer1<'p> {
    pub fn new(palace: &'p dyn Palace) -> Self {
        Self { palace, wing: None }
    }

    pub fn with_wing(palace: &'p dyn Palace, wing: Option<String>) -> Self {
        Self { palace, wing }
    }

    pub fn generate(&self) -> String {
        let filter = SearchFilter {
            wing: self.wing.clone(),
            room: None,
        };

        let drawers = match self.palace.list_filtered(&filter, 5000) {
            Ok(v) => v,
            Err(_) => return "## L1 — No palace found. Run: mempalace mine <dir>".to_string(),
        };

        if drawers.is_empty() {
            return "## L1 — No memories yet.".to_string();
        }

        let mut scored: Vec<(f64, &crate::palace::DrawerRecord)> = drawers
            .iter()
            .map(|d| (d.metadata.importance.unwrap_or(3.0), d))
            .collect();
        scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
        scored.truncate(L1_MAX_DRAWERS);

        let mut by_room: BTreeMap<String, Vec<(f64, &crate::palace::DrawerRecord)>> =
            BTreeMap::new();
        for (imp, d) in scored {
            let room = d
                .metadata
                .room
                .clone()
                .unwrap_or_else(|| "general".to_string());
            by_room.entry(room).or_default().push((imp, d));
        }

        let mut lines: Vec<String> = vec!["## L1 — ESSENTIAL STORY".to_string()];
        let mut total_len: usize = 0;

        for (room, entries) in by_room {
            let room_line = format!("\n[{room}]");
            total_len += room_line.len();
            lines.push(room_line);

            for (_imp, d) in entries {
                let source = d
                    .metadata
                    .source_file
                    .as_deref()
                    .and_then(|p| Path::new(p).file_name())
                    .map(|f| f.to_string_lossy().into_owned())
                    .unwrap_or_default();

                let snippet_raw: String = d.content.trim().replace('\n', " ");
                let snippet = if snippet_raw.chars().count() > 200 {
                    let truncated: String = snippet_raw.chars().take(197).collect();
                    format!("{truncated}...")
                } else {
                    snippet_raw
                };

                let mut entry_line = format!("  - {snippet}");
                if !source.is_empty() {
                    entry_line.push_str(&format!("  ({source})"));
                }

                if total_len + entry_line.len() > L1_MAX_CHARS {
                    lines.push("  ... (more in L3 search)".to_string());
                    return lines.join("\n");
                }

                total_len += entry_line.len();
                lines.push(entry_line);
            }
        }

        lines.join("\n")
    }
}

#[derive(Debug)]
pub struct Layer2<'p> {
    palace: &'p dyn Palace,
}

impl<'p> Layer2<'p> {
    pub fn new(palace: &'p dyn Palace) -> Self {
        Self { palace }
    }

    pub fn retrieve(&self, wing: Option<&str>, room: Option<&str>, n_results: usize) -> String {
        let filter = SearchFilter {
            wing: wing.map(str::to_string),
            room: room.map(str::to_string),
        };

        let drawers = match self.palace.list_filtered(&filter, n_results) {
            Ok(v) => v,
            Err(_) => return "No palace found.".to_string(),
        };

        if drawers.is_empty() {
            let mut label = String::new();
            if let Some(w) = wing {
                label.push_str(&format!("wing={w}"));
            }
            if let Some(r) = room {
                if !label.is_empty() {
                    label.push(' ');
                }
                label.push_str(&format!("room={r}"));
            }
            return format!("No drawers found for {label}.");
        }

        let mut lines = vec![format!("## L2 — ON-DEMAND ({} drawers)", drawers.len())];
        for d in drawers {
            let room_name = d.metadata.room.clone().unwrap_or_else(|| "?".to_string());
            let source = d
                .metadata
                .source_file
                .as_deref()
                .and_then(|p| Path::new(p).file_name())
                .map(|f| f.to_string_lossy().into_owned())
                .unwrap_or_default();

            let snippet_raw: String = d.content.trim().replace('\n', " ");
            let snippet: String = if snippet_raw.chars().count() > 300 {
                let truncated: String = snippet_raw.chars().take(297).collect();
                format!("{truncated}...")
            } else {
                snippet_raw
            };

            let mut entry = format!("  [{room_name}] {snippet}");
            if !source.is_empty() {
                entry.push_str(&format!("  ({source})"));
            }
            lines.push(entry);
        }
        lines.join("\n")
    }
}

#[derive(Debug)]
pub struct Layer3<'p> {
    palace: &'p dyn Palace,
}

impl<'p> Layer3<'p> {
    pub fn new(palace: &'p dyn Palace) -> Self {
        Self { palace }
    }

    pub fn search(
        &self,
        query: &str,
        wing: Option<&str>,
        room: Option<&str>,
        n_results: usize,
    ) -> String {
        let filter = SearchFilter {
            wing: wing.map(str::to_string),
            room: room.map(str::to_string),
        };
        let hits = match self.palace.search(query, &filter, n_results) {
            Ok(v) => v,
            Err(_) => return "No palace found.".to_string(),
        };

        if hits.is_empty() {
            return "No results found.".to_string();
        }

        let mut lines = vec![format!("## L3 — SEARCH RESULTS for \"{query}\"")];
        for (i, r) in hits.iter().enumerate() {
            let idx = i + 1;
            let similarity = (r.similarity * 1000.0).round() / 1000.0;
            let wing_name = r.metadata.wing.as_deref().unwrap_or("?");
            let room_name = r.metadata.room.as_deref().unwrap_or("?");
            let source = r
                .metadata
                .source_file
                .as_deref()
                .and_then(|p| Path::new(p).file_name())
                .map(|f| f.to_string_lossy().into_owned())
                .unwrap_or_default();

            let snippet_raw: String = r.content.trim().replace('\n', " ");
            let snippet: String = if snippet_raw.chars().count() > 300 {
                let truncated: String = snippet_raw.chars().take(297).collect();
                format!("{truncated}...")
            } else {
                snippet_raw
            };

            lines.push(format!(
                "  [{idx}] {wing_name}/{room_name} (sim={similarity})"
            ));
            lines.push(format!("      {snippet}"));
            if !source.is_empty() {
                lines.push(format!("      src: {source}"));
            }
        }
        lines.join("\n")
    }
}

#[derive(Debug)]
pub struct MemoryStack<'p> {
    palace: &'p dyn Palace,
    pub identity_path: PathBuf,
    l0: Layer0,
}

impl<'p> MemoryStack<'p> {
    pub fn new(palace: &'p dyn Palace, identity_path: Option<PathBuf>) -> Self {
        let l0 = Layer0::new(identity_path.clone());
        let identity_path = l0.path.clone();
        Self {
            palace,
            identity_path,
            l0,
        }
    }

    pub fn wake_up(&mut self, wing: Option<&str>) -> String {
        let mut parts: Vec<String> = Vec::new();
        parts.push(self.l0.render().to_string());
        parts.push(String::new());
        let l1 = Layer1::with_wing(self.palace, wing.map(str::to_string));
        parts.push(l1.generate());
        parts.join("\n")
    }

    pub fn recall(&self, wing: Option<&str>, room: Option<&str>, n_results: usize) -> String {
        Layer2::new(self.palace).retrieve(wing, room, n_results)
    }

    pub fn search(
        &self,
        query: &str,
        wing: Option<&str>,
        room: Option<&str>,
        n_results: usize,
    ) -> String {
        Layer3::new(self.palace).search(query, wing, room, n_results)
    }

    pub fn total_drawers(&self) -> usize {
        self.palace.count().unwrap_or(0)
    }
}

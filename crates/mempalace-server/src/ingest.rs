//! Project file ingest — port of Python `mempalace/miner.py`.
//!
//! Walks a directory (respecting `.gitignore`), reads text-like files
//! under [`MAX_FILE_SIZE`] bytes, splits them into overlapping chunks,
//! and inserts the chunks as drawers into a [`Palace`].

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use std::sync::OnceLock;

use ignore::WalkBuilder;
use mempalace_store::palace::{DrawerMetadata, DrawerRecord, Palace};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;

pub const CHUNK_SIZE: usize = 800;
pub const CHUNK_OVERLAP: usize = 100;
pub const MIN_CHUNK_SIZE: usize = 50;
pub const MAX_FILE_SIZE: u64 = 10 * 1024 * 1024;

static READABLE_EXTENSIONS: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        "txt", "md", "py", "js", "ts", "jsx", "tsx", "json", "yaml", "yml", "html", "css", "java",
        "go", "rs", "rb", "sh", "csv", "sql", "toml",
    ]
    .into_iter()
    .collect()
});

static SKIP_FILENAMES: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        "mempalace.yaml",
        "mempalace.yml",
        "mempal.yaml",
        "mempal.yml",
        ".gitignore",
        "package-lock.json",
    ]
    .into_iter()
    .collect()
});

#[derive(Debug, Error)]
pub enum IngestError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("palace error: {0}")]
    Palace(#[from] mempalace_store::palace::PalaceError),
    #[error("root is not a directory: {0}")]
    NotADirectory(PathBuf),
    #[error("symlinked file rejected: {0}")]
    SymlinkRejected(PathBuf),
}

pub type Result<T> = std::result::Result<T, IngestError>;

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct IngestStats {
    pub files_scanned: usize,
    pub files_skipped_size: usize,
    pub files_skipped_symlink: usize,
    pub files_skipped_binary: usize,
    pub files_indexed: usize,
    pub drawers_written: usize,
    pub drawers_skipped_existing: usize,
}

#[derive(Debug, Clone)]
pub struct MinerOptions {
    pub wing: Option<String>,
    pub default_room: String,
    pub chunk_size: usize,
    pub chunk_overlap: usize,
    pub max_file_size: u64,
}

impl Default for MinerOptions {
    fn default() -> Self {
        Self {
            wing: None,
            default_room: "general".to_string(),
            chunk_size: CHUNK_SIZE,
            chunk_overlap: CHUNK_OVERLAP,
            max_file_size: MAX_FILE_SIZE,
        }
    }
}

#[derive(Debug)]
pub struct Miner {
    options: MinerOptions,
}

impl Miner {
    pub fn new(options: MinerOptions) -> Self {
        Self { options }
    }

    pub fn mine(&self, root: &Path, palace: &mut dyn Palace) -> Result<IngestStats> {
        if !root.is_dir() {
            return Err(IngestError::NotADirectory(root.to_path_buf()));
        }

        let canonical_root = root.canonicalize()?;
        let mut stats = IngestStats::default();

        let walker = WalkBuilder::new(&canonical_root)
            .git_ignore(true)
            .git_exclude(true)
            .git_global(true)
            .hidden(true)
            .follow_links(false)
            .build();

        for entry in walker.flatten() {
            let path = entry.path();
            if !path.is_file() {
                continue;
            }

            stats.files_scanned += 1;

            if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                if SKIP_FILENAMES.contains(name) {
                    continue;
                }
            }

            let ext = path
                .extension()
                .and_then(|e| e.to_str())
                .map(str::to_lowercase);
            let ext_ok = ext
                .as_deref()
                .is_some_and(|e| READABLE_EXTENSIONS.contains(e));
            if !ext_ok {
                stats.files_skipped_binary += 1;
                continue;
            }

            let metadata = std::fs::symlink_metadata(path)?;
            if metadata.file_type().is_symlink() {
                stats.files_skipped_symlink += 1;
                continue;
            }
            if metadata.len() > self.options.max_file_size {
                stats.files_skipped_size += 1;
                continue;
            }

            let content = match std::fs::read_to_string(path) {
                Ok(text) => text,
                Err(_) => {
                    stats.files_skipped_binary += 1;
                    continue;
                }
            };

            let relative = path
                .strip_prefix(&canonical_root)
                .map(Path::to_path_buf)
                .unwrap_or_else(|_| path.to_path_buf());
            self.ingest_file_content(palace, &content, &relative, &mut stats)?;
            stats.files_indexed += 1;
        }

        Ok(stats)
    }

    fn ingest_file_content(
        &self,
        palace: &mut dyn Palace,
        content: &str,
        relative_path: &Path,
        stats: &mut IngestStats,
    ) -> Result<()> {
        let chunks = chunk_text(content, self.options.chunk_size, self.options.chunk_overlap);
        for (idx, chunk) in chunks.into_iter().enumerate() {
            if chunk.len() < MIN_CHUNK_SIZE {
                continue;
            }
            let drawer_id = compute_drawer_id(relative_path, idx, &chunk);
            let record = DrawerRecord {
                id: drawer_id,
                content: chunk,
                metadata: DrawerMetadata {
                    wing: self.options.wing.clone(),
                    room: Some(self.options.default_room.clone()),
                    hall: Some("hall_facts".to_string()),
                    source_file: Some(relative_path.to_string_lossy().into_owned()),
                    date: Some(today_iso()),
                    importance: Some(3.0),
                    ..DrawerMetadata::default()
                },
            };
            match palace.add(record) {
                Ok(()) => stats.drawers_written += 1,
                Err(mempalace_store::palace::PalaceError::Duplicate(_)) => {
                    stats.drawers_skipped_existing += 1;
                }
                Err(e) => return Err(IngestError::Palace(e)),
            }
        }
        Ok(())
    }
}

pub fn chunk_text(text: &str, size: usize, overlap: usize) -> Vec<String> {
    if text.is_empty() {
        return Vec::new();
    }
    if size == 0 {
        return vec![text.to_string()];
    }
    let chars: Vec<char> = text.chars().collect();
    let total = chars.len();
    if total <= size {
        return vec![text.to_string()];
    }

    let mut chunks = Vec::new();
    let stride = size.saturating_sub(overlap).max(1);
    let mut start = 0usize;
    while start < total {
        let end = (start + size).min(total);
        let slice: String = chars[start..end].iter().collect();
        chunks.push(slice);
        if end == total {
            break;
        }
        start += stride;
    }
    chunks
}

pub fn compute_drawer_id(source_file: &Path, chunk_index: usize, chunk: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(source_file.to_string_lossy().as_bytes());
    hasher.update(b"::");
    hasher.update(chunk_index.to_le_bytes());
    hasher.update(b"::");
    hasher.update(chunk.as_bytes());
    let digest = hasher.finalize();
    let hex = digest
        .iter()
        .take(12)
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    format!("drawer_{hex}")
}

fn today_iso() -> String {
    static INIT: OnceLock<()> = OnceLock::new();
    let _ = INIT;
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let days = (secs / 86_400) as i64;
    let (y, m, d) = civil_from_days(days);
    format!("{y:04}-{m:02}-{d:02}")
}

fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    let y = if m <= 2 { y + 1 } else { y };
    (y, m, d)
}

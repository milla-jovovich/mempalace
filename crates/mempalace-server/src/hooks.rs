//! Pure-Rust hook logic for Claude Code save/precompact triggers.
//!
//! The Python equivalents lived in `mempalace/hooks_cli.py` plus shell
//! scripts under `hooks/`. Shelling out to bash was a known security
//! risk (#110, fixed). This Rust port executes the same logic without
//! any shell invocation.

use std::path::{Path, PathBuf};

use mempalace_store::palace::{DrawerMetadata, DrawerRecord, Palace, PalaceError};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum HookError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("palace error: {0}")]
    Palace(#[from] PalaceError),
    #[error("empty content")]
    Empty,
}

pub type Result<T> = std::result::Result<T, HookError>;

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SaveRequest {
    pub wing: Option<String>,
    pub room: Option<String>,
    pub source: Option<String>,
    pub content: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SaveResult {
    pub drawer_id: String,
    pub chars_written: usize,
    pub deduped: bool,
}

#[derive(Debug)]
pub struct SaveHook {
    pub trigger_every_messages: usize,
}

impl Default for SaveHook {
    fn default() -> Self {
        Self {
            trigger_every_messages: 15,
        }
    }
}

impl SaveHook {
    pub fn new(trigger_every_messages: usize) -> Self {
        Self {
            trigger_every_messages,
        }
    }

    pub fn save(&self, palace: &mut dyn Palace, req: SaveRequest) -> Result<SaveResult> {
        let content = req.content.trim();
        if content.is_empty() {
            return Err(HookError::Empty);
        }

        let drawer_id = compute_id(&req.source, content);
        let record = DrawerRecord {
            id: drawer_id.clone(),
            content: content.to_string(),
            metadata: DrawerMetadata {
                wing: req.wing,
                room: req.room.or_else(|| Some("general".to_string())),
                hall: Some("hall_events".to_string()),
                source_file: req.source.clone(),
                date: Some(today_iso()),
                importance: Some(3.0),
                ..DrawerMetadata::default()
            },
        };

        match palace.add(record) {
            Ok(()) => Ok(SaveResult {
                drawer_id,
                chars_written: content.len(),
                deduped: false,
            }),
            Err(PalaceError::Duplicate(id)) => Ok(SaveResult {
                drawer_id: id,
                chars_written: 0,
                deduped: true,
            }),
            Err(e) => Err(HookError::Palace(e)),
        }
    }

    pub fn run_auto_ingest(
        &self,
        palace: &mut dyn Palace,
        source_dir: &Path,
        wing: Option<String>,
    ) -> Result<crate::ingest::IngestStats> {
        use crate::ingest::{Miner, MinerOptions};
        let miner = Miner::new(MinerOptions {
            wing,
            ..MinerOptions::default()
        });
        miner.mine(source_dir, palace).map_err(|e| match e {
            crate::ingest::IngestError::Io(e) => HookError::Io(e),
            crate::ingest::IngestError::Palace(e) => HookError::Palace(e),
            crate::ingest::IngestError::NotADirectory(p) => HookError::Io(std::io::Error::other(
                format!("not a directory: {}", p.display()),
            )),
            crate::ingest::IngestError::SymlinkRejected(p) => HookError::Io(std::io::Error::other(
                format!("symlink rejected: {}", p.display()),
            )),
        })
    }
}

fn compute_id(source: &Option<String>, content: &str) -> String {
    let mut hasher = Sha256::new();
    if let Some(s) = source {
        hasher.update(s.as_bytes());
    }
    hasher.update(b"::");
    hasher.update(content.as_bytes());
    let digest = hasher.finalize();
    let hex = digest
        .iter()
        .take(12)
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    format!("hook_{hex}")
}

fn today_iso() -> String {
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

pub fn precompact_save(palace: &mut dyn Palace, req: SaveRequest) -> Result<SaveResult> {
    SaveHook::default().save(palace, req)
}

pub fn resolve_mempal_dir() -> Option<PathBuf> {
    std::env::var_os("MEMPAL_DIR").map(PathBuf::from)
}

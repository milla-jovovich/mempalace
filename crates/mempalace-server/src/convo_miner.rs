//! Conversation miner — port of Python `mempalace/convo_miner.py`.
//!
//! Ingests chat exports (Claude Code, ChatGPT, Slack, plain text transcripts).
//! Normalizes format, chunks by exchange pair (Q+A = one unit), files to palace.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use mempalace_store::palace::{DrawerMetadata, DrawerRecord, Palace, PalaceError};
use mempalace_text::general_extractor::{extract_memories, MemoryType};
use mempalace_text::normalize::normalize;
use sha2::{Digest, Sha256};
use thiserror::Error;

// ── Constants ──────────────────────────────────────────────────────────

/// File extensions considered as potential conversation files.
pub const CONVO_EXTENSIONS: &[&str] = &[".txt", ".md", ".json", ".jsonl"];

/// Minimum chunk size in characters — shorter chunks are discarded.
pub const MIN_CHUNK_SIZE: usize = 30;

/// Maximum file size in bytes (10 MB).
pub const MAX_FILE_SIZE: u64 = 10 * 1024 * 1024;

/// Directories to skip when scanning.
const SKIP_DIRS: &[&str] = &[
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    "target",
    "dist",
    "build",
    ".eggs",
    ".nox",
];

// ── Types ──────────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum ConvoMineError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("palace error: {0}")]
    Palace(#[from] PalaceError),
    #[error("not a directory: {0}")]
    NotADirectory(PathBuf),
}

pub type Result<T> = std::result::Result<T, ConvoMineError>;

/// A single chunk extracted from a conversation.
#[derive(Debug, Clone)]
pub struct ConvoChunk {
    pub content: String,
    pub chunk_index: usize,
}

/// Extraction strategy.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExtractMode {
    /// Exchange-pair chunking: Q+A = one unit.
    Exchange,
    /// General extractor: decisions, preferences, milestones, problems, emotions.
    General,
}

/// Statistics returned after mining.
#[derive(Debug, Clone, Default)]
pub struct ConvoMineStats {
    pub files_processed: usize,
    pub files_skipped: usize,
    pub drawers_filed: usize,
    pub room_counts: BTreeMap<String, usize>,
}

/// Conversation miner.
#[derive(Debug)]
pub struct ConvoMiner {
    pub wing: Option<String>,
    pub extract_mode: ExtractMode,
    /// Maximum number of files to process (0 = no limit).
    pub limit: usize,
    pub dry_run: bool,
}

// ── Topic keywords for room detection ──────────────────────────────────

struct TopicEntry {
    room: &'static str,
    keywords: &'static [&'static str],
}

const TOPIC_KEYWORDS: &[TopicEntry] = &[
    TopicEntry {
        room: "technical",
        keywords: &[
            "code", "python", "function", "bug", "error", "api", "database", "server", "deploy",
            "git", "test", "debug", "refactor",
        ],
    },
    TopicEntry {
        room: "architecture",
        keywords: &[
            "architecture",
            "design",
            "pattern",
            "structure",
            "schema",
            "interface",
            "module",
            "component",
            "service",
            "layer",
        ],
    },
    TopicEntry {
        room: "planning",
        keywords: &[
            "plan",
            "roadmap",
            "milestone",
            "deadline",
            "priority",
            "sprint",
            "backlog",
            "scope",
            "requirement",
            "spec",
        ],
    },
    TopicEntry {
        room: "decisions",
        keywords: &[
            "decided",
            "chose",
            "picked",
            "switched",
            "migrated",
            "replaced",
            "trade-off",
            "alternative",
            "option",
            "approach",
        ],
    },
    TopicEntry {
        room: "problems",
        keywords: &[
            "problem",
            "issue",
            "broken",
            "failed",
            "crash",
            "stuck",
            "workaround",
            "fix",
            "solved",
            "resolved",
        ],
    },
];

// ── Chunking ───────────────────────────────────────────────────────────

/// Chunk conversation content into exchange pairs or paragraphs.
///
/// If the content has >= 3 lines starting with `>`, uses exchange-pair
/// chunking. Otherwise falls back to paragraph chunking.
pub fn chunk_exchanges(content: &str) -> Vec<ConvoChunk> {
    let lines: Vec<&str> = content.split('\n').collect();
    let quote_count = lines
        .iter()
        .filter(|l| l.trim_start().starts_with('>'))
        .count();

    if quote_count >= 3 {
        chunk_by_exchange(&lines)
    } else {
        chunk_by_paragraph(content)
    }
}

fn chunk_by_exchange(lines: &[&str]) -> Vec<ConvoChunk> {
    let mut chunks = Vec::new();
    let mut i = 0;

    while i < lines.len() {
        let line = lines[i];
        if line.trim_start().starts_with('>') {
            let user_turn = line.trim().to_string();
            i += 1;

            let mut ai_lines = Vec::new();
            while i < lines.len() {
                let next = lines[i];
                let trimmed = next.trim();
                if trimmed.starts_with('>') || trimmed.starts_with("---") {
                    break;
                }
                if !trimmed.is_empty() {
                    ai_lines.push(trimmed.to_string());
                }
                i += 1;
            }

            let ai_response: String = ai_lines.into_iter().take(8).collect::<Vec<_>>().join(" ");
            let content = if ai_response.is_empty() {
                user_turn
            } else {
                format!("{user_turn}\n{ai_response}")
            };

            if content.trim().len() > MIN_CHUNK_SIZE {
                chunks.push(ConvoChunk {
                    content,
                    chunk_index: chunks.len(),
                });
            }
        } else {
            i += 1;
        }
    }

    chunks
}

fn chunk_by_paragraph(content: &str) -> Vec<ConvoChunk> {
    let mut chunks = Vec::new();
    let paragraphs: Vec<&str> = content
        .split("\n\n")
        .map(str::trim)
        .filter(|p| !p.is_empty())
        .collect();

    // If only 1 paragraph and >20 newlines, chunk by 25-line groups.
    if paragraphs.len() <= 1 && content.matches('\n').count() > 20 {
        let lines: Vec<&str> = content.split('\n').collect();
        for start in (0..lines.len()).step_by(25) {
            let end = (start + 25).min(lines.len());
            let group = lines[start..end].join("\n");
            let group = group.trim().to_string();
            if group.len() > MIN_CHUNK_SIZE {
                chunks.push(ConvoChunk {
                    content: group,
                    chunk_index: chunks.len(),
                });
            }
        }
        return chunks;
    }

    for para in paragraphs {
        if para.len() > MIN_CHUNK_SIZE {
            chunks.push(ConvoChunk {
                content: para.to_string(),
                chunk_index: chunks.len(),
            });
        }
    }

    chunks
}

// ── Room detection ─────────────────────────────────────────────────────

/// Score conversation content against topic keywords and return best room.
pub fn detect_convo_room(content: &str) -> &'static str {
    let sample: String = content.chars().take(3000).collect();
    let content_lower = sample.to_lowercase();

    let mut best_room: &str = "general";
    let mut best_score: usize = 0;

    for entry in TOPIC_KEYWORDS {
        let score = entry
            .keywords
            .iter()
            .filter(|kw| content_lower.contains(*kw))
            .count();
        if score > best_score {
            best_score = score;
            best_room = entry.room;
        }
    }

    best_room
}

// ── Scanning ───────────────────────────────────────────────────────────

/// Walk `dir` and return conversation files (respecting skip-dirs, extension filter, etc.).
pub fn scan_convos(dir: &Path) -> Vec<PathBuf> {
    let mut files = Vec::new();
    scan_convos_recurse(dir, &mut files);
    files
}

fn scan_convos_recurse(dir: &Path, files: &mut Vec<PathBuf>) {
    let entries = match std::fs::read_dir(dir) {
        Ok(e) => e,
        Err(_) => return,
    };

    for entry in entries.flatten() {
        let path = entry.path();
        if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
            if path.is_dir() {
                if SKIP_DIRS.contains(&name) {
                    continue;
                }
                scan_convos_recurse(&path, files);
                continue;
            }

            // Skip symlinks
            if let Ok(meta) = std::fs::symlink_metadata(&path) {
                if meta.file_type().is_symlink() {
                    continue;
                }
                if meta.len() > MAX_FILE_SIZE {
                    continue;
                }
            } else {
                continue;
            }

            // Skip .meta.json files
            if name.ends_with(".meta.json") {
                continue;
            }

            // Check extension
            let ext = path
                .extension()
                .and_then(|e| e.to_str())
                .map(|e| format!(".{}", e.to_lowercase()));

            if let Some(ref ext) = ext {
                if CONVO_EXTENSIONS.contains(&ext.as_str()) {
                    files.push(path);
                }
            }
        }
    }
}

// ── Mining ──────────────────────────────────────────────────────────────

impl ConvoMiner {
    pub fn new() -> Self {
        Self {
            wing: None,
            extract_mode: ExtractMode::Exchange,
            limit: 0,
            dry_run: false,
        }
    }

    /// Mine conversation files from `dir` into `palace`.
    pub fn mine(&self, dir: &Path, palace: &mut dyn Palace) -> Result<ConvoMineStats> {
        if !dir.is_dir() {
            return Err(ConvoMineError::NotADirectory(dir.to_path_buf()));
        }

        let wing = self.wing.clone().unwrap_or_else(|| {
            dir.file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("convos")
                .to_lowercase()
                .replace([' ', '-'], "_")
        });

        let mut files = scan_convos(dir);
        if self.limit > 0 && files.len() > self.limit {
            files.truncate(self.limit);
        }

        let mut stats = ConvoMineStats::default();

        for filepath in &files {
            let source_file = filepath.to_string_lossy().to_string();

            // Normalize
            let content = match normalize(filepath) {
                Ok(c) => c,
                Err(_) => {
                    stats.files_skipped += 1;
                    continue;
                }
            };

            if content.trim().len() < MIN_CHUNK_SIZE {
                stats.files_skipped += 1;
                continue;
            }

            match self.extract_mode {
                ExtractMode::Exchange => {
                    let chunks = chunk_exchanges(&content);
                    if chunks.is_empty() {
                        stats.files_skipped += 1;
                        continue;
                    }

                    let room = detect_convo_room(&content).to_string();
                    *stats.room_counts.entry(room.clone()).or_insert(0) += 1;

                    if self.dry_run {
                        stats.drawers_filed += chunks.len();
                        stats.files_processed += 1;
                        continue;
                    }

                    for chunk in &chunks {
                        let drawer_id =
                            make_drawer_id(&wing, &room, &source_file, chunk.chunk_index);
                        let record = DrawerRecord {
                            id: drawer_id,
                            content: chunk.content.clone(),
                            metadata: DrawerMetadata {
                                wing: Some(wing.clone()),
                                room: Some(room.clone()),
                                source_file: Some(source_file.clone()),
                                ..DrawerMetadata::default()
                            },
                        };
                        match palace.add(record) {
                            Ok(()) => stats.drawers_filed += 1,
                            Err(PalaceError::Duplicate(_)) => { /* skip silently */ }
                            Err(e) => return Err(ConvoMineError::Palace(e)),
                        }
                    }
                }
                ExtractMode::General => {
                    let memories = extract_memories(&content, 0.0);
                    if memories.is_empty() {
                        stats.files_skipped += 1;
                        continue;
                    }

                    if self.dry_run {
                        for mem in &memories {
                            let room = memory_type_to_room(&mem.memory_type);
                            *stats.room_counts.entry(room.to_string()).or_insert(0) += 1;
                        }
                        stats.drawers_filed += memories.len();
                        stats.files_processed += 1;
                        continue;
                    }

                    for mem in &memories {
                        let room = memory_type_to_room(&mem.memory_type).to_string();
                        *stats.room_counts.entry(room.clone()).or_insert(0) += 1;

                        let drawer_id =
                            make_drawer_id(&wing, &room, &source_file, mem.chunk_index as usize);
                        let record = DrawerRecord {
                            id: drawer_id,
                            content: mem.content.clone(),
                            metadata: DrawerMetadata {
                                wing: Some(wing.clone()),
                                room: Some(room),
                                source_file: Some(source_file.clone()),
                                ..DrawerMetadata::default()
                            },
                        };
                        match palace.add(record) {
                            Ok(()) => stats.drawers_filed += 1,
                            Err(PalaceError::Duplicate(_)) => { /* skip silently */ }
                            Err(e) => return Err(ConvoMineError::Palace(e)),
                        }
                    }
                }
            }

            stats.files_processed += 1;
        }

        Ok(stats)
    }
}

impl Default for ConvoMiner {
    fn default() -> Self {
        Self::new()
    }
}

/// Map `MemoryType` to a room name.
fn memory_type_to_room(mt: &MemoryType) -> &'static str {
    match mt {
        MemoryType::Decision => "decisions",
        MemoryType::Preference => "preferences",
        MemoryType::Milestone => "milestones",
        MemoryType::Problem => "problems",
        MemoryType::Emotional => "emotional",
    }
}

/// Generate a deterministic drawer ID from wing, room, source file, and chunk index.
fn make_drawer_id(wing: &str, room: &str, source_file: &str, chunk_index: usize) -> String {
    let mut hasher = Sha256::new();
    hasher.update(source_file.as_bytes());
    hasher.update(chunk_index.to_string().as_bytes());
    let digest = hasher.finalize();
    let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();
    format!("drawer_{wing}_{room}_{}", &hex[..24])
}

// ── Tests ──────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use mempalace_store::palace::InMemoryPalace;
    use tempfile::TempDir;

    #[test]
    fn test_exchange_chunking() {
        let content = "\
> What is memory?
Memory is persistence of information over time.

> Why does it matter?
It enables continuity across sessions and conversations.

> How do we build it?
With structured storage and retrieval mechanisms.
";
        let chunks = chunk_exchanges(content);
        assert!(
            chunks.len() >= 2,
            "expected >= 2 chunks, got {}",
            chunks.len()
        );
        assert!(chunks.iter().all(|c| !c.content.is_empty()));
    }

    #[test]
    fn test_paragraph_fallback() {
        let content = format!(
            "{}\n\n{}\n\n{}",
            "This is a long paragraph about memory systems. ".repeat(10),
            "This is another paragraph about storage. ".repeat(10),
            "And a third paragraph about retrieval. ".repeat(10),
        );
        let chunks = chunk_exchanges(&content);
        assert!(
            chunks.len() >= 2,
            "expected >= 2 paragraph chunks, got {}",
            chunks.len()
        );
    }

    #[test]
    fn test_paragraph_line_group_fallback() {
        let lines: Vec<String> = (0..60)
            .map(|i| format!("Line {i}: some content that is meaningful"))
            .collect();
        let content = lines.join("\n");
        let chunks = chunk_exchanges(&content);
        assert!(
            !chunks.is_empty(),
            "expected >= 1 line-group chunks, got {}",
            chunks.len()
        );
    }

    #[test]
    fn test_empty_content() {
        let chunks = chunk_exchanges("");
        assert!(chunks.is_empty());
    }

    #[test]
    fn test_short_content_skipped() {
        let chunks = chunk_exchanges("> hi\nbye");
        // Too short to produce chunks (below MIN_CHUNK_SIZE)
        assert!(chunks.is_empty() || chunks.iter().all(|c| c.content.len() > MIN_CHUNK_SIZE));
    }

    #[test]
    fn test_detect_technical_room() {
        let content = "Let me debug this python function and fix the code error in the api";
        assert_eq!(detect_convo_room(content), "technical");
    }

    #[test]
    fn test_detect_planning_room() {
        let content = "We need to plan the roadmap for the next sprint and set milestone deadlines";
        assert_eq!(detect_convo_room(content), "planning");
    }

    #[test]
    fn test_detect_architecture_room() {
        let content =
            "The architecture uses a service layer with component interface and module design";
        assert_eq!(detect_convo_room(content), "architecture");
    }

    #[test]
    fn test_detect_decisions_room() {
        let content = "We decided to switch and migrated to the new framework after we chose it";
        assert_eq!(detect_convo_room(content), "decisions");
    }

    #[test]
    fn test_detect_general_fallback() {
        let content = "Hello, how are you doing today? The weather is nice.";
        assert_eq!(detect_convo_room(content), "general");
    }

    #[test]
    fn test_scan_finds_txt_and_md() {
        let tmp = TempDir::new().unwrap();
        std::fs::write(tmp.path().join("chat.txt"), "hello").unwrap();
        std::fs::write(tmp.path().join("notes.md"), "world").unwrap();
        std::fs::write(tmp.path().join("image.png"), b"fake").unwrap();

        let files = scan_convos(tmp.path());
        let extensions: Vec<String> = files
            .iter()
            .filter_map(|f| {
                f.extension()
                    .and_then(|e| e.to_str())
                    .map(|e| format!(".{e}"))
            })
            .collect();
        assert!(extensions.contains(&".txt".to_string()));
        assert!(extensions.contains(&".md".to_string()));
        assert!(!extensions.contains(&".png".to_string()));
    }

    #[test]
    fn test_scan_skips_git_dir() {
        let tmp = TempDir::new().unwrap();
        let git_dir = tmp.path().join(".git");
        std::fs::create_dir(&git_dir).unwrap();
        std::fs::write(git_dir.join("config.txt"), "git stuff").unwrap();
        std::fs::write(tmp.path().join("chat.txt"), "hello").unwrap();

        let files = scan_convos(tmp.path());
        assert_eq!(files.len(), 1);
    }

    #[test]
    fn test_scan_skips_meta_json() {
        let tmp = TempDir::new().unwrap();
        std::fs::write(tmp.path().join("chat.meta.json"), "{}").unwrap();
        std::fs::write(tmp.path().join("chat.json"), "{}").unwrap();

        let files = scan_convos(tmp.path());
        let names: Vec<String> = files
            .iter()
            .filter_map(|f| f.file_name().and_then(|n| n.to_str()).map(String::from))
            .collect();
        assert!(names.contains(&"chat.json".to_string()));
        assert!(!names.contains(&"chat.meta.json".to_string()));
    }

    #[test]
    fn test_scan_empty_dir() {
        let tmp = TempDir::new().unwrap();
        let files = scan_convos(tmp.path());
        assert!(files.is_empty());
    }

    #[test]
    fn test_mine_roundtrip() {
        let tmp = TempDir::new().unwrap();
        let chat_content = "\
> What is memory?
Memory is persistence of information over time and it matters a lot.

> Why does it matter?
It enables continuity across sessions and conversations between agents.

> How do we build it?
With structured storage and retrieval mechanisms that work reliably.
";
        std::fs::write(tmp.path().join("chat.txt"), chat_content).unwrap();

        let mut palace = InMemoryPalace::new();
        let miner = ConvoMiner {
            wing: Some("test_convos".to_string()),
            extract_mode: ExtractMode::Exchange,
            limit: 0,
            dry_run: false,
        };

        let stats = miner.mine(tmp.path(), &mut palace).unwrap();
        assert!(
            stats.drawers_filed >= 2,
            "expected >= 2 drawers, got {}",
            stats.drawers_filed
        );
        assert_eq!(stats.files_processed, 1);
        assert!(palace.count().unwrap() >= 2);
    }
}

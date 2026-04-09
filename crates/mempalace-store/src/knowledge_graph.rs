//! Temporal entity-relationship knowledge graph backed by SQLite.
//!
//! Port of Python `mempalace/knowledge_graph.py`.

use std::path::{Path, PathBuf};

use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum KnowledgeGraphError {
    #[error("sqlite error: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
}

pub type Result<T> = std::result::Result<T, KnowledgeGraphError>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Direction {
    Outgoing,
    Incoming,
    Both,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Triple {
    pub direction: String,
    pub subject: String,
    pub predicate: String,
    pub object: String,
    pub valid_from: Option<String>,
    pub valid_to: Option<String>,
    pub confidence: f64,
    pub source_closet: Option<String>,
    pub current: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimelineEntry {
    pub subject: String,
    pub predicate: String,
    pub object: String,
    pub valid_from: Option<String>,
    pub valid_to: Option<String>,
    pub current: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Stats {
    pub entities: i64,
    pub triples: i64,
    pub current_facts: i64,
    pub expired_facts: i64,
    pub relationship_types: Vec<String>,
}

#[derive(Debug)]
pub struct KnowledgeGraph {
    conn: Connection,
    db_path: PathBuf,
}

impl KnowledgeGraph {
    pub fn default_path() -> PathBuf {
        let home = mempalace_core::home_dir().unwrap_or_else(|| PathBuf::from("/tmp"));
        home.join(".mempalace").join("knowledge_graph.sqlite3")
    }

    pub fn open<P: AsRef<Path>>(db_path: P) -> Result<Self> {
        let db_path = db_path.as_ref().to_path_buf();
        if let Some(parent) = db_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let conn = Connection::open(&db_path)?;
        let this = Self { conn, db_path };
        this.init_schema()?;
        Ok(this)
    }

    pub fn open_default() -> Result<Self> {
        Self::open(Self::default_path())
    }

    pub fn db_path(&self) -> &Path {
        &self.db_path
    }

    fn init_schema(&self) -> Result<()> {
        self.conn.execute_batch(
            r"
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT DEFAULT 'unknown',
                properties TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS triples (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                valid_from TEXT,
                valid_to TEXT,
                confidence REAL DEFAULT 1.0,
                source_closet TEXT,
                source_file TEXT,
                extracted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (subject) REFERENCES entities(id),
                FOREIGN KEY (object) REFERENCES entities(id)
            );

            CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
            CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);
            CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
            CREATE INDEX IF NOT EXISTS idx_triples_valid ON triples(valid_from, valid_to);
            ",
        )?;
        Ok(())
    }

    pub fn entity_id(name: &str) -> String {
        name.to_lowercase().replace(' ', "_").replace('\'', "")
    }

    pub fn add_entity(
        &self,
        name: &str,
        entity_type: &str,
        properties: Option<&serde_json::Value>,
    ) -> Result<String> {
        let eid = Self::entity_id(name);
        let props = match properties {
            Some(v) => serde_json::to_string(v)?,
            None => "{}".to_string(),
        };
        self.conn.execute(
            "INSERT OR REPLACE INTO entities (id, name, type, properties) VALUES (?, ?, ?, ?)",
            params![eid, name, entity_type, props],
        )?;
        Ok(eid)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn add_triple(
        &self,
        subject: &str,
        predicate: &str,
        object: &str,
        valid_from: Option<&str>,
        valid_to: Option<&str>,
        confidence: f64,
        source_closet: Option<&str>,
        source_file: Option<&str>,
    ) -> Result<String> {
        let sub_id = Self::entity_id(subject);
        let obj_id = Self::entity_id(object);
        let pred = predicate.to_lowercase().replace(' ', "_");

        self.conn.execute(
            "INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)",
            params![sub_id, subject],
        )?;
        self.conn.execute(
            "INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)",
            params![obj_id, object],
        )?;

        let existing: Option<String> = self
            .conn
            .query_row(
                "SELECT id FROM triples WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
                params![sub_id, pred, obj_id],
                |row| row.get(0),
            )
            .optional()?;

        if let Some(id) = existing {
            return Ok(id);
        }

        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos().to_string())
            .unwrap_or_else(|_| "0".to_string());

        let seed = format!("{}{}", valid_from.unwrap_or(""), now);
        let mut hasher = Sha256::new();
        hasher.update(seed.as_bytes());
        let hash_hex = hex_short(&hasher.finalize());
        let triple_id = format!("t_{sub_id}_{pred}_{obj_id}_{hash_hex}");

        self.conn.execute(
            "INSERT INTO triples (id, subject, predicate, object, valid_from, valid_to, confidence, source_closet, source_file)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            params![triple_id, sub_id, pred, obj_id, valid_from, valid_to, confidence, source_closet, source_file],
        )?;

        Ok(triple_id)
    }

    pub fn invalidate(
        &self,
        subject: &str,
        predicate: &str,
        object: &str,
        ended: Option<&str>,
    ) -> Result<usize> {
        let sub_id = Self::entity_id(subject);
        let obj_id = Self::entity_id(object);
        let pred = predicate.to_lowercase().replace(' ', "_");
        let ended_str: String = ended.map(str::to_string).unwrap_or_else(today_iso_date);

        let n = self.conn.execute(
            "UPDATE triples SET valid_to=? WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
            params![ended_str, sub_id, pred, obj_id],
        )?;
        Ok(n)
    }

    pub fn query_entity(
        &self,
        name: &str,
        as_of: Option<&str>,
        direction: Direction,
    ) -> Result<Vec<Triple>> {
        let eid = Self::entity_id(name);
        let mut results = Vec::new();

        if matches!(direction, Direction::Outgoing | Direction::Both) {
            let mut sql = String::from(
                "SELECT t.predicate, t.object, t.valid_from, t.valid_to, t.confidence, t.source_closet, e.name as obj_name \
                 FROM triples t JOIN entities e ON t.object = e.id WHERE t.subject = ?",
            );
            if as_of.is_some() {
                sql.push_str(
                    " AND (t.valid_from IS NULL OR t.valid_from <= ?) \
                       AND (t.valid_to IS NULL OR t.valid_to >= ?)",
                );
            }

            let mut stmt = self.conn.prepare(&sql)?;
            let rows: Vec<Triple> = if let Some(ao) = as_of {
                stmt.query_map(params![eid, ao, ao], |row| {
                    Ok(Triple {
                        direction: "outgoing".to_string(),
                        subject: name.to_string(),
                        predicate: row.get::<_, String>(0)?,
                        object: row.get::<_, String>(6)?,
                        valid_from: row.get::<_, Option<String>>(2)?,
                        valid_to: row.get::<_, Option<String>>(3)?,
                        confidence: row.get::<_, f64>(4)?,
                        source_closet: row.get::<_, Option<String>>(5)?,
                        current: row.get::<_, Option<String>>(3)?.is_none(),
                    })
                })?
                .collect::<rusqlite::Result<Vec<_>>>()?
            } else {
                stmt.query_map(params![eid], |row| {
                    Ok(Triple {
                        direction: "outgoing".to_string(),
                        subject: name.to_string(),
                        predicate: row.get::<_, String>(0)?,
                        object: row.get::<_, String>(6)?,
                        valid_from: row.get::<_, Option<String>>(2)?,
                        valid_to: row.get::<_, Option<String>>(3)?,
                        confidence: row.get::<_, f64>(4)?,
                        source_closet: row.get::<_, Option<String>>(5)?,
                        current: row.get::<_, Option<String>>(3)?.is_none(),
                    })
                })?
                .collect::<rusqlite::Result<Vec<_>>>()?
            };
            results.extend(rows);
        }

        if matches!(direction, Direction::Incoming | Direction::Both) {
            let mut sql = String::from(
                "SELECT t.predicate, t.subject, t.valid_from, t.valid_to, t.confidence, t.source_closet, e.name as sub_name \
                 FROM triples t JOIN entities e ON t.subject = e.id WHERE t.object = ?",
            );
            if as_of.is_some() {
                sql.push_str(
                    " AND (t.valid_from IS NULL OR t.valid_from <= ?) \
                       AND (t.valid_to IS NULL OR t.valid_to >= ?)",
                );
            }

            let mut stmt = self.conn.prepare(&sql)?;
            let rows: Vec<Triple> = if let Some(ao) = as_of {
                stmt.query_map(params![eid, ao, ao], |row| {
                    Ok(Triple {
                        direction: "incoming".to_string(),
                        subject: row.get::<_, String>(6)?,
                        predicate: row.get::<_, String>(0)?,
                        object: name.to_string(),
                        valid_from: row.get::<_, Option<String>>(2)?,
                        valid_to: row.get::<_, Option<String>>(3)?,
                        confidence: row.get::<_, f64>(4)?,
                        source_closet: row.get::<_, Option<String>>(5)?,
                        current: row.get::<_, Option<String>>(3)?.is_none(),
                    })
                })?
                .collect::<rusqlite::Result<Vec<_>>>()?
            } else {
                stmt.query_map(params![eid], |row| {
                    Ok(Triple {
                        direction: "incoming".to_string(),
                        subject: row.get::<_, String>(6)?,
                        predicate: row.get::<_, String>(0)?,
                        object: name.to_string(),
                        valid_from: row.get::<_, Option<String>>(2)?,
                        valid_to: row.get::<_, Option<String>>(3)?,
                        confidence: row.get::<_, f64>(4)?,
                        source_closet: row.get::<_, Option<String>>(5)?,
                        current: row.get::<_, Option<String>>(3)?.is_none(),
                    })
                })?
                .collect::<rusqlite::Result<Vec<_>>>()?
            };
            results.extend(rows);
        }

        Ok(results)
    }

    pub fn query_relationship(
        &self,
        predicate: &str,
        as_of: Option<&str>,
    ) -> Result<Vec<TimelineEntry>> {
        let pred = predicate.to_lowercase().replace(' ', "_");
        let mut sql = String::from(
            "SELECT t.predicate, t.valid_from, t.valid_to, s.name as sub_name, o.name as obj_name \
             FROM triples t \
             JOIN entities s ON t.subject = s.id \
             JOIN entities o ON t.object = o.id \
             WHERE t.predicate = ?",
        );
        if as_of.is_some() {
            sql.push_str(
                " AND (t.valid_from IS NULL OR t.valid_from <= ?) \
                   AND (t.valid_to IS NULL OR t.valid_to >= ?)",
            );
        }
        let mut stmt = self.conn.prepare(&sql)?;
        let rows: Vec<TimelineEntry> = if let Some(ao) = as_of {
            stmt.query_map(params![pred, ao, ao], |row| {
                Ok(TimelineEntry {
                    subject: row.get::<_, String>(3)?,
                    predicate: row.get::<_, String>(0)?,
                    object: row.get::<_, String>(4)?,
                    valid_from: row.get::<_, Option<String>>(1)?,
                    valid_to: row.get::<_, Option<String>>(2)?,
                    current: row.get::<_, Option<String>>(2)?.is_none(),
                })
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?
        } else {
            stmt.query_map(params![pred], |row| {
                Ok(TimelineEntry {
                    subject: row.get::<_, String>(3)?,
                    predicate: row.get::<_, String>(0)?,
                    object: row.get::<_, String>(4)?,
                    valid_from: row.get::<_, Option<String>>(1)?,
                    valid_to: row.get::<_, Option<String>>(2)?,
                    current: row.get::<_, Option<String>>(2)?.is_none(),
                })
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?
        };
        Ok(rows)
    }

    pub fn timeline(&self, entity_name: Option<&str>) -> Result<Vec<TimelineEntry>> {
        let (sql, eid_opt): (&str, Option<String>) = match entity_name {
            Some(name) => (
                "SELECT t.predicate, t.valid_from, t.valid_to, s.name as sub_name, o.name as obj_name \
                 FROM triples t \
                 JOIN entities s ON t.subject = s.id \
                 JOIN entities o ON t.object = o.id \
                 WHERE (t.subject = ?1 OR t.object = ?1) \
                 ORDER BY t.valid_from ASC NULLS LAST \
                 LIMIT 100",
                Some(Self::entity_id(name)),
            ),
            None => (
                "SELECT t.predicate, t.valid_from, t.valid_to, s.name as sub_name, o.name as obj_name \
                 FROM triples t \
                 JOIN entities s ON t.subject = s.id \
                 JOIN entities o ON t.object = o.id \
                 ORDER BY t.valid_from ASC NULLS LAST \
                 LIMIT 100",
                None,
            ),
        };

        let mut stmt = self.conn.prepare(sql)?;
        let rows: Vec<TimelineEntry> = if let Some(eid) = eid_opt {
            stmt.query_map(params![eid], |row| {
                Ok(TimelineEntry {
                    subject: row.get::<_, String>(3)?,
                    predicate: row.get::<_, String>(0)?,
                    object: row.get::<_, String>(4)?,
                    valid_from: row.get::<_, Option<String>>(1)?,
                    valid_to: row.get::<_, Option<String>>(2)?,
                    current: row.get::<_, Option<String>>(2)?.is_none(),
                })
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?
        } else {
            stmt.query_map([], |row| {
                Ok(TimelineEntry {
                    subject: row.get::<_, String>(3)?,
                    predicate: row.get::<_, String>(0)?,
                    object: row.get::<_, String>(4)?,
                    valid_from: row.get::<_, Option<String>>(1)?,
                    valid_to: row.get::<_, Option<String>>(2)?,
                    current: row.get::<_, Option<String>>(2)?.is_none(),
                })
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?
        };
        Ok(rows)
    }

    pub fn stats(&self) -> Result<Stats> {
        let entities: i64 = self
            .conn
            .query_row("SELECT COUNT(*) FROM entities", [], |r| r.get(0))?;
        let triples: i64 = self
            .conn
            .query_row("SELECT COUNT(*) FROM triples", [], |r| r.get(0))?;
        let current: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM triples WHERE valid_to IS NULL",
            [],
            |r| r.get(0),
        )?;
        let mut stmt = self
            .conn
            .prepare("SELECT DISTINCT predicate FROM triples ORDER BY predicate")?;
        let rows: Vec<String> = stmt
            .query_map([], |r| r.get::<_, String>(0))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(Stats {
            entities,
            triples,
            current_facts: current,
            expired_facts: triples - current,
            relationship_types: rows,
        })
    }
}

fn hex_short(bytes: &[u8]) -> String {
    const HEX: &[u8] = b"0123456789abcdef";
    let take = 6.min(bytes.len());
    let mut out = String::with_capacity(take * 2);
    for &b in &bytes[..take] {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

fn today_iso_date() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let days = secs / 86_400;
    let (year, month, day) = civil_from_days(days as i64);
    format!("{year:04}-{month:02}-{day:02}")
}

/// Convert days since Unix epoch (1970-01-01) to a proleptic Gregorian
/// date. Algorithm from Howard Hinnant's date library.
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

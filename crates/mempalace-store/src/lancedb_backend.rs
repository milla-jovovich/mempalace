//! Persistent [`Palace`] backend on top of `lancedb` + `fastembed`.
//!
//! This module provides [`LanceDbPalace`], a real semantic vector store
//! that replaces the in-memory reference backend for production use. It is
//! gated behind the `lancedb-backend` Cargo feature (on by default).
//!
//! ## Design notes
//!
//! - The [`Palace`] trait is **synchronous**, but `lancedb` is fully async.
//!   We solve this by owning a dedicated `tokio::runtime::Runtime` inside
//!   the struct and calling `runtime.block_on(...)` from each trait method.
//!   To avoid the classic "block_on inside a running runtime" panic, the
//!   constructor refuses to build if the caller is already inside a tokio
//!   runtime (`Handle::try_current().is_ok()`).
//!
//! - Embeddings use `fastembed` 5 with `AllMiniLML6V2` (384 dim).
//!
//! - Distance metric is **cosine**, so similarity is `1.0 - distance`.
//!
//! - The table schema keeps one Arrow row per drawer. `insert_seq` preserves
//!   insertion order for `list` / `list_filtered` (lancedb has no implicit
//!   row order guarantee).
//!
//! - Filter values are sanitised before being embedded in a SQL `where`
//!   clause: control characters cause a hard error, single quotes are
//!   escaped by doubling (`'` → `''`). This is the same rule Postgres and
//!   SQLite use for single-quoted literals.

use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;

use arrow_array::{
    Array, FixedSizeListArray, Float32Array, Float64Array, Int64Array, RecordBatch,
    RecordBatchIterator, StringArray,
};
use arrow_schema::{DataType, Field, Schema, SchemaRef};
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase};
use lancedb::{Connection, DistanceType, Table};
use tokio::runtime::{Handle, Runtime};
use tracing::debug;

use crate::palace::{
    DrawerMetadata, DrawerRecord, Palace, PalaceError, Result, SearchFilter, SearchResult,
};

/// Embedding dimensionality for `AllMiniLML6V2`.
pub const EMBEDDING_DIM: i32 = 384;

/// Default table name used by [`LanceDbPalace::new`].
pub const DEFAULT_TABLE_NAME: &str = "mempalace_drawers";

/// Real, persistent [`Palace`] backed by `lancedb` + `fastembed`.
pub struct LanceDbPalace {
    runtime: Runtime,
    connection: Connection,
    table: Table,
    embedder: Mutex<TextEmbedding>,
    next_seq: Mutex<i64>,
    table_name: String,
}

impl std::fmt::Debug for LanceDbPalace {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("LanceDbPalace")
            .field("table_name", &self.table_name)
            .finish()
    }
}

impl LanceDbPalace {
    /// Open (or create) a palace at `path` using the default table name.
    pub fn new(path: impl AsRef<Path>) -> Result<Self> {
        Self::new_with_table(path, DEFAULT_TABLE_NAME)
    }

    /// Open (or create) a palace at `path` with a specific table name.
    pub fn new_with_table(path: impl AsRef<Path>, table_name: &str) -> Result<Self> {
        if Handle::try_current().is_ok() {
            return Err(PalaceError::Backend(
                "LanceDbPalace cannot be constructed from within a running tokio runtime; \
                 use PalaceAsync-style callers or spawn a dedicated thread"
                    .to_string(),
            ));
        }

        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .worker_threads(2)
            .thread_name("mempalace-lancedb")
            .build()
            .map_err(|e| PalaceError::Backend(format!("failed to build tokio runtime: {e}")))?;

        let path_str = path
            .as_ref()
            .to_str()
            .ok_or_else(|| PalaceError::Backend("lancedb path is not valid UTF-8".to_string()))?
            .to_string();
        let table_name_owned = table_name.to_string();

        let schema = build_schema();

        let (connection, table) = runtime.block_on(async {
            let conn = lancedb::connect(&path_str)
                .execute()
                .await
                .map_err(|e| PalaceError::Backend(format!("lancedb connect failed: {e}")))?;

            let existing = conn
                .table_names()
                .execute()
                .await
                .map_err(|e| PalaceError::Backend(format!("list tables failed: {e}")))?;

            let table = if existing.iter().any(|n| n == &table_name_owned) {
                conn.open_table(&table_name_owned)
                    .execute()
                    .await
                    .map_err(|e| PalaceError::Backend(format!("open table failed: {e}")))?
            } else {
                conn.create_empty_table(&table_name_owned, schema.clone())
                    .execute()
                    .await
                    .map_err(|e| PalaceError::Backend(format!("create table failed: {e}")))?
            };

            Ok::<_, PalaceError>((conn, table))
        })?;

        let embedder = TextEmbedding::try_new(InitOptions::new(EmbeddingModel::AllMiniLML6V2))
            .map_err(|e| PalaceError::Backend(format!("fastembed init failed: {e}")))?;

        // Recover the max insert_seq so new rows continue the sequence across restarts.
        let next_seq = runtime.block_on(async { scan_max_seq(&table).await })?;

        debug!(
            table = %table_name_owned,
            next_seq = next_seq,
            "LanceDbPalace opened"
        );

        Ok(Self {
            runtime,
            connection,
            table,
            embedder: Mutex::new(embedder),
            next_seq: Mutex::new(next_seq),
            table_name: table_name_owned,
        })
    }

    fn embed_one(&self, text: &str) -> Result<Vec<f32>> {
        let mut guard = self
            .embedder
            .lock()
            .map_err(|e| PalaceError::Backend(format!("embedder mutex poisoned: {e}")))?;
        let out = guard
            .embed(vec![text.to_string()], None)
            .map_err(|e| PalaceError::Backend(format!("fastembed embed failed: {e}")))?;
        out.into_iter()
            .next()
            .ok_or_else(|| PalaceError::Backend("fastembed returned empty output".to_string()))
    }

    fn bump_seq(&self) -> Result<i64> {
        let mut g = self
            .next_seq
            .lock()
            .map_err(|e| PalaceError::Backend(format!("seq mutex poisoned: {e}")))?;
        let v = *g;
        *g = v.saturating_add(1);
        Ok(v)
    }
}

// ── Arrow schema ────────────────────────────────────────────────────────

/// Build the canonical Arrow schema used by [`LanceDbPalace`].
///
/// Exposed as `pub(crate)` so the unit test can assert on it without
/// instantiating the embedder (which would download model files).
pub(crate) fn build_schema() -> SchemaRef {
    let vector_field = Field::new("item", DataType::Float32, true);
    Arc::new(Schema::new(vec![
        Field::new("id", DataType::Utf8, false),
        Field::new("content", DataType::Utf8, false),
        Field::new(
            "vector",
            DataType::FixedSizeList(Arc::new(vector_field), EMBEDDING_DIM),
            false,
        ),
        Field::new("wing", DataType::Utf8, true),
        Field::new("room", DataType::Utf8, true),
        Field::new("hall", DataType::Utf8, true),
        Field::new("source_file", DataType::Utf8, true),
        Field::new("date", DataType::Utf8, true),
        Field::new("importance", DataType::Float64, true),
        Field::new("extra_json", DataType::Utf8, true),
        Field::new("insert_seq", DataType::Int64, false),
    ]))
}

// ── SQL-safe filter building ────────────────────────────────────────────

/// Escape a string value for inclusion as a SQL single-quoted literal.
///
/// Rejects any string containing control characters (`\x00..=\x1f` or
/// `\x7f`). Otherwise doubles single quotes.
pub(crate) fn escape_sql_literal(value: &str) -> Result<String> {
    if value.chars().any(|c| c.is_control()) {
        return Err(PalaceError::Backend(format!(
            "filter value contains control characters: {value:?}"
        )));
    }
    Ok(value.replace('\'', "''"))
}

fn build_where_clause(filter: &SearchFilter) -> Result<Option<String>> {
    let mut parts: Vec<String> = Vec::new();
    if let Some(w) = filter.wing.as_ref() {
        parts.push(format!("wing = '{}'", escape_sql_literal(w)?));
    }
    if let Some(r) = filter.room.as_ref() {
        parts.push(format!("room = '{}'", escape_sql_literal(r)?));
    }
    if parts.is_empty() {
        Ok(None)
    } else {
        Ok(Some(parts.join(" AND ")))
    }
}

// ── Helpers for reading lancedb rows back into DrawerRecord ────────────

async fn scan_max_seq(table: &Table) -> Result<i64> {
    let stream = table
        .query()
        .select(lancedb::query::Select::columns(&["insert_seq"]))
        .execute()
        .await
        .map_err(|e| PalaceError::Backend(format!("scan insert_seq failed: {e}")))?;
    let batches: Vec<RecordBatch> = stream
        .try_collect()
        .await
        .map_err(|e| PalaceError::Backend(format!("collect insert_seq failed: {e}")))?;
    let mut max_seen: i64 = -1;
    for batch in batches {
        let col = batch
            .column_by_name("insert_seq")
            .ok_or_else(|| PalaceError::Backend("insert_seq column missing".to_string()))?;
        let arr = col
            .as_any()
            .downcast_ref::<Int64Array>()
            .ok_or_else(|| PalaceError::Backend("insert_seq not Int64".to_string()))?;
        for i in 0..arr.len() {
            if !arr.is_null(i) {
                let v = arr.value(i);
                if v > max_seen {
                    max_seen = v;
                }
            }
        }
    }
    Ok(max_seen + 1)
}

fn read_string(batch: &RecordBatch, col: &str, row: usize) -> Result<Option<String>> {
    let Some(arr) = batch.column_by_name(col) else {
        return Ok(None);
    };
    let s = arr
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| PalaceError::Backend(format!("column `{col}` is not Utf8")))?;
    if s.is_null(row) {
        Ok(None)
    } else {
        Ok(Some(s.value(row).to_string()))
    }
}

fn read_f64(batch: &RecordBatch, col: &str, row: usize) -> Result<Option<f64>> {
    let Some(arr) = batch.column_by_name(col) else {
        return Ok(None);
    };
    let f = arr
        .as_any()
        .downcast_ref::<Float64Array>()
        .ok_or_else(|| PalaceError::Backend(format!("column `{col}` is not Float64")))?;
    if f.is_null(row) {
        Ok(None)
    } else {
        Ok(Some(f.value(row)))
    }
}

fn read_i64(batch: &RecordBatch, col: &str, row: usize) -> Result<Option<i64>> {
    let Some(arr) = batch.column_by_name(col) else {
        return Ok(None);
    };
    let f = arr
        .as_any()
        .downcast_ref::<Int64Array>()
        .ok_or_else(|| PalaceError::Backend(format!("column `{col}` is not Int64")))?;
    if f.is_null(row) {
        Ok(None)
    } else {
        Ok(Some(f.value(row)))
    }
}

fn row_to_record(batch: &RecordBatch, row: usize) -> Result<DrawerRecord> {
    let id = read_string(batch, "id", row)?
        .ok_or_else(|| PalaceError::Backend("row missing id".to_string()))?;
    let content = read_string(batch, "content", row)?
        .ok_or_else(|| PalaceError::Backend("row missing content".to_string()))?;

    let extra = match read_string(batch, "extra_json", row)? {
        Some(s) if !s.is_empty() => serde_json::from_str(&s)
            .map_err(|e| PalaceError::Backend(format!("extra_json deserialize failed: {e}")))?,
        _ => Default::default(),
    };

    let metadata = DrawerMetadata {
        wing: read_string(batch, "wing", row)?,
        room: read_string(batch, "room", row)?,
        hall: read_string(batch, "hall", row)?,
        source_file: read_string(batch, "source_file", row)?,
        date: read_string(batch, "date", row)?,
        importance: read_f64(batch, "importance", row)?,
        extra,
    };

    Ok(DrawerRecord {
        id,
        content,
        metadata,
    })
}

fn row_similarity(batch: &RecordBatch, row: usize) -> Result<f64> {
    let Some(col) = batch.column_by_name("_distance") else {
        return Ok(0.0);
    };
    let arr = col
        .as_any()
        .downcast_ref::<Float32Array>()
        .ok_or_else(|| PalaceError::Backend("_distance not Float32".to_string()))?;
    if arr.is_null(row) {
        return Ok(0.0);
    }
    // Cosine distance is in [0, 2]; similarity = 1 - distance puts it in [-1, 1].
    let distance = f64::from(arr.value(row));
    Ok(1.0 - distance)
}

fn build_insert_batch(
    schema: SchemaRef,
    record: &DrawerRecord,
    vector: Vec<f32>,
    seq: i64,
) -> Result<RecordBatch> {
    if vector.len() != EMBEDDING_DIM as usize {
        return Err(PalaceError::Backend(format!(
            "embedding has wrong dim: got {}, expected {}",
            vector.len(),
            EMBEDDING_DIM
        )));
    }

    let id = Arc::new(StringArray::from(vec![record.id.clone()])) as Arc<dyn Array>;
    let content = Arc::new(StringArray::from(vec![record.content.clone()])) as Arc<dyn Array>;

    let vector_array =
        FixedSizeListArray::from_iter_primitive::<arrow_array::types::Float32Type, _, _>(
            std::iter::once(Some(vector.into_iter().map(Some).collect::<Vec<_>>())),
            EMBEDDING_DIM,
        );
    let vector: Arc<dyn Array> = Arc::new(vector_array);

    let wing = Arc::new(StringArray::from(vec![record.metadata.wing.clone()])) as Arc<dyn Array>;
    let room = Arc::new(StringArray::from(vec![record.metadata.room.clone()])) as Arc<dyn Array>;
    let hall = Arc::new(StringArray::from(vec![record.metadata.hall.clone()])) as Arc<dyn Array>;
    let source_file =
        Arc::new(StringArray::from(vec![record.metadata.source_file.clone()])) as Arc<dyn Array>;
    let date = Arc::new(StringArray::from(vec![record.metadata.date.clone()])) as Arc<dyn Array>;
    let importance =
        Arc::new(Float64Array::from(vec![record.metadata.importance])) as Arc<dyn Array>;

    let extra_json_str = if record.metadata.extra.is_empty() {
        None
    } else {
        Some(
            serde_json::to_string(&record.metadata.extra)
                .map_err(|e| PalaceError::Backend(format!("extra_json serialize failed: {e}")))?,
        )
    };
    let extra_json = Arc::new(StringArray::from(vec![extra_json_str])) as Arc<dyn Array>;

    let insert_seq = Arc::new(Int64Array::from(vec![seq])) as Arc<dyn Array>;

    RecordBatch::try_new(
        schema,
        vec![
            id,
            content,
            vector,
            wing,
            room,
            hall,
            source_file,
            date,
            importance,
            extra_json,
            insert_seq,
        ],
    )
    .map_err(|e| PalaceError::Backend(format!("build record batch failed: {e}")))
}

impl Palace for LanceDbPalace {
    fn count(&self) -> Result<usize> {
        self.runtime.block_on(async {
            self.table
                .count_rows(None)
                .await
                .map_err(|e| PalaceError::Backend(format!("count_rows failed: {e}")))
        })
    }

    fn add(&mut self, record: DrawerRecord) -> Result<()> {
        // Pre-check for duplicate id — lancedb does not enforce primary keys.
        let id_escaped = escape_sql_literal(&record.id)?;
        let filter = format!("id = '{id_escaped}'");
        let existing = self.runtime.block_on(async {
            self.table
                .count_rows(Some(filter.clone()))
                .await
                .map_err(|e| PalaceError::Backend(format!("duplicate check failed: {e}")))
        })?;
        if existing > 0 {
            return Err(PalaceError::Duplicate(record.id));
        }

        let vector = self.embed_one(&record.content)?;
        let seq = self.bump_seq()?;
        let schema = build_schema();
        let batch = build_insert_batch(schema.clone(), &record, vector, seq)?;

        let reader: Box<dyn arrow_array::RecordBatchReader + Send> = Box::new(
            RecordBatchIterator::new(vec![Ok(batch)].into_iter(), schema),
        );

        self.runtime.block_on(async {
            self.table
                .add(reader)
                .execute()
                .await
                .map(|_| ())
                .map_err(|e| PalaceError::Backend(format!("add failed: {e}")))
        })
    }

    fn delete(&mut self, id: &str) -> Result<bool> {
        let id_escaped = escape_sql_literal(id)?;
        let predicate = format!("id = '{id_escaped}'");
        self.runtime.block_on(async {
            let before = self
                .table
                .count_rows(Some(predicate.clone()))
                .await
                .map_err(|e| PalaceError::Backend(format!("pre-delete count failed: {e}")))?;
            if before == 0 {
                return Ok(false);
            }
            self.table
                .delete(&predicate)
                .await
                .map_err(|e| PalaceError::Backend(format!("delete failed: {e}")))?;
            Ok(true)
        })
    }

    fn get(&self, id: &str) -> Result<Option<DrawerRecord>> {
        let id_escaped = escape_sql_literal(id)?;
        let filter = format!("id = '{id_escaped}'");
        let batches: Vec<RecordBatch> = self.runtime.block_on(async {
            let stream = self
                .table
                .query()
                .only_if(filter)
                .limit(1)
                .execute()
                .await
                .map_err(|e| PalaceError::Backend(format!("get query failed: {e}")))?;
            stream
                .try_collect()
                .await
                .map_err(|e| PalaceError::Backend(format!("get collect failed: {e}")))
        })?;

        for batch in &batches {
            if batch.num_rows() > 0 {
                return Ok(Some(row_to_record(batch, 0)?));
            }
        }
        Ok(None)
    }

    fn list(&self, limit: usize, offset: usize) -> Result<Vec<DrawerRecord>> {
        let want = limit.saturating_add(offset);
        if want == 0 {
            return Ok(Vec::new());
        }

        // Collect records with their insert_seq, sort, then slice.
        let batches: Vec<RecordBatch> = self.runtime.block_on(async {
            let stream = self
                .table
                .query()
                .limit(want.max(1))
                // No `order_by` public API; we sort client-side below.
                .execute()
                .await
                .map_err(|e| PalaceError::Backend(format!("list query failed: {e}")))?;
            stream
                .try_collect()
                .await
                .map_err(|e| PalaceError::Backend(format!("list collect failed: {e}")))
        })?;

        // If the first query was truncated by `want`, re-scan with no limit.
        // (Cheap safety net for correctness — lancedb does not guarantee order.)
        let all_batches =
            if total_rows(&batches) < want {
                batches
            } else {
                self.runtime.block_on(async {
                    let stream =
                        self.table.query().execute().await.map_err(|e| {
                            PalaceError::Backend(format!("list rescan failed: {e}"))
                        })?;
                    let out: Vec<RecordBatch> = stream.try_collect().await.map_err(|e| {
                        PalaceError::Backend(format!("list rescan collect failed: {e}"))
                    })?;
                    Ok::<_, PalaceError>(out)
                })?
            };

        let mut with_seq: Vec<(i64, DrawerRecord)> = Vec::new();
        for batch in &all_batches {
            for row in 0..batch.num_rows() {
                let seq = read_i64(batch, "insert_seq", row)?.unwrap_or(i64::MAX);
                with_seq.push((seq, row_to_record(batch, row)?));
            }
        }
        with_seq.sort_by_key(|(s, _)| *s);

        Ok(with_seq
            .into_iter()
            .skip(offset)
            .take(limit)
            .map(|(_, r)| r)
            .collect())
    }

    fn list_filtered(&self, filter: &SearchFilter, limit: usize) -> Result<Vec<DrawerRecord>> {
        let where_clause = build_where_clause(filter)?;
        let batches: Vec<RecordBatch> = self.runtime.block_on(async {
            let mut q = self.table.query();
            if let Some(w) = where_clause {
                q = q.only_if(w);
            }
            let stream = q
                .execute()
                .await
                .map_err(|e| PalaceError::Backend(format!("list_filtered failed: {e}")))?;
            stream
                .try_collect()
                .await
                .map_err(|e| PalaceError::Backend(format!("list_filtered collect failed: {e}")))
        })?;

        let mut with_seq: Vec<(i64, DrawerRecord)> = Vec::new();
        for batch in &batches {
            for row in 0..batch.num_rows() {
                let seq = read_i64(batch, "insert_seq", row)?.unwrap_or(i64::MAX);
                with_seq.push((seq, row_to_record(batch, row)?));
            }
        }
        with_seq.sort_by_key(|(s, _)| *s);
        Ok(with_seq.into_iter().take(limit).map(|(_, r)| r).collect())
    }

    fn search(
        &self,
        query: &str,
        filter: &SearchFilter,
        n_results: usize,
    ) -> Result<Vec<SearchResult>> {
        if query.trim().is_empty() || n_results == 0 {
            return Ok(Vec::new());
        }

        let vector = self.embed_one(query)?;
        let where_clause = build_where_clause(filter)?;

        let batches: Vec<RecordBatch> = self.runtime.block_on(async {
            let mut q = self
                .table
                .query()
                .nearest_to(vector)
                .map_err(|e| PalaceError::Backend(format!("nearest_to failed: {e}")))?
                .distance_type(DistanceType::Cosine)
                .limit(n_results);
            if let Some(w) = where_clause {
                q = q.only_if(w);
            }
            let stream = q
                .execute()
                .await
                .map_err(|e| PalaceError::Backend(format!("search execute failed: {e}")))?;
            stream
                .try_collect()
                .await
                .map_err(|e| PalaceError::Backend(format!("search collect failed: {e}")))
        })?;

        let mut out: Vec<SearchResult> = Vec::new();
        for batch in &batches {
            for row in 0..batch.num_rows() {
                let rec = row_to_record(batch, row)?;
                let similarity = row_similarity(batch, row)?;
                out.push(SearchResult {
                    id: rec.id,
                    content: rec.content,
                    metadata: rec.metadata,
                    similarity,
                });
            }
        }
        out.truncate(n_results);
        Ok(out)
    }
}

fn total_rows(batches: &[RecordBatch]) -> usize {
    batches.iter().map(RecordBatch::num_rows).sum()
}

// Hint: connection is held to keep the database handle alive; we don't
// currently call it after construction but dropping it would close the
// underlying object store.
impl LanceDbPalace {
    #[allow(dead_code)]
    fn _keep_alive(&self) -> &Connection {
        &self.connection
    }
}

// ── tests ──────────────────────────────────────────────────────────────

#[cfg(test)]
#[allow(clippy::panic, clippy::unwrap_used)]
mod tests {
    use super::*;

    #[test]
    fn schema_has_expected_fields() {
        let s = build_schema();
        let names: Vec<&str> = s.fields().iter().map(|f| f.name().as_str()).collect();
        assert_eq!(
            names,
            vec![
                "id",
                "content",
                "vector",
                "wing",
                "room",
                "hall",
                "source_file",
                "date",
                "importance",
                "extra_json",
                "insert_seq",
            ]
        );

        // Spot-check types.
        assert_eq!(
            s.field_with_name("id").unwrap().data_type(),
            &DataType::Utf8
        );
        assert!(!s.field_with_name("id").unwrap().is_nullable());
        assert!(s.field_with_name("wing").unwrap().is_nullable());

        match s.field_with_name("vector").unwrap().data_type() {
            DataType::FixedSizeList(inner, sz) => {
                assert_eq!(*sz, EMBEDDING_DIM);
                assert_eq!(inner.data_type(), &DataType::Float32);
            }
            other => panic!("vector field wrong type: {other:?}"),
        }

        assert_eq!(
            s.field_with_name("insert_seq").unwrap().data_type(),
            &DataType::Int64
        );
    }

    #[test]
    fn escape_sql_doubles_quotes() {
        assert_eq!(escape_sql_literal("abc").unwrap(), "abc");
        assert_eq!(escape_sql_literal("o'brien").unwrap(), "o''brien");
        assert_eq!(escape_sql_literal("a'b'c").unwrap(), "a''b''c");
    }

    #[test]
    fn escape_sql_rejects_control_chars() {
        assert!(escape_sql_literal("line1\nline2").is_err());
        assert!(escape_sql_literal("tab\there").is_err());
        assert!(escape_sql_literal("nul\0byte").is_err());
    }

    #[test]
    fn build_where_clause_empty_filter_is_none() {
        let w = build_where_clause(&SearchFilter::default()).unwrap();
        assert!(w.is_none());
    }

    #[test]
    fn build_where_clause_escapes_values() {
        let f = SearchFilter {
            wing: Some("o'reilly".to_string()),
            room: Some("r1".to_string()),
        };
        let w = build_where_clause(&f).unwrap().unwrap();
        assert_eq!(w, "wing = 'o''reilly' AND room = 'r1'");
    }

    // ── Full round-trip tests (require model download) ─────────────────

    fn model_download_allowed() -> bool {
        std::env::var("MEMPALACE_ALLOW_MODEL_DOWNLOAD")
            .map(|v| v == "1")
            .unwrap_or(false)
    }

    #[test]
    #[ignore = "downloads ONNX model; set MEMPALACE_ALLOW_MODEL_DOWNLOAD=1 and remove ignore locally"]
    fn roundtrip_add_get_search_delete() {
        if !model_download_allowed() {
            return;
        }
        let tmp = tempfile::TempDir::new().unwrap();
        let mut palace = LanceDbPalace::new(tmp.path()).unwrap();

        let rec = DrawerRecord {
            id: "d1".to_string(),
            content: "The quick brown fox jumps over the lazy dog".to_string(),
            metadata: DrawerMetadata {
                wing: Some("code".to_string()),
                room: Some("rust".to_string()),
                ..Default::default()
            },
        };
        palace.add(rec.clone()).unwrap();
        assert_eq!(palace.count().unwrap(), 1);

        let got = palace.get("d1").unwrap().unwrap();
        assert_eq!(got.content, rec.content);

        // Duplicate add should fail.
        assert!(matches!(
            palace.add(rec.clone()),
            Err(PalaceError::Duplicate(_))
        ));

        // Search should find the drawer.
        let hits = palace
            .search("fast brown animal", &SearchFilter::default(), 5)
            .unwrap();
        assert!(!hits.is_empty());
        assert_eq!(hits[0].id, "d1");

        // Filter narrows results.
        let hits = palace
            .search(
                "fox",
                &SearchFilter {
                    wing: Some("code".to_string()),
                    room: None,
                },
                5,
            )
            .unwrap();
        assert_eq!(hits.len(), 1);

        let hits = palace
            .search(
                "fox",
                &SearchFilter {
                    wing: Some("nope".to_string()),
                    room: None,
                },
                5,
            )
            .unwrap();
        assert!(hits.is_empty());

        // list_filtered.
        let listed = palace
            .list_filtered(
                &SearchFilter {
                    wing: Some("code".to_string()),
                    room: None,
                },
                10,
            )
            .unwrap();
        assert_eq!(listed.len(), 1);

        // delete.
        assert!(palace.delete("d1").unwrap());
        assert!(!palace.delete("d1").unwrap());
        assert_eq!(palace.count().unwrap(), 0);
    }

    #[test]
    #[ignore = "downloads ONNX model; set MEMPALACE_ALLOW_MODEL_DOWNLOAD=1 and remove ignore locally"]
    fn persistence_across_reopen() {
        if !model_download_allowed() {
            return;
        }
        let tmp = tempfile::TempDir::new().unwrap();
        {
            let mut palace = LanceDbPalace::new(tmp.path()).unwrap();
            palace
                .add(DrawerRecord {
                    id: "a".to_string(),
                    content: "hello world".to_string(),
                    metadata: DrawerMetadata::default(),
                })
                .unwrap();
            palace
                .add(DrawerRecord {
                    id: "b".to_string(),
                    content: "second drawer".to_string(),
                    metadata: DrawerMetadata::default(),
                })
                .unwrap();
        }

        let palace = LanceDbPalace::new(tmp.path()).unwrap();
        assert_eq!(palace.count().unwrap(), 2);
        let listed = palace.list(10, 0).unwrap();
        assert_eq!(listed.len(), 2);
        assert_eq!(listed[0].id, "a");
        assert_eq!(listed[1].id, "b");
    }
}

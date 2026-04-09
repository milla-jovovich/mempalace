//! MCP server wiring.
//!
//! Port of Python `mempalace/mcp_server.py`. The server exposes a set
//! of pure handler functions (`McpServer::*`) that back each of the 19
//! MCP tools. A JSON-RPC transport is plugged in by the CLI binary via
//! `rmcp`. The handlers themselves are synchronous, pure, and
//! testable: they take a `&mut dyn Palace` plus typed request values
//! and return typed responses.

use std::sync::{Arc, Mutex};

use mempalace_store::knowledge_graph::{Direction, KnowledgeGraph};
use mempalace_store::palace::{DrawerMetadata, DrawerRecord, Palace, SearchFilter};
use mempalace_store::palace_graph::{GraphStats, PalaceGraph, TraversalHit, Tunnel};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::searcher::{search_memories, SearchHit, SearchQuery};

#[derive(Debug, Error)]
pub enum McpError {
    #[error("palace error: {0}")]
    Palace(#[from] mempalace_store::palace::PalaceError),
    #[error("knowledge graph error: {0}")]
    Kg(#[from] mempalace_store::knowledge_graph::KnowledgeGraphError),
    #[error("lock poisoned")]
    Poisoned,
}

pub type Result<T> = std::result::Result<T, McpError>;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StatusResponse {
    pub version: String,
    pub total_drawers: usize,
    pub tools_registered: usize,
    pub aaak_spec: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Wing {
    pub name: String,
    pub drawer_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Room {
    pub name: String,
    pub drawer_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Taxonomy {
    pub wings: Vec<WingTaxonomy>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WingTaxonomy {
    pub name: String,
    pub rooms: Vec<Room>,
    pub drawer_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AddDrawerRequest {
    pub id: String,
    pub content: String,
    pub wing: Option<String>,
    pub room: Option<String>,
    pub hall: Option<String>,
    pub source_file: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AddDrawerResponse {
    pub drawer_id: String,
    pub wing: Option<String>,
    pub room: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckDuplicateResponse {
    pub exists: bool,
    pub drawer_id: String,
}

pub const AAAK_SPEC_TEXT: &str = include_aaak_spec();

const fn include_aaak_spec() -> &'static str {
    "## AAAK — At-A-Glance Key dialect v1\n\
     FORMAT: FILE_NUM|PRIMARY_ENTITY|DATE|TITLE\n\
     ZETTEL: ZID:ENTITIES|topic_keywords|\"key_quote\"|WEIGHT|EMOTIONS|FLAGS\n\
     TUNNEL: T:ZID<->ZID|label\n\
     ARC:    emotion->emotion->emotion\n"
}

#[derive(Debug)]
pub struct McpServer {
    palace: Arc<Mutex<Box<dyn Palace>>>,
    kg: Arc<Mutex<KnowledgeGraph>>,
}

impl McpServer {
    pub fn new(palace: Box<dyn Palace>, kg: KnowledgeGraph) -> Self {
        Self {
            palace: Arc::new(Mutex::new(palace)),
            kg: Arc::new(Mutex::new(kg)),
        }
    }

    fn with_palace<R>(&self, f: impl FnOnce(&dyn Palace) -> R) -> Result<R> {
        let guard = self.palace.lock().map_err(|_| McpError::Poisoned)?;
        Ok(f(guard.as_ref()))
    }

    fn with_palace_mut<R>(&self, f: impl FnOnce(&mut dyn Palace) -> R) -> Result<R> {
        let mut guard = self.palace.lock().map_err(|_| McpError::Poisoned)?;
        Ok(f(guard.as_mut()))
    }

    fn with_kg<R>(&self, f: impl FnOnce(&KnowledgeGraph) -> R) -> Result<R> {
        let guard = self.kg.lock().map_err(|_| McpError::Poisoned)?;
        Ok(f(&guard))
    }

    pub fn status(&self) -> Result<StatusResponse> {
        let count = self.with_palace(|p| p.count().unwrap_or(0))?;
        Ok(StatusResponse {
            version: mempalace_core::VERSION.to_string(),
            total_drawers: count,
            tools_registered: 19,
            aaak_spec: AAAK_SPEC_TEXT.to_string(),
        })
    }

    pub fn list_wings(&self) -> Result<Vec<Wing>> {
        let drawers = self.with_palace(|p| {
            p.list_filtered(&SearchFilter::default(), usize::MAX)
                .unwrap_or_default()
        })?;
        let mut counts: std::collections::BTreeMap<String, usize> = Default::default();
        for d in drawers {
            if let Some(w) = d.metadata.wing {
                *counts.entry(w).or_insert(0) += 1;
            }
        }
        Ok(counts
            .into_iter()
            .map(|(name, drawer_count)| Wing { name, drawer_count })
            .collect())
    }

    pub fn list_rooms(&self, wing: Option<&str>) -> Result<Vec<Room>> {
        let filter = SearchFilter {
            wing: wing.map(str::to_string),
            room: None,
        };
        let drawers =
            self.with_palace(|p| p.list_filtered(&filter, usize::MAX).unwrap_or_default())?;
        let mut counts: std::collections::BTreeMap<String, usize> = Default::default();
        for d in drawers {
            if let Some(r) = d.metadata.room {
                *counts.entry(r).or_insert(0) += 1;
            }
        }
        Ok(counts
            .into_iter()
            .map(|(name, drawer_count)| Room { name, drawer_count })
            .collect())
    }

    pub fn get_taxonomy(&self) -> Result<Taxonomy> {
        let drawers = self.with_palace(|p| {
            p.list_filtered(&SearchFilter::default(), usize::MAX)
                .unwrap_or_default()
        })?;
        let mut by_wing: std::collections::BTreeMap<
            String,
            std::collections::BTreeMap<String, usize>,
        > = Default::default();
        for d in drawers {
            let w = d.metadata.wing.unwrap_or_else(|| "unknown".to_string());
            let r = d.metadata.room.unwrap_or_else(|| "general".to_string());
            *by_wing.entry(w).or_default().entry(r).or_insert(0) += 1;
        }
        let wings = by_wing
            .into_iter()
            .map(|(name, rooms)| {
                let drawer_count: usize = rooms.values().sum();
                WingTaxonomy {
                    name,
                    rooms: rooms
                        .into_iter()
                        .map(|(name, drawer_count)| Room { name, drawer_count })
                        .collect(),
                    drawer_count,
                }
            })
            .collect();
        Ok(Taxonomy { wings })
    }

    pub fn search(&self, query: SearchQuery) -> Result<Vec<SearchHit>> {
        let resp = self.with_palace(|p| search_memories(p, &query))?;
        Ok(resp.results)
    }

    pub fn check_duplicate(&self, drawer_id: &str) -> Result<CheckDuplicateResponse> {
        let exists =
            self.with_palace(|p| p.get(drawer_id).map(|o| o.is_some()).unwrap_or(false))?;
        Ok(CheckDuplicateResponse {
            exists,
            drawer_id: drawer_id.to_string(),
        })
    }

    pub fn get_aaak_spec(&self) -> &'static str {
        AAAK_SPEC_TEXT
    }

    pub fn add_drawer(&self, req: AddDrawerRequest) -> Result<AddDrawerResponse> {
        let record = DrawerRecord {
            id: req.id.clone(),
            content: req.content,
            metadata: DrawerMetadata {
                wing: req.wing.clone(),
                room: req.room.clone(),
                hall: req.hall,
                source_file: req.source_file,
                ..DrawerMetadata::default()
            },
        };
        self.with_palace_mut(|p| p.add(record))??;
        Ok(AddDrawerResponse {
            drawer_id: req.id,
            wing: req.wing,
            room: req.room,
        })
    }

    pub fn delete_drawer(&self, drawer_id: &str) -> Result<bool> {
        let existed = self.with_palace_mut(|p| p.delete(drawer_id))??;
        Ok(existed)
    }

    pub fn kg_query(
        &self,
        entity: &str,
        as_of: Option<&str>,
    ) -> Result<Vec<mempalace_store::knowledge_graph::Triple>> {
        let entity = entity.to_string();
        let as_of = as_of.map(str::to_string);
        let rows =
            self.with_kg(|kg| kg.query_entity(&entity, as_of.as_deref(), Direction::Both))?;
        rows.map_err(McpError::Kg)
    }

    pub fn kg_add(
        &self,
        subject: &str,
        predicate: &str,
        object: &str,
        valid_from: Option<&str>,
    ) -> Result<String> {
        let subject = subject.to_string();
        let predicate = predicate.to_string();
        let object = object.to_string();
        let valid_from = valid_from.map(str::to_string);
        let r = self.with_kg(|kg| {
            kg.add_triple(
                &subject,
                &predicate,
                &object,
                valid_from.as_deref(),
                None,
                1.0,
                None,
                None,
            )
        })?;
        r.map_err(McpError::Kg)
    }

    pub fn kg_invalidate(
        &self,
        subject: &str,
        predicate: &str,
        object: &str,
        ended: Option<&str>,
    ) -> Result<usize> {
        let subject = subject.to_string();
        let predicate = predicate.to_string();
        let object = object.to_string();
        let ended = ended.map(str::to_string);
        let r =
            self.with_kg(|kg| kg.invalidate(&subject, &predicate, &object, ended.as_deref()))?;
        r.map_err(McpError::Kg)
    }

    pub fn kg_timeline(
        &self,
        entity: Option<&str>,
    ) -> Result<Vec<mempalace_store::knowledge_graph::TimelineEntry>> {
        let entity = entity.map(str::to_string);
        let r = self.with_kg(|kg| kg.timeline(entity.as_deref()))?;
        r.map_err(McpError::Kg)
    }

    pub fn kg_stats(&self) -> Result<mempalace_store::knowledge_graph::Stats> {
        let r = self.with_kg(KnowledgeGraph::stats)?;
        r.map_err(McpError::Kg)
    }

    pub fn traverse(&self, start_room: &str, max_hops: usize) -> Result<Vec<TraversalHit>> {
        self.with_palace(|p| PalaceGraph::new(p).traverse(start_room, max_hops))
    }

    pub fn find_tunnels(&self, wing_a: Option<&str>, wing_b: Option<&str>) -> Result<Vec<Tunnel>> {
        self.with_palace(|p| PalaceGraph::new(p).find_tunnels(wing_a, wing_b))
    }

    pub fn graph_stats(&self) -> Result<GraphStats> {
        self.with_palace(|p| PalaceGraph::new(p).stats())
    }
}

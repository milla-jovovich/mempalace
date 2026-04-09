#![forbid(unsafe_code)]
#![allow(clippy::pedantic)]
#![allow(clippy::unwrap_used)]
#![allow(clippy::expect_used)]
#![doc = "Storage layer: knowledge graph, palace graph, layers, and vector store."]

pub mod knowledge_graph;
pub mod layers;
pub mod palace;
pub mod palace_graph;

#[cfg(feature = "lancedb-backend")]
pub mod lancedb_backend;

pub use knowledge_graph::{KnowledgeGraph, KnowledgeGraphError, Triple};
#[cfg(feature = "lancedb-backend")]
pub use lancedb_backend::LanceDbPalace;
pub use layers::{Layer0, Layer1, Layer2, Layer3, MemoryStack};
pub use mempalace_core::VERSION;
pub use palace::{DrawerMetadata, DrawerRecord, Palace, PalaceError, SearchResult};
pub use palace_graph::{GraphEdge, GraphNode, PalaceGraph};

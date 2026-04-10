#![forbid(unsafe_code)]
#![allow(clippy::pedantic)]
#![allow(clippy::unwrap_used)]
#![allow(clippy::expect_used)]
#![doc = "Server layer: searcher, ingest (miner), hooks, onboarding, and MCP server."]

pub mod convo_miner;
pub mod hooks;
pub mod ingest;
pub mod mcp;
pub mod mcp_transport;
pub mod onboarding;
pub mod searcher;

pub use convo_miner::{ConvoMineStats, ConvoMiner, ExtractMode};
pub use hooks::{HookError, SaveHook};
pub use ingest::{IngestError, IngestStats, Miner};
pub use mcp::McpServer;
pub use mcp_transport::serve_stdio;
pub use mempalace_core::VERSION;
pub use onboarding::{OnboardingError, WingConfig};
pub use searcher::{search_memories, SearchHit, SearchQuery};

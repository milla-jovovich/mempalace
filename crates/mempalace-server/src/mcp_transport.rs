//! MCP stdio transport using rmcp 0.16.
//!
//! Exposes every `McpServer` tool over a JSON-RPC stdio transport so that
//! Claude, Cursor, or any MCP-compatible client can call them.

use std::sync::Arc;

use rmcp::handler::server::router::tool::CallToolHandlerExt;
use rmcp::handler::server::router::Router;
use rmcp::handler::server::wrapper::Parameters;
use rmcp::handler::server::ServerHandler;
use rmcp::model::{Implementation, ServerCapabilities, ServerInfo, ToolsCapability};
use rmcp::transport::io::stdio;
use rmcp::ServiceExt;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::mcp::{AddDrawerRequest, McpServer};

// ---------------------------------------------------------------------------
// Parameter structs (schemars-derived JSON schemas)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct SearchParams {
    query: String,
    wing: Option<String>,
    room: Option<String>,
    n_results: Option<usize>,
}

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct ListRoomsParams {
    wing: Option<String>,
}

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct DrawerIdParams {
    drawer_id: String,
}

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct AddDrawerParams {
    id: String,
    content: String,
    wing: Option<String>,
    room: Option<String>,
    hall: Option<String>,
    source_file: Option<String>,
}

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct KgQueryParams {
    entity: String,
    as_of: Option<String>,
}

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct KgAddParams {
    subject: String,
    predicate: String,
    object: String,
    valid_from: Option<String>,
}

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct KgInvalidateParams {
    subject: String,
    predicate: String,
    object: String,
    ended: Option<String>,
}

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct KgTimelineParams {
    entity: Option<String>,
}

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct TraverseParams {
    start_room: String,
    max_hops: usize,
}

#[derive(Debug, Clone, Deserialize, JsonSchema)]
struct FindTunnelsParams {
    wing_a: Option<String>,
    wing_b: Option<String>,
}

// ---------------------------------------------------------------------------
// Handler struct
// ---------------------------------------------------------------------------

/// Thin wrapper that implements `ServerHandler` so the `Router` can delegate
/// `initialize` / `ping` / etc. to default impls while the `ToolRouter`
/// dispatches tool calls.
struct MempalaceMcp {
    #[allow(dead_code)]
    inner: Arc<McpServer>,
}

impl ServerHandler for MempalaceMcp {
    fn get_info(&self) -> ServerInfo {
        ServerInfo {
            protocol_version: Default::default(),
            capabilities: ServerCapabilities {
                tools: Some(ToolsCapability { list_changed: None }),
                ..Default::default()
            },
            server_info: Implementation {
                name: "mempalace".to_string(),
                title: None,
                version: mempalace_core::VERSION.to_string(),
                description: Some("MemPalace MCP server".to_string()),
                icons: None,
                website_url: None,
            },
            instructions: Some("MemPalace: AI memory palace with AAAK dialect".to_string()),
        }
    }
}

// ---------------------------------------------------------------------------
// Helper: serialize Ok(value) -> Result<String,String>, map McpError -> Err
// ---------------------------------------------------------------------------

fn to_json(value: &impl Serialize) -> Result<String, String> {
    serde_json::to_string_pretty(value).map_err(|e| e.to_string())
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/// Run the MCP server over stdin/stdout using rmcp's stdio transport.
pub async fn serve_stdio(server: McpServer) -> anyhow::Result<()> {
    let inner = Arc::new(server);
    let handler = MempalaceMcp {
        inner: Arc::clone(&inner),
    };

    let router = Router::new(handler)
        // mempalace_status
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp| {
                s.status()
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_status")
            .description("Show palace status: version, drawer count, tools registered, AAAK spec")
            .parameters::<serde_json::Value>()
        })
        // mempalace_search
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp, Parameters(p): Parameters<SearchParams>| {
                let q = crate::searcher::SearchQuery {
                    query: p.query,
                    wing: p.wing,
                    room: p.room,
                    n_results: p.n_results.unwrap_or(5),
                };
                s.search(q)
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_search")
            .description("Search the palace for memories matching a query")
            .parameters::<SearchParams>()
        })
        // mempalace_list_wings
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp| {
                s.list_wings()
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_list_wings")
            .description("List all wings and their drawer counts")
            .parameters::<serde_json::Value>()
        })
        // mempalace_list_rooms
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp, Parameters(p): Parameters<ListRoomsParams>| {
                s.list_rooms(p.wing.as_deref())
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_list_rooms")
            .description("List rooms, optionally filtered by wing")
            .parameters::<ListRoomsParams>()
        })
        // mempalace_get_taxonomy
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp| {
                s.get_taxonomy()
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_get_taxonomy")
            .description("Get full taxonomy: wings, rooms, and drawer counts")
            .parameters::<serde_json::Value>()
        })
        // mempalace_check_duplicate
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp, Parameters(p): Parameters<DrawerIdParams>| {
                s.check_duplicate(&p.drawer_id)
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_check_duplicate")
            .description("Check if a drawer with the given ID already exists")
            .parameters::<DrawerIdParams>()
        })
        // mempalace_get_aaak_spec
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp| -> Result<String, String> {
                Ok(s.get_aaak_spec().to_string())
            })
            .name("mempalace_get_aaak_spec")
            .description("Return the AAAK (At-A-Glance Key) dialect specification")
            .parameters::<serde_json::Value>()
        })
        // mempalace_add_drawer
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp, Parameters(p): Parameters<AddDrawerParams>| {
                let req = AddDrawerRequest {
                    id: p.id,
                    content: p.content,
                    wing: p.wing,
                    room: p.room,
                    hall: p.hall,
                    source_file: p.source_file,
                };
                s.add_drawer(req)
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_add_drawer")
            .description("Add a new drawer to the palace")
            .parameters::<AddDrawerParams>()
        })
        // mempalace_delete_drawer
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp, Parameters(p): Parameters<DrawerIdParams>| {
                s.delete_drawer(&p.drawer_id)
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_delete_drawer")
            .description("Delete a drawer by its ID")
            .parameters::<DrawerIdParams>()
        })
        // mempalace_kg_query
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp, Parameters(p): Parameters<KgQueryParams>| {
                s.kg_query(&p.entity, p.as_of.as_deref())
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_kg_query")
            .description("Query knowledge graph triples for an entity")
            .parameters::<KgQueryParams>()
        })
        // mempalace_kg_add
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp, Parameters(p): Parameters<KgAddParams>| {
                s.kg_add(&p.subject, &p.predicate, &p.object, p.valid_from.as_deref())
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_kg_add")
            .description("Add a triple to the knowledge graph")
            .parameters::<KgAddParams>()
        })
        // mempalace_kg_invalidate
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp, Parameters(p): Parameters<KgInvalidateParams>| {
                s.kg_invalidate(&p.subject, &p.predicate, &p.object, p.ended.as_deref())
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_kg_invalidate")
            .description("Invalidate (soft-delete) a knowledge graph triple")
            .parameters::<KgInvalidateParams>()
        })
        // mempalace_kg_timeline
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp, Parameters(p): Parameters<KgTimelineParams>| {
                s.kg_timeline(p.entity.as_deref())
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_kg_timeline")
            .description("Get knowledge graph timeline, optionally for a specific entity")
            .parameters::<KgTimelineParams>()
        })
        // mempalace_kg_stats
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp| {
                s.kg_stats()
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_kg_stats")
            .description("Get knowledge graph statistics")
            .parameters::<serde_json::Value>()
        })
        // mempalace_traverse
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp, Parameters(p): Parameters<TraverseParams>| {
                s.traverse(&p.start_room, p.max_hops)
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_traverse")
            .description("Traverse the palace graph from a starting room")
            .parameters::<TraverseParams>()
        })
        // mempalace_find_tunnels
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp, Parameters(p): Parameters<FindTunnelsParams>| {
                s.find_tunnels(p.wing_a.as_deref(), p.wing_b.as_deref())
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_find_tunnels")
            .description("Find tunnels (cross-wing connections) between wings")
            .parameters::<FindTunnelsParams>()
        })
        // mempalace_graph_stats
        .with_tool({
            let s = Arc::clone(&inner);
            (move |_: &MempalaceMcp| {
                s.graph_stats()
                    .map_err(|e| e.to_string())
                    .and_then(|v| to_json(&v))
            })
            .name("mempalace_graph_stats")
            .description("Get palace graph statistics (nodes, edges, etc.)")
            .parameters::<serde_json::Value>()
        });

    let running = router
        .serve(stdio())
        .await
        .map_err(|e| anyhow::anyhow!("MCP server initialization failed: {e}"))?;
    running
        .waiting()
        .await
        .map_err(|e| anyhow::anyhow!("MCP server error: {e}"))?;

    Ok(())
}

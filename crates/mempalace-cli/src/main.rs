#![forbid(unsafe_code)]
#![allow(clippy::pedantic)]
#![allow(clippy::unwrap_used)]
#![allow(clippy::expect_used)]

use std::path::PathBuf;

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use mempalace_server::hooks::{SaveHook, SaveRequest};
use mempalace_server::ingest::{Miner, MinerOptions};
use mempalace_server::onboarding::WingConfig;
use mempalace_server::searcher::{format_human, search_memories, SearchQuery};
use mempalace_store::layers::MemoryStack;
use mempalace_store::palace::{InMemoryPalace, Palace};
use tracing_subscriber::EnvFilter;

#[derive(Debug, Parser)]
#[command(
    name = "mempalace",
    version = mempalace_core::VERSION,
    about = "Give your AI a memory — mine projects and conversations into a searchable palace.",
)]
struct Cli {
    #[arg(long, global = true)]
    palace: Option<PathBuf>,

    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    #[command(about = "Show palace status and drawer counts")]
    Status,

    #[command(about = "Search the palace")]
    Search {
        query: Vec<String>,
        #[arg(long)]
        wing: Option<String>,
        #[arg(long)]
        room: Option<String>,
        #[arg(long, default_value_t = 5)]
        n: usize,
    },

    #[command(about = "Guided first-run onboarding: write wing_config.json")]
    Init {
        #[arg(long)]
        person: Vec<String>,
        #[arg(long)]
        project: Vec<String>,
    },

    #[command(about = "Mine a directory of project files into the palace")]
    Mine {
        dir: PathBuf,
        #[arg(long)]
        wing: Option<String>,
        #[arg(long, default_value = "general")]
        room: String,
    },

    #[command(about = "Wake-up text: L0 identity + L1 essential story")]
    WakeUp {
        #[arg(long)]
        wing: Option<String>,
    },

    #[command(about = "Split concatenated transcript mega-files")]
    Split {
        dir: PathBuf,
        #[arg(long)]
        dry_run: bool,
    },

    #[command(about = "Print MCP setup command for Claude / ChatGPT / Cursor")]
    Mcp,

    #[command(about = "Hook save trigger (for editor / shell integrations)")]
    HookSave {
        #[arg(long)]
        wing: Option<String>,
        #[arg(long)]
        room: Option<String>,
        #[arg(long)]
        source: Option<String>,
        content: String,
    },

    #[command(about = "Print version and build info")]
    Instructions,
}

fn main() -> Result<()> {
    let filter = EnvFilter::try_from_default_env()
        .or_else(|_| EnvFilter::try_new("warn"))
        .context("failed to build tracing env filter")?;
    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .try_init()
        .map_err(|e| anyhow::anyhow!("failed to initialise tracing subscriber: {e}"))?;

    let cli = Cli::parse();

    let mut palace: Box<dyn Palace> = Box::new(InMemoryPalace::new());

    match cli.command {
        Command::Status => cmd_status(palace.as_ref()),
        Command::Search {
            query,
            wing,
            room,
            n,
        } => cmd_search(palace.as_ref(), &query.join(" "), wing, room, n),
        Command::Init { person, project } => cmd_init(&person, &project),
        Command::Mine { dir, wing, room } => cmd_mine(palace.as_mut(), &dir, wing, room),
        Command::WakeUp { wing } => cmd_wake_up(palace.as_ref(), wing.as_deref()),
        Command::Split { dir, dry_run } => cmd_split(&dir, dry_run),
        Command::Mcp => cmd_mcp(),
        Command::HookSave {
            wing,
            room,
            source,
            content,
        } => cmd_hook_save(palace.as_mut(), wing, room, source, content),
        Command::Instructions => cmd_instructions(),
    }
}

fn cmd_status(palace: &dyn Palace) -> Result<()> {
    let drawers = palace.count().unwrap_or(0);
    println!("mempalace {}", mempalace_core::VERSION);
    println!("drawers: {drawers}");
    println!("tools:   19");
    Ok(())
}

fn cmd_search(
    palace: &dyn Palace,
    query: &str,
    wing: Option<String>,
    room: Option<String>,
    n: usize,
) -> Result<()> {
    let q = SearchQuery {
        query: query.to_string(),
        wing,
        room,
        n_results: n,
    };
    let resp = search_memories(palace, &q);
    print!("{}", format_human(&resp));
    Ok(())
}

fn cmd_init(persons: &[String], projects: &[String]) -> Result<()> {
    let mut cfg = WingConfig::new_empty();
    for p in persons {
        let wing = cfg.add_person(p)?;
        println!("added person: {p} -> {wing}");
    }
    for p in projects {
        let wing = cfg.add_project(p, &[])?;
        println!("added project: {p} -> {wing}");
    }
    let path = WingConfig::default_path();
    cfg.save(&path)
        .with_context(|| format!("failed to write wing config to {}", path.display()))?;
    println!("wing_config written to {}", path.display());
    Ok(())
}

fn cmd_mine(
    palace: &mut dyn Palace,
    dir: &std::path::Path,
    wing: Option<String>,
    room: String,
) -> Result<()> {
    let miner = Miner::new(MinerOptions {
        wing,
        default_room: room,
        ..MinerOptions::default()
    });
    let stats = miner
        .mine(dir, palace)
        .with_context(|| format!("mining {}", dir.display()))?;
    println!("{stats:#?}");
    Ok(())
}

fn cmd_wake_up(palace: &dyn Palace, wing: Option<&str>) -> Result<()> {
    let mut stack = MemoryStack::new(palace, None);
    println!("{}", stack.wake_up(wing));
    Ok(())
}

fn cmd_split(dir: &std::path::Path, dry_run: bool) -> Result<()> {
    use mempalace_text::split_mega_files::{find_session_boundaries, split_file};

    let entries = std::fs::read_dir(dir).with_context(|| format!("reading {}", dir.display()))?;
    let mut total = 0usize;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("txt") {
            continue;
        }
        let content = std::fs::read_to_string(&path).unwrap_or_default();
        let lines: Vec<String> = content.lines().map(|l| format!("{l}\n")).collect();
        let boundaries = find_session_boundaries(&lines);
        if boundaries.len() < 2 {
            continue;
        }
        println!("  {}  ({} sessions)", path.display(), boundaries.len());
        let written = split_file(&path, None, dry_run)
            .with_context(|| format!("splitting {}", path.display()))?;
        total += written.len();
    }
    if dry_run {
        println!("DRY RUN — would create {total} files");
    } else {
        println!("created {total} files");
    }
    Ok(())
}

fn cmd_mcp() -> Result<()> {
    println!("# Claude Code / ChatGPT / Cursor / Gemini MCP setup\n");
    println!("claude mcp add mempalace -- mempalace mcp-serve");
    println!();
    println!("The Rust binary speaks MCP over stdio via rmcp.");
    Ok(())
}

fn cmd_hook_save(
    palace: &mut dyn Palace,
    wing: Option<String>,
    room: Option<String>,
    source: Option<String>,
    content: String,
) -> Result<()> {
    let result = SaveHook::default()
        .save(
            palace,
            SaveRequest {
                wing,
                room,
                source,
                content,
            },
        )
        .context("save hook failed")?;
    println!("{result:#?}");
    Ok(())
}

fn cmd_instructions() -> Result<()> {
    println!("mempalace {}", mempalace_core::VERSION);
    println!("Rust port of MemPalace. Run `mempalace --help` for commands.");
    Ok(())
}

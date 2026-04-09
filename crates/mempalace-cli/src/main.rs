#![forbid(unsafe_code)]

use anyhow::{Context, Result};
use tracing_subscriber::EnvFilter;

fn main() -> Result<()> {
    let filter = EnvFilter::try_from_default_env()
        .or_else(|_| EnvFilter::try_new("warn"))
        .context("failed to build tracing env filter")?;

    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .try_init()
        .map_err(|e| anyhow::anyhow!("failed to initialise tracing subscriber: {e}"))?;

    tracing::info!(
        version = mempalace_core::VERSION,
        "mempalace cli (Rust port, Phase 1/7)"
    );

    println!(
        "mempalace {} — Rust port in progress (Phase 1/7). Use the Python cli until Phase 6 lands.",
        mempalace_core::VERSION
    );
    Ok(())
}

# Delphi Miner — MemPalace Plugin

A miner plugin that ingests signals from the [Delphi Oracle](https://delphi-oracle.onrender.com) into [MemPalace](https://github.com/milla-jovovich/mempalace).

Signals are filed into MemPalace's wing/room/drawer structure:

- **Wing:** `delphi`
- **Rooms:** auto-created per signal type (e.g., `market_anomaly`, `security_alert`)
- **Drawers:** one per signal, stored verbatim with full metadata

## Install

```bash
pip install chromadb requests
```

MemPalace must already be initialised (`mempalace init` + at least one `mempalace mine`).

## Usage

```bash
# Dry run — see what would be filed
python delphi_miner.py --dry-run

# Free endpoints only (no payment needed)
python delphi_miner.py --free-only

# Full ingest with x402 payment
export DELPHI_X402_PAYMENT="your-x402-header-value"
python delphi_miner.py

# Custom palace path
python delphi_miner.py --palace /path/to/palace --limit 100
```

## How It Works

1. Calls free `GET /v1/signals/count` and `GET /v1/signals/types` to probe available data
2. Calls paid `GET /v1/signals/query` ($0.002 via x402) to fetch actual signals
3. Maps each signal to a MemPalace room based on signal type
4. Stores verbatim signal content as drawers in ChromaDB (upsert, idempotent)
5. Preserves all signal metadata (severity, confidence, source, timestamp, expires) in ChromaDB metadata fields

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--palace` | `~/.mempalace/palace` | Palace directory path |
| `--base-url` | `https://delphi-oracle.onrender.com` | Delphi API base URL |
| `--dry-run` | off | Preview without writing |
| `--free-only` | off | Skip paid endpoints |
| `--limit` | 50 | Max signals per query |
| `--x402-payment` | env `DELPHI_X402_PAYMENT` | x402 payment header |

## Searching Ingested Signals

After mining, use standard MemPalace search:

```bash
mempalace search "security alert" --wing delphi
mempalace search "high severity" --wing delphi --room security_alert
```

Or via MCP (Claude Code / Cursor):

> "What Delphi signals came in about market anomalies?"

## Signal Structure

Each signal from Delphi has this shape:

```json
{
  "signal_id": "...",
  "type": "market_anomaly",
  "severity": "high",
  "title": "Unusual volume detected",
  "data": { ... },
  "confidence": 0.92,
  "source": "delphi-core",
  "signature": "...",
  "timestamp": "2026-04-10T08:00:00Z",
  "expires": "2026-04-11T08:00:00Z"
}
```

The miner stores the full signal verbatim (no summarisation), following MemPalace's core design principle.

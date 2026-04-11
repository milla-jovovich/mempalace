#!/usr/bin/env python3
"""
delphi_miner.py — Mine Delphi Oracle signals into MemPalace.

Fetches signals from the Delphi Oracle API and files them into
the palace using MemPalace's wing/room/drawer structure.

Wing:  "delphi"
Rooms: one per signal type (e.g., "market_anomaly", "security_alert", etc.)
       with a fallback "general" room for unknown types.

Free endpoints (no payment):
  GET /v1/signals/count   — signal counts by type
  GET /v1/signals/types   — available signal types

Paid endpoints (x402 micropayment):
  GET /v1/signals/query   — full signal query ($0.002)
  GET /v1/signals/latest  — latest signals ($0.001)

Usage:
    python delphi_miner.py --palace ~/.mempalace/palace
    python delphi_miner.py --palace ~/.mempalace/palace --dry-run
    python delphi_miner.py --palace ~/.mempalace/palace --free-only
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import chromadb
import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DELPHI_BASE_URL = "https://delphi-oracle.onrender.com"

WING = "delphi"
AGENT = "delphi_miner"

CHUNK_MIN_SIZE = 30  # minimum content length to store


# ---------------------------------------------------------------------------
# Delphi API Client
# ---------------------------------------------------------------------------


class DelphiClient:
    """Minimal client for the Delphi Oracle public API."""

    def __init__(self, base_url: str = DELPHI_BASE_URL, x402_payment_header: str = None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        if x402_payment_header:
            self.session.headers["X-Payment"] = x402_payment_header

    # -- Free endpoints ----------------------------------------------------

    def get_signal_count(self) -> dict:
        """GET /v1/signals/count — signal counts by type (free)."""
        resp = self.session.get(f"{self.base_url}/v1/signals/count", timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_signal_types(self) -> list:
        """GET /v1/signals/types — available signal type names (free)."""
        resp = self.session.get(f"{self.base_url}/v1/signals/types", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("types", data.get("signal_types", []))

    # -- Paid endpoints (x402) ---------------------------------------------

    def query_signals(self, params: dict = None) -> list:
        """GET /v1/signals/query — full signal query ($0.002 via x402).

        The caller must have configured x402 payment headers on this
        client for the request to succeed.  Without payment the
        endpoint will return 402 Payment Required.
        """
        resp = self.session.get(
            f"{self.base_url}/v1/signals/query",
            params=params or {},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("signals", data.get("results", []))

    def get_latest_signals(self, limit: int = 25) -> list:
        """GET /v1/signals/latest — latest signals ($0.001 via x402)."""
        resp = self.session.get(
            f"{self.base_url}/v1/signals/latest",
            params={"limit": limit},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("signals", data.get("results", []))


# ---------------------------------------------------------------------------
# Palace helpers  (mirrors mempalace.palace / mempalace.miner patterns)
# ---------------------------------------------------------------------------


def load_palace_config() -> dict:
    """Read ~/.mempalace/config.json if it exists."""
    config_path = Path.home() / ".mempalace" / "config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except Exception:
            pass
    return {}


def get_collection(palace_path: str, collection_name: str = None):
    """Get or create the ChromaDB collection (same as mempalace.palace).

    If collection_name is None, reads from ~/.mempalace/config.json
    (key: "collection_name"), falling back to "mempalace_drawers".
    """
    if collection_name is None:
        config = load_palace_config()
        collection_name = config.get("collection_name", "mempalace_drawers")
    os.makedirs(palace_path, exist_ok=True)
    client = chromadb.PersistentClient(path=palace_path)
    try:
        return client.get_collection(collection_name)
    except Exception:
        return client.create_collection(collection_name)


def drawer_id_for_signal(signal: dict) -> str:
    """Deterministic drawer ID from signal_id so upserts are idempotent."""
    sig_id = signal.get("signal_id", "")
    if not sig_id:
        sig_id = hashlib.sha256(json.dumps(signal, sort_keys=True).encode()).hexdigest()[:32]
    return f"drawer_{WING}_{sig_id}"


def signal_already_stored(collection, signal: dict) -> bool:
    """Check if this signal's drawer already exists."""
    did = drawer_id_for_signal(signal)
    try:
        results = collection.get(ids=[did])
        return bool(results.get("ids"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Signal -> Drawer mapping
# ---------------------------------------------------------------------------


def signal_to_room(signal: dict) -> str:
    """Map a signal to a MemPalace room name based on its type.

    Room names are sanitised to the same character set MemPalace uses.
    """
    raw_type = signal.get("type", "general") or "general"
    # Normalise: lowercase, replace spaces/hyphens with underscores
    room = raw_type.strip().lower().replace(" ", "_").replace("-", "_")
    # Keep only safe characters
    room = "".join(c for c in room if c.isalnum() or c == "_")
    return room or "general"


def signal_to_document(signal: dict) -> str:
    """Render a signal as a human-readable document string for ChromaDB.

    This is the verbatim content stored in the drawer — following
    MemPalace's principle of storing raw content, not summaries.
    """
    parts = []

    title = signal.get("title", "")
    if title:
        parts.append(f"# {title}")
        parts.append("")

    parts.append(f"Type: {signal.get('type', 'unknown')}")
    parts.append(f"Severity: {signal.get('severity', 'unknown')}")
    parts.append(f"Confidence: {signal.get('confidence', 'unknown')}")
    parts.append(f"Source: {signal.get('source', 'unknown')}")
    parts.append(f"Timestamp: {signal.get('timestamp', 'unknown')}")

    expires = signal.get("expires")
    if expires:
        parts.append(f"Expires: {expires}")

    parts.append("")

    # Data payload — store verbatim
    data = signal.get("data")
    if data:
        if isinstance(data, dict):
            parts.append("## Data")
            parts.append(json.dumps(data, indent=2))
        elif isinstance(data, str):
            parts.append("## Data")
            parts.append(data)

    return "\n".join(parts)


def _signal_is_expired(signal: dict) -> bool:
    """Check if a signal's expires field is in the past."""
    expires = signal.get("expires")
    if not expires:
        return False
    try:
        exp_dt = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
        return exp_dt < datetime.now(exp_dt.tzinfo)
    except (ValueError, TypeError):
        return False


def build_metadata(signal: dict, room: str) -> dict:
    """Build ChromaDB metadata dict matching MemPalace conventions."""
    meta = {
        "wing": WING,
        "room": room,
        "source_file": f"delphi://{signal.get('signal_id', 'unknown')}",
        "chunk_index": 0,
        "added_by": AGENT,
        "filed_at": datetime.now().isoformat(),
        "ingest_mode": "delphi",
    }

    # Auto-archive expired signals (see MemPalace #332)
    if _signal_is_expired(signal):
        meta["status"] = "archived"

    # Preserve signal metadata for downstream queries
    for key in ("signal_id", "type", "severity", "confidence", "source", "timestamp", "expires"):
        val = signal.get(key)
        if val is not None:
            meta[f"delphi_{key}"] = str(val)

    return meta


# ---------------------------------------------------------------------------
# Mining logic
# ---------------------------------------------------------------------------


def mine_signals(
    signals: list,
    palace_path: str,
    dry_run: bool = False,
    collection_name: str = None,
) -> dict:
    """File a list of Delphi signals into the palace.

    Returns summary stats dict.
    """
    collection = get_collection(palace_path, collection_name) if not dry_run else None

    stats = {"total": len(signals), "filed": 0, "skipped": 0, "rooms": {}}

    for signal in signals:
        room = signal_to_room(signal)
        doc = signal_to_document(signal)

        if len(doc.strip()) < CHUNK_MIN_SIZE:
            stats["skipped"] += 1
            continue

        if not dry_run and signal_already_stored(collection, signal):
            stats["skipped"] += 1
            continue

        did = drawer_id_for_signal(signal)
        meta = build_metadata(signal, room)

        if dry_run:
            title = signal.get("title", signal.get("signal_id", "?"))
            print(f"    [DRY RUN] {title[:60]:60} -> room:{room}")
        else:
            collection.upsert(
                documents=[doc],
                ids=[did],
                metadatas=[meta],
            )

        stats["filed"] += 1
        stats["rooms"][room] = stats["rooms"].get(room, 0) + 1

    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Delphi Miner — ingest Delphi Oracle signals into MemPalace",
    )
    parser.add_argument(
        "--palace",
        default=os.path.expanduser("~/.mempalace/palace"),
        help="Path to the MemPalace palace directory (default: ~/.mempalace/palace)",
    )
    parser.add_argument(
        "--base-url",
        default=DELPHI_BASE_URL,
        help=f"Delphi Oracle base URL (default: {DELPHI_BASE_URL})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be filed without writing to the palace",
    )
    parser.add_argument(
        "--free-only",
        action="store_true",
        help="Only use free endpoints (count + types) — skip paid signal fetch",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max signals to fetch per query (default: 50)",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="ChromaDB collection name (default: reads from ~/.mempalace/config.json, else 'mempalace_drawers')",
    )
    parser.add_argument(
        "--x402-payment",
        default=None,
        help="x402 payment header value for paid endpoints (env: DELPHI_X402_PAYMENT)",
    )
    args = parser.parse_args()

    palace_path = os.path.expanduser(args.palace)
    x402 = args.x402_payment or os.environ.get("DELPHI_X402_PAYMENT")
    client = DelphiClient(base_url=args.base_url, x402_payment_header=x402)

    print(f"\n{'=' * 60}")
    print("  Delphi Miner — MemPalace Signal Ingest")
    print(f"{'=' * 60}")
    print(f"  Wing:    {WING}")
    print(f"  Palace:  {palace_path}")
    print(f"  Source:  {args.base_url}")
    if args.dry_run:
        print("  DRY RUN — nothing will be filed")
    print(f"{'─' * 60}\n")

    # Step 1: Free probe — get signal counts and types
    print("  [1/3] Fetching signal counts (free)...")
    try:
        counts = client.get_signal_count()
        print(f"         Signal counts: {json.dumps(counts, indent=2)[:200]}")
    except Exception as e:
        print(f"         Warning: could not fetch counts — {e}")
        counts = {}

    print("  [2/3] Fetching signal types (free)...")
    try:
        types = client.get_signal_types()
        print(f"         Types available: {types}")
    except Exception as e:
        print(f"         Warning: could not fetch types — {e}")
        types = []

    # Step 2: Paid fetch — actual signals
    if args.free_only:
        print("\n  --free-only set, skipping paid signal fetch.")
        print(f"\n{'=' * 60}\n")
        return

    print("  [3/3] Querying signals (paid, $0.002 via x402)...")
    try:
        signals = client.query_signals({"limit": args.limit})
        print(f"         Received {len(signals)} signals")
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 402:
            print("         ERROR: 402 Payment Required.")
            print("         Set --x402-payment or DELPHI_X402_PAYMENT env var.")
            print("         Or use --free-only to skip paid endpoints.")
            sys.exit(1)
        raise
    except Exception as e:
        print(f"         Error fetching signals: {e}")
        print("         Trying /v1/signals/latest as fallback...")
        try:
            signals = client.get_latest_signals(limit=args.limit)
            print(f"         Received {len(signals)} signals via /latest")
        except Exception as e2:
            print(f"         Fallback also failed: {e2}")
            sys.exit(1)

    if not signals:
        print("\n  No signals to mine.")
        print(f"\n{'=' * 60}\n")
        return

    # Step 3: File into palace
    print(f"\n  Filing {len(signals)} signals into palace...\n")
    stats = mine_signals(signals, palace_path, dry_run=args.dry_run, collection_name=args.collection)

    print(f"\n{'=' * 60}")
    print("  Done.")
    print(f"  Signals received: {stats['total']}")
    print(f"  Drawers filed:    {stats['filed']}")
    print(f"  Skipped:          {stats['skipped']}")
    if stats["rooms"]:
        print("\n  By room:")
        for room, count in sorted(stats["rooms"].items(), key=lambda x: x[1], reverse=True):
            print(f"    {room:30} {count} drawers")
    print(f"\n  Search: mempalace search 'market anomaly' --wing delphi")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()

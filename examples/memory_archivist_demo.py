#!/usr/bin/env python3
"""
Example: Using LiteArchivist for Dense, Long-Term Memory
========================================================

Demonstrates how to use the SQLite-based archive to store
structured AAAK summaries for deep history retrieval.
"""

import os
from pathlib import Path
from mempalace.archivist import LiteArchivist
from mempalace.dialect import Dialect

def run_demo():
      # 1. Setup paths
      palace_dir = Path("./demo_palace")
      palace_dir.mkdir(exist_ok=True)
      db_path = palace_dir / "palace_archive.db"

    # 2. Initialize Archivist and Dialect
      archivist = LiteArchivist(str(db_path))
      dialect = Dialect()

    print("--- Archiving New Memory ---")

    # 3. Simulate a memory entry
    raw_text = """
        We decided to implement the 'LiteArchivist' pattern today. 
            It uses SQLite for local-first density. This is a foundational pillar 
                for our memory architecture. We chose this over a cloud-only solution 
                    to ensure user privacy and speed.
                        """

    # 4. Compress to AAAK Dialect
    summary = dialect.compress(raw_text, metadata={
              "wing": "CoreArchitecture",
              "room": "Persistence",
              "date": "2026-04-12"
    })

    print(f"AAAK Summary:\n{summary}\n")

    # 5. Store in Archive
    archivist.archive(
              content=raw_text,
              summary=summary,
              session_id="session_001",
              tags=["architecture", "sqlite", "privacy", "foundation"],
              concepts=["archivist", "density"],
              importance=0.9
    )

    print("[DONE] Memory archived successfully.\n")

    # 6. Retrieve via Tag Search
    print("--- Querying Archive ---")
    results = archivist.search(tags=["architecture"], limit=1)

    for r in results:
              print(f"[Match Found]")
              print(f"ID:      {r['id']}")
              print(f"Summary: {r['summary']}")
              print(f"Created: {r['created_at']}")

    # 7. Check Density Report
    stats = archivist.get_density_report()
    print(f"\nArchive Density: {stats['total_entries']} entries across {stats['unique_tags']} tags.")

if __name__ == "__main__":
      run_demo()

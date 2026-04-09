"""
MemPalace backup, export, and import utilities.

backup  — copy or zip the palace directory (binary, fast restore)
export  — dump drawers to JSONL files organized by wing/room (git-friendly)
import  — load JSONL drawers into the palace (merge, deduplicate by ID)
"""

import json
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

import chromadb


def backup_palace(palace_path: str, zip_mode: bool = False, max_backups: int = 5):
    """Create a timestamped backup of the palace directory.

    Args:
        palace_path: Path to the palace directory.
        zip_mode: If True, create a zip archive instead of a directory copy.
        max_backups: Maximum number of backups to retain (0 = unlimited).
    """
    palace = Path(palace_path)
    if not palace.exists():
        print(f"  No palace found at {palace_path}")
        return None

    parent = palace.parent
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_name = f"palace-backup-{timestamp}"

    if zip_mode:
        backup_path = parent / f"{backup_name}.zip"
        print(f"  Creating zip backup: {backup_path}")
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(palace):
                for f in files:
                    file_path = Path(root) / f
                    arcname = file_path.relative_to(palace)
                    zf.write(file_path, arcname)
        size_mb = backup_path.stat().st_size / (1024 * 1024)
        print(f"  Backup size: {size_mb:.1f} MB")
    else:
        backup_path = parent / backup_name
        print(f"  Creating backup: {backup_path}")
        shutil.copytree(palace, backup_path)
        total = sum(f.stat().st_size for f in backup_path.rglob("*") if f.is_file())
        size_mb = total / (1024 * 1024)
        print(f"  Backup size: {size_mb:.1f} MB")

    # Prune old backups
    if max_backups > 0:
        pattern = "palace-backup-*.zip" if zip_mode else "palace-backup-*"
        existing = sorted(parent.glob(pattern))
        if not zip_mode:
            existing = [p for p in existing if p.is_dir()]
        if len(existing) > max_backups:
            to_remove = existing[: len(existing) - max_backups]
            for old in to_remove:
                print(f"  Pruning old backup: {old.name}")
                if old.is_dir():
                    shutil.rmtree(old)
                else:
                    old.unlink()

    print(f"  Done.")
    return backup_path


def export_palace(palace_path: str, output_dir: str):
    """Export all drawers to JSONL files organized by wing/room.

    Args:
        palace_path: Path to the palace directory.
        output_dir: Directory to write JSONL files to.
    """
    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
    except Exception:
        print(f"  No palace found at {palace_path}")
        return

    total = col.count()
    print(f"  Exporting {total} drawers from {palace_path}")

    # Fetch all drawers in batches
    batch_size = 5000
    all_docs = []
    all_metas = []
    all_ids = []

    offset = 0
    while offset < total:
        results = col.get(
            limit=batch_size, offset=offset, include=["documents", "metadatas"]
        )
        all_docs.extend(results["documents"])
        all_metas.extend(results["metadatas"])
        all_ids.extend(results["ids"])
        offset += batch_size

    # Group by wing/room
    groups = {}
    for doc, meta, did in zip(all_docs, all_metas, all_ids):
        wing = meta.get("wing", "unknown")
        room = meta.get("room", "general")
        key = (wing, room)
        if key not in groups:
            groups[key] = []
        groups[key].append({"id": did, "document": doc, "metadata": meta})

    # Write JSONL files
    out = Path(output_dir)
    total_files = 0
    for (wing, room), drawers in sorted(groups.items()):
        wing_dir = out / wing
        wing_dir.mkdir(parents=True, exist_ok=True)
        filepath = wing_dir / f"{room}.jsonl"
        with open(filepath, "w", encoding="utf-8") as f:
            for drawer in drawers:
                f.write(json.dumps(drawer, ensure_ascii=False) + "\n")
        total_files += 1
        print(f"  {wing}/{room}.jsonl — {len(drawers)} drawers")

    print(f"\n  Exported to {output_dir}")
    print(f"  {total_files} files, {len(all_ids)} drawers total")


def import_palace(palace_path: str, input_dir: str):
    """Import JSONL drawers into the palace, deduplicating by ID.

    Args:
        palace_path: Path to the palace directory.
        input_dir: Directory containing wing/room.jsonl files.
    """
    os.makedirs(palace_path, exist_ok=True)
    client = chromadb.PersistentClient(path=palace_path)
    try:
        col = client.get_collection("mempalace_drawers")
    except Exception:
        col = client.create_collection("mempalace_drawers")

    inp = Path(input_dir)
    if not inp.exists():
        print(f"  Import directory not found: {input_dir}")
        return

    total_added = 0
    total_skipped = 0

    for jsonl_file in sorted(inp.rglob("*.jsonl")):
        wing = jsonl_file.parent.name
        room = jsonl_file.stem

        drawers = []
        with open(jsonl_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    drawers.append(json.loads(line))

        if not drawers:
            continue

        # Check which IDs already exist
        ids = [d["id"] for d in drawers]
        existing = set()
        try:
            result = col.get(ids=ids, include=[])
            existing = set(result["ids"])
        except Exception:
            pass

        new_drawers = [d for d in drawers if d["id"] not in existing]
        skipped = len(drawers) - len(new_drawers)

        if new_drawers:
            batch_size = 5000
            for i in range(0, len(new_drawers), batch_size):
                batch = new_drawers[i : i + batch_size]
                col.add(
                    ids=[d["id"] for d in batch],
                    documents=[d["document"] for d in batch],
                    metadatas=[d["metadata"] for d in batch],
                )

        total_added += len(new_drawers)
        total_skipped += skipped
        print(f"  {wing}/{room}.jsonl — +{len(new_drawers)} new, {skipped} skipped")

    print(f"\n  Import complete: {total_added} added, {total_skipped} already existed")

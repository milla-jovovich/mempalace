"""
exporter.py — Export the palace as a browsable folder of markdown files.

Produces:
  output_dir/
    index.md              — table of contents
    wing_name/
      room_name.md        — one file per room, drawers as sections
"""

import os
from collections import defaultdict
from datetime import datetime

from .palace import get_collection


def export_palace(palace_path: str, output_dir: str, format: str = "markdown") -> dict:
    """Export all palace drawers as markdown files organized by wing/room.

    Args:
        palace_path: Path to the ChromaDB palace directory.
        output_dir: Where to write the exported markdown tree.
        format: Output format (currently only "markdown").

    Returns:
        Stats dict: {"wings": N, "rooms": N, "drawers": N}
    """
    col = get_collection(palace_path)
    total = col.count()

    if total == 0:
        print("  Palace is empty — nothing to export.")
        return {"wings": 0, "rooms": 0, "drawers": 0}

    # Paginate all drawers in batches of 1000
    print(f"  Reading {total} drawers...")
    grouped = defaultdict(lambda: defaultdict(list))
    offset = 0
    while offset < total:
        batch = col.get(limit=1000, offset=offset, include=["documents", "metadatas"])
        if not batch["ids"]:
            break
        for doc_id, doc, meta in zip(batch["ids"], batch["documents"], batch["metadatas"]):
            wing = meta.get("wing", "unknown")
            room = meta.get("room", "general")
            grouped[wing][room].append({
                "id": doc_id,
                "content": doc,
                "source": meta.get("source_file", ""),
                "filed_at": meta.get("filed_at", ""),
                "added_by": meta.get("added_by", ""),
            })
        offset += len(batch["ids"])

    # Write markdown files
    os.makedirs(output_dir, exist_ok=True)
    total_drawers = 0

    index_rows = []

    for wing in sorted(grouped):
        wing_dir = os.path.join(output_dir, wing)
        os.makedirs(wing_dir, exist_ok=True)
        wing_drawer_count = 0

        rooms = grouped[wing]
        for room in sorted(rooms):
            drawers = rooms[room]
            room_path = os.path.join(wing_dir, f"{room}.md")

            sections = []
            for drawer in drawers:
                source = drawer["source"] or "unknown"
                filed = drawer["filed_at"] or "unknown"
                added_by = drawer["added_by"] or "unknown"

                section = (
                    f"## {drawer['id']}\n"
                    f"\n"
                    f"> {_quote_content(drawer['content'])}\n"
                    f"\n"
                    f"| Field | Value |\n"
                    f"|-------|-------|\n"
                    f"| Source | {source} |\n"
                    f"| Filed | {filed} |\n"
                    f"| Added by | {added_by} |\n"
                    f"\n"
                    f"---"
                )
                sections.append(section)

            body = f"# {wing} / {room}\n\n" + "\n\n".join(sections) + "\n"
            with open(room_path, "w", encoding="utf-8") as f:
                f.write(body)

            wing_drawer_count += len(drawers)

        total_drawers += wing_drawer_count
        index_rows.append((wing, len(rooms), wing_drawer_count))
        print(f"  {wing}: {len(rooms)} rooms, {wing_drawer_count} drawers")

    # Write index.md
    today = datetime.now().strftime("%Y-%m-%d")
    index_lines = [
        f"# Palace Export — {today}\n",
        "",
        "| Wing | Rooms | Drawers |",
        "|------|-------|---------|",
    ]
    for wing, room_count, drawer_count in index_rows:
        index_lines.append(f"| [{wing}]({wing}/) | {room_count} | {drawer_count} |")
    index_lines.append("")

    index_path = os.path.join(output_dir, "index.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(index_lines))

    stats = {"wings": len(grouped), "rooms": sum(r for _, r, _ in index_rows), "drawers": total_drawers}
    print(f"\n  Exported {stats['drawers']} drawers across {stats['wings']} wings, {stats['rooms']} rooms")
    print(f"  Output: {output_dir}")
    return stats


def _quote_content(text: str) -> str:
    """Format content for a markdown blockquote, handling multiline."""
    lines = text.rstrip("\n").split("\n")
    return "\n> ".join(lines)

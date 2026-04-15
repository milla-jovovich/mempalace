#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def find_node(graph: list[dict], node_id: str) -> dict | None:
    for node in graph:
        if node.get("@id") == node_id:
            return node
    return None


def _collect_refs(value, out: set[str]) -> None:
    if isinstance(value, str) and value.startswith("did:"):
        out.add(value)
    elif isinstance(value, list):
        for item in value:
            _collect_refs(item, out)
    elif isinstance(value, dict):
        for item in value.values():
            _collect_refs(item, out)


def frame_unit(doc: dict, node_id: str) -> dict:
    graph = doc.get("@graph", [])
    root = find_node(graph, node_id)
    if not root:
        raise KeyError(f"missing node: {node_id}")

    related_ids: set[str] = {node_id}
    _collect_refs(root, related_ids)

    expanded = True
    while expanded:
        expanded = False
        for node in graph:
            current_id = node.get("@id")
            if current_id not in related_ids:
                continue
            before = len(related_ids)
            _collect_refs(node, related_ids)
            if len(related_ids) > before:
                expanded = True

    framed_graph = [node for node in graph if node.get("@id") in related_ids]
    return {
        "@context": doc.get("@context", []),
        "@graph": framed_graph,
    }


def main() -> int:
    if len(sys.argv) != 4:
        print("Usage: python frame_runtime_registry_from_binding_graph.py <binding.graph.jsonld> <node-id> <output.jsonld>")
        return 2

    source = Path(sys.argv[1]).expanduser().resolve()
    node_id = sys.argv[2]
    out = Path(sys.argv[3]).expanduser().resolve()
    framed = frame_unit(load_json(source), node_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(framed, indent=2) + "\n", encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

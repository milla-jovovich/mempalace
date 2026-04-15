#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

RUNTIME_REGISTRY_ID = "did:webvh:{SCID}:github.com:Fleet-to-Force:mempalace#op/runtime-registry"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def find_node(graph: list[dict], node_id: str) -> dict | None:
    for node in graph:
        if node.get("@id") == node_id:
            return node
    return None


def frame_runtime_registry(doc: dict) -> dict:
    graph = doc.get("@graph", [])
    root = find_node(graph, RUNTIME_REGISTRY_ID)
    if not root:
        raise KeyError(f"missing runtime-registry node: {RUNTIME_REGISTRY_ID}")

    related_ids: set[str] = {RUNTIME_REGISTRY_ID}
    for layer_name in ("l0", "l1", "l2", "l3"):
        for entry in root.get(layer_name, []) or []:
            if isinstance(entry, dict) and entry.get("@id"):
                related_ids.add(entry["@id"])
            if isinstance(entry, dict):
                for field in ("bindsTo", "authority", "protocol", "permissionPolicy", "observedBy"):
                    value = entry.get(field)
                    if isinstance(value, str):
                        related_ids.add(value)
                for field in ("emitsArtifact", "participatesIn"):
                    values = entry.get(field, []) or []
                    if isinstance(values, list):
                        for value in values:
                            if isinstance(value, str):
                                related_ids.add(value)

    expanded = True
    while expanded:
        expanded = False
        for node in graph:
            node_id = node.get("@id")
            if node_id not in related_ids:
                continue
            for field in ("realizedBy",):
                value = node.get(field)
                if isinstance(value, str) and value not in related_ids:
                    related_ids.add(value)
                    expanded = True

    framed_graph = [node for node in graph if node.get("@id") in related_ids]
    return {
        "@context": doc.get("@context", []),
        "@graph": framed_graph,
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python frame_runtime_registry_from_binding_graph.py <binding.graph.jsonld> <output.jsonld>")
        return 2

    source = Path(sys.argv[1]).expanduser().resolve()
    out = Path(sys.argv[2]).expanduser().resolve()
    framed = frame_runtime_registry(load_json(source))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(framed, indent=2) + "\n", encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

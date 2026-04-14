#!/usr/bin/env python3
from __future__ import annotations
import json
import sys
from pathlib import Path

import yaml


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding='utf-8'))


def compile_hot_to_cold(doc: dict) -> dict:
    context = doc.get('@context', [])
    root = {
        '@context': context if isinstance(context, list) else [context],
        '@graph': []
    }

    root_fields = {
        '@id': doc.get('@id'),
        '@type': doc.get('@type'),
        'repoName': doc.get('repoName'),
        'displayName': doc.get('displayName'),
        'repoUrl': doc.get('repoUrl'),
        'packageName': doc.get('packageName'),
        'commandName': doc.get('commandName'),
        'hiddenDir': doc.get('hiddenDir'),
        'moduleEntry': doc.get('moduleEntry'),
    }
    root['@graph'].append({k: v for k, v in root_fields.items() if v is not None})

    for key in ['collections', 'capabilities', 'domainManagers', 'toggles', 'hooks']:
        for item in doc.get(key, []) or []:
            root['@graph'].append(item)

    return root


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print('Usage: python compile_semantic_identity.py /path/to/repo.identity.yaml [output.jsonld]')
        return 2
    src = Path(sys.argv[1]).expanduser().resolve()
    dst = Path(sys.argv[2]).expanduser().resolve() if len(sys.argv) == 3 else None
    doc = load_yaml(src)
    compiled = compile_hot_to_cold(doc)
    if dst:
        dst.write_text(json.dumps(compiled, indent=2), encoding='utf-8')
        print(str(dst))
        return 0
    print(json.dumps(compiled, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

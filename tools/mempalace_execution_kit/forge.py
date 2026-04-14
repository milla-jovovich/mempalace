#!/usr/bin/env python3
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Any

from compile_identity import load, validate, derive, plan


def load_batch(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def cmd_compile(cfg_path: Path) -> int:
    raw = load(cfg_path)
    errors = validate(raw)
    if errors:
        print(json.dumps({'errors': errors}, indent=2))
        return 1
    print(json.dumps(derive(raw), indent=2))
    return 0


def cmd_plan(cfg_path: Path) -> int:
    raw = load(cfg_path)
    errors = validate(raw)
    if errors:
        print(json.dumps({'errors': errors}, indent=2))
        return 1
    print(json.dumps(plan(derive(raw)), indent=2))
    return 0


def cmd_batch_plan(batch_path: Path) -> int:
    raw = load_batch(batch_path)
    source = raw.get('source')
    targets = raw.get('targets', [])
    if not source or not isinstance(targets, list):
        print(json.dumps({'errors': ['batch file must contain source and targets[]']}, indent=2))
        return 1
    compiled = []
    errors = []
    for i, item in enumerate(targets):
        cfg = {
            'source': source,
            'target': item.get('target'),
            'overrides': item.get('overrides', {}),
            'interpreter_policy': item.get('interpreter_policy', {'fallback_command': 'python'})
        }
        val_errors = validate(cfg)
        if val_errors:
            errors.append({'index': i, 'errors': val_errors})
            continue
        exp = derive(cfg)
        compiled.append({'index': i, 'target': item.get('target', {}).get('id'), 'plan': plan(exp)})
    print(json.dumps({'compiled': compiled, 'errors': errors}, indent=2))
    return 1 if errors else 0


def main() -> int:
    if len(sys.argv) != 3:
        print('Usage: python forge.py <compile|plan|batch-plan> /path/to/config.json')
        return 2
    action = sys.argv[1]
    path = Path(sys.argv[2]).expanduser().resolve()
    if action == 'compile':
        return cmd_compile(path)
    if action == 'plan':
        return cmd_plan(path)
    if action == 'batch-plan':
        return cmd_batch_plan(path)
    print('Unknown action')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())

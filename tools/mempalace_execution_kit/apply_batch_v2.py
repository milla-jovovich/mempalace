#!/usr/bin/env python3
from __future__ import annotations
import json
import sys
from pathlib import Path

from compile_identity import validate, derive
from apply_conventions_v2 import iter_files, read_text, write_text, replace_text, patch_hook_file, patch_json_manifest, rename_package_dir

PLUGIN_MANIFESTS = [
    '.claude-plugin/.mcp.json',
    '.claude-plugin/plugin.json',
    '.codex-plugin/plugin.json',
    '.codex-plugin/hooks.json',
]
HOOK_FILES = [
    'hooks/mempal_save_hook.sh',
    'hooks/mempal_precompact_hook.sh',
    '.claude-plugin/hooks/mempal-stop-hook.sh',
    '.claude-plugin/hooks/mempal-precompact-hook.sh',
    '.codex-plugin/hooks/mempal-hook.sh',
]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def apply_one(repo_root: Path, cfg: dict) -> int:
    rename_package_dir(repo_root, cfg)
    changed = 0
    for path in iter_files(repo_root):
        old = read_text(path)
        new = replace_text(old, cfg)
        if new != old:
            write_text(path, new)
            changed += 1
    for rel in PLUGIN_MANIFESTS:
        patch_json_manifest(repo_root / rel, cfg)
    for rel in HOOK_FILES:
        patch_hook_file(repo_root / rel, cfg)
    return changed


def main() -> int:
    if len(sys.argv) != 2:
        print('Usage: python apply_batch_v2.py /path/to/batch_targets.json')
        return 2
    raw = load(Path(sys.argv[1]).expanduser().resolve())
    source = raw.get('source')
    targets = raw.get('targets', [])
    if not source or not isinstance(targets, list):
        print(json.dumps({'errors': ['batch file must contain source and targets[]']}, indent=2))
        return 1
    results = []
    errors = []
    for i, item in enumerate(targets):
        repo_path = item.get('repo_path')
        if not repo_path:
            errors.append({'index': i, 'error': 'missing repo_path'})
            continue
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
        compiled = derive(cfg)
        repo_root = Path(repo_path).expanduser().resolve()
        changed = apply_one(repo_root, compiled)
        results.append({'index': i, 'target': item.get('target', {}).get('id'), 'repo_path': str(repo_root), 'changed_files': changed})
    print(json.dumps({'results': results, 'errors': errors}, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())

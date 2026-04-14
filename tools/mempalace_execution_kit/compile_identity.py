#!/usr/bin/env python3
from __future__ import annotations
import json
import re
import sys
from pathlib import Path


def slug_to_env(name: str) -> str:
    return re.sub(r'[^A-Z0-9]+', '_', name.upper()).strip('_')


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def validate(cfg: dict) -> list[str]:
    errors: list[str] = []
    for key in ['source', 'target']:
        if key not in cfg:
            errors.append(f'missing top-level key: {key}')
    if errors:
        return errors
    src = cfg['source']
    tgt = cfg['target']
    for key in ['package', 'command', 'hidden_dir', 'module_entry', 'collections']:
        if key not in src:
            errors.append(f'missing source.{key}')
    for key in ['id', 'display_name', 'repo_url']:
        if key not in tgt:
            errors.append(f'missing target.{key}')
    if 'hidden_dir' in src and not str(src['hidden_dir']).startswith('.'):
        errors.append('source.hidden_dir must start with a dot')
    if 'id' in tgt and not re.match(r'^[a-z][a-z0-9_]*$', str(tgt['id'])):
        errors.append('target.id must match ^[a-z][a-z0-9_]*$')
    return errors


def derive(raw: dict) -> dict:
    src = raw['source']
    tgt = raw['target']
    ov = raw.get('overrides', {})
    ov_col = ov.get('collections') or {}

    package = ov.get('package') or tgt['id']
    command = ov.get('command') or package
    hidden_dir = ov.get('hidden_dir') or f'.{package}'
    module_entry = ov.get('module_entry') or f'{package}.mcp_server'
    plugin_name = ov.get('plugin_name') or package
    plugin_display_name = ov.get('plugin_display_name') or tgt.get('display_name') or package
    interpreter_env_var = ov.get('interpreter_env_var') or f'{slug_to_env(package)}_PYTHON'
    collections = {
        'drawers': ov_col.get('drawers') or f'{package}_drawers',
        'compressed': ov_col.get('compressed') or f'{package}_compressed',
        'closets': ov_col.get('closets') or f'{package}_closets',
    }

    return {
        'source_package_name': src['package'],
        'source_cli_command': src['command'],
        'source_hidden_dir': src['hidden_dir'],
        'source_module_entry': src['module_entry'],
        'source_repo_url': src.get('repo_url'),
        'source_collection_names': src['collections'],
        'target_package_name': package,
        'target_cli_command': command,
        'target_hidden_dir': hidden_dir,
        'target_module_entry': module_entry,
        'target_repo_url': tgt['repo_url'],
        'target_collection_names': collections,
        'plugin_name': plugin_name,
        'plugin_display_name': plugin_display_name,
        'brand_color': tgt.get('brand_color', '#2563EB'),
        'interpreter_policy': {
            'env_var': interpreter_env_var,
            'fallback_command': raw.get('interpreter_policy', {}).get('fallback_command', 'python')
        }
    }


def plan(expanded: dict) -> dict:
    return {
        'identity': {
            'package': expanded['target_package_name'],
            'command': expanded['target_cli_command'],
            'hidden_dir': expanded['target_hidden_dir'],
            'module_entry': expanded['target_module_entry'],
            'plugin_name': expanded['plugin_name'],
            'plugin_display_name': expanded['plugin_display_name'],
            'repo_url': expanded['target_repo_url'],
        },
        'collections': expanded['target_collection_names'],
        'interpreter': expanded['interpreter_policy'],
        'replacements': {
            'package': [expanded['source_package_name'], expanded['target_package_name']],
            'command': [expanded['source_cli_command'], expanded['target_cli_command']],
            'hidden_dir': [expanded['source_hidden_dir'], expanded['target_hidden_dir']],
            'module_entry': [expanded['source_module_entry'], expanded['target_module_entry']],
            'repo_url': [expanded.get('source_repo_url'), expanded['target_repo_url']],
            'collections': {
                k: [expanded['source_collection_names'][k], expanded['target_collection_names'][k]]
                for k in ['drawers', 'compressed', 'closets']
            }
        }
    }


def main() -> None:
    if len(sys.argv) not in (2, 3):
        print('Usage: python compile_identity.py /path/to/conventions.json [--plan]')
        raise SystemExit(2)
    raw = load(Path(sys.argv[1]).expanduser().resolve())
    errors = validate(raw)
    if errors:
        print(json.dumps({'errors': errors}, indent=2))
        raise SystemExit(1)
    expanded = derive(raw)
    if len(sys.argv) == 3 and sys.argv[2] == '--plan':
        print(json.dumps(plan(expanded), indent=2))
        return
    print(json.dumps(expanded, indent=2))


if __name__ == '__main__':
    main()

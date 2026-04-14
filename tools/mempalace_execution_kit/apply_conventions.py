#!/usr/bin/env python3
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

TEXT_EXTS = {'.py','.md','.json','.toml','.yml','.yaml','.sh','.txt','.ini','.cfg','.lock'}
SKIP_DIRS = {'.git','.venv','venv','__pycache__','.pytest_cache','node_modules','dist','build'}
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

def iter_files(root: Path):
    for p in root.rglob('*'):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() in TEXT_EXTS:
            yield p

def read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8')

def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding='utf-8')

def replace_text(text: str, cfg: dict) -> str:
    sp = cfg['source_package_name']
    tp = cfg['target_package_name']
    sc = cfg['source_cli_command']
    tc = cfg['target_cli_command']
    shd = cfg['source_hidden_dir']
    thd = cfg['target_hidden_dir']
    sme = cfg['source_module_entry']
    tme = cfg['target_module_entry']
    srepo = cfg.get('source_repo_url')
    trepo = cfg.get('target_repo_url')
    coll_src = cfg['source_collection_names']
    coll_tgt = cfg['target_collection_names']

    replacements = [
        (sme, tme),
        (f'python -m {sp}.mcp_server', f'python -m {tp}.mcp_server'),
        (f'python3 -m {sp}.mcp_server', f'python -m {tp}.mcp_server'),
        (f'{sp}.cli:main', f'{tp}.cli:main'),
        (coll_src['drawers'], coll_tgt['drawers']),
        (coll_src['compressed'], coll_tgt['compressed']),
        (coll_src['closets'], coll_tgt['closets']),
        (f'~/{shd}', f'~/{thd}'),
        (shd, thd),
    ]
    if srepo and trepo:
        replacements.append((srepo, trepo))
    for a, b in replacements:
        text = text.replace(a, b)

    text = re.sub(rf'(?m)^(\s*from\s+){re.escape(sp)}(\b)', rf'\1{tp}\2', text)
    text = re.sub(rf'(?m)^(\s*import\s+){re.escape(sp)}(\b)', rf'\1{tp}\2', text)
    text = re.sub(rf'(?<![\w.-]){re.escape(sc)}(?![\w.-])', tc, text)
    return text

def patch_hook_file(path: Path, cfg: dict) -> None:
    if not path.exists():
        return
    text = read_text(path)
    env_var = cfg['interpreter_policy']['env_var']
    fallback = cfg['interpreter_policy']['fallback_command']
    tp = cfg['target_package_name']
    tc = cfg['target_cli_command']
    shim = f'PYTHON="${{{env_var}:-$(command -v {fallback} 2>/dev/null || command -v python3 2>/dev/null || command -v python 2>/dev/null)}}"'
    text = re.sub(r'PYTHON="\$\(command -v python3\)"', shim, text)
    text = text.replace('python3 -m ', '"$PYTHON" -m ')
    text = text.replace('python -m ', '"$PYTHON" -m ')
    text = text.replace('mempalace mine', f'{tc} mine')
    text = text.replace('-m mempalace ', f'-m {tp} ')
    write_text(path, text)

def rename_package_dir(root: Path, cfg: dict) -> None:
    src = root / cfg['source_package_name']
    dst = root / cfg['target_package_name']
    if src.exists() and src.is_dir() and src != dst:
        if dst.exists():
            raise RuntimeError(f'Target package dir already exists: {dst}')
        src.rename(dst)

def patch_json_manifest(path: Path, cfg: dict) -> None:
    if not path.exists():
        return
    try:
        data = json.loads(read_text(path))
    except Exception:
        return
    tme = cfg['target_module_entry']
    trepo = cfg['target_repo_url']
    fallback = cfg['interpreter_policy']['fallback_command']
    display = cfg['plugin_display_name']
    def walk(obj):
        if isinstance(obj, dict):
            return {k: walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [walk(v) for v in obj]
        if isinstance(obj, str):
            s = obj.replace('mempalace.mcp_server', tme)
            s = s.replace('mempalace', cfg['target_package_name'])
            s = s.replace('python3', fallback)
            s = s.replace('https://github.com/MemPalace/mempalace', trepo)
            s = s.replace('MemPalace', display)
            return s
        return obj
    data = walk(data)
    if 'name' in data:
        data['name'] = cfg['plugin_name']
    if 'repository' in data:
        data['repository'] = trepo
    if 'homepage' in data:
        data['homepage'] = trepo
    if isinstance(data.get('interface'), dict):
        data['interface']['displayName'] = display
        data['interface']['brandColor'] = cfg.get('brand_color', data['interface'].get('brandColor', '#2563EB'))
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + '\n')

def main():
    if len(sys.argv) != 3:
        print('Usage: python apply_conventions.py /path/to/repo /path/to/conventions.json')
        raise SystemExit(2)
    root = Path(sys.argv[1]).expanduser().resolve()
    cfg = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    rename_package_dir(root, cfg)
    changed = 0
    for path in iter_files(root):
        old = read_text(path)
        new = replace_text(old, cfg)
        if new != old:
            write_text(path, new)
            changed += 1
    for rel in PLUGIN_MANIFESTS:
        patch_json_manifest(root / rel, cfg)
    for rel in HOOK_FILES:
        patch_hook_file(root / rel, cfg)
    print(f'Applied convention rewrite under: {root}')
    print(f'Text files changed: {changed}')
    print('Next: run verify_conventions.py, then Ruff and pytest.')

if __name__ == '__main__':
    main()

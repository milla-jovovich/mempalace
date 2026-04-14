#!/usr/bin/env python3
from __future__ import annotations
import json
import sys
from pathlib import Path

TEXT_EXTS = {'.py','.md','.json','.toml','.yml','.yaml','.sh','.txt','.ini','.cfg','.lock'}
SKIP_DIRS = {'.git','.venv','venv','__pycache__','.pytest_cache','node_modules','dist','build'}

def iter_files(root: Path):
    for p in root.rglob('*'):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() in TEXT_EXTS:
            yield p

def main():
    if len(sys.argv) != 3:
        print('Usage: python verify_conventions.py /path/to/repo /path/to/conventions.json')
        raise SystemExit(2)
    root = Path(sys.argv[1]).expanduser().resolve()
    cfg = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    needles = [
        cfg['source_package_name'],
        cfg['source_cli_command'],
        cfg['source_hidden_dir'],
        cfg['source_module_entry'],
        'python3',
        'https://github.com/MemPalace/mempalace',
    ]
    hits = []
    for path in iter_files(root):
        text = path.read_text(encoding='utf-8')
        for needle in needles:
            if needle and needle in text:
                hits.append((str(path.relative_to(root)), needle))
    print(f'Verification scan for: {root}')
    if not hits:
        print('No stale source literals found in scanned text files.')
        return
    print('Stale literals still present:')
    for rel, needle in hits:
        print(f'  {rel}: {needle}')
    raise SystemExit(1)

if __name__ == '__main__':
    main()

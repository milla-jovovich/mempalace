#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: ./run_all_v2.sh /path/to/repo /path/to/conventions.json"
  exit 2
fi

python compile_identity.py "$2" > /tmp/mempalace_identity_compiled.json
python apply_conventions_v2.py "$1" "$2"
python verify_conventions.py "$1" /tmp/mempalace_identity_compiled.json

echo
echo "Next steps:"
echo "  cd $1"
echo "  ruff check ."
echo "  ruff format --check ."
echo "  python -m pytest tests/ -v --ignore=tests/benchmarks"

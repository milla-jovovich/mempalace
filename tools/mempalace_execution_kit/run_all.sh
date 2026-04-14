#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: ./run_all.sh /path/to/repo /path/to/conventions.json"
  exit 2
fi

python apply_conventions.py "$1" "$2"
python verify_conventions.py "$1" "$2"

echo
echo "Next steps:"
echo "  cd $1"
echo "  ruff check ."
echo "  ruff format --check ."
echo "  python -m pytest tests/ -v --ignore=tests/benchmarks"

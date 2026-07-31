#!/usr/bin/env bash
# The gate: exactly what CI runs, in the same order. Run before every commit.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m pytest tests/ -q

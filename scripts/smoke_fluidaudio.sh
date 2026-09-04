#!/bin/sh
set -eu

binary="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/vendor/fluidaudiocli"
test -x "$binary"
"$binary" transcribe --help >/dev/null 2>&1
echo "FluidAudio smoke test passed: $binary"

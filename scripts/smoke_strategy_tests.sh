#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PS_SCRIPT="$SCRIPT_DIR/smoke_strategy_tests.ps1"

if command -v pwsh >/dev/null 2>&1; then
  exec pwsh -NoProfile -ExecutionPolicy Bypass -File "$PS_SCRIPT" "$@"
fi

if command -v powershell >/dev/null 2>&1; then
  exec powershell -NoProfile -ExecutionPolicy Bypass -File "$PS_SCRIPT" "$@"
fi

echo "PowerShell is required to run scripts/smoke_strategy_tests.ps1 from this shell wrapper." >&2
exit 127

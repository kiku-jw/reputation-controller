#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DEFAULT_PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PATH="${CONTROLLER_PATH:-$DEFAULT_PATH}"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

WORKSPACE="${CONTROLLER_WORKSPACE:-$ROOT/..}"
mkdir -p "$WORKSPACE/.controller/logs"

export PYTHONPATH="$ROOT/src"
exec python3 -m reputation_controller \
  --config "$ROOT/config/controller.example.json" \
  loop \
  --interval "${CONTROLLER_LOOP_INTERVAL_SECONDS:-900}"

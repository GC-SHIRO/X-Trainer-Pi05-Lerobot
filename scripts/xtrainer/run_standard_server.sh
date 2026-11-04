#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p outputs/standard_logs
RUN_ID=$(date +%Y%m%d_%H%M%S)
/home/dell211/miniconda3/envs/xtrainer-pi05/bin/python -u -m lerobot.scripts.lerobot_policy_server \
  --config_path="$ROOT/configs/xtrainer/remote_server.json" "$@" \
  2>&1 | tee "outputs/standard_logs/server_${RUN_ID}.log"

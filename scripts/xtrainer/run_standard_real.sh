#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p outputs/standard_logs
RUN_ID=$(date +%Y%m%d_%H%M%S)
/home/dobot/miniconda3/envs/xtrainer-pi05/bin/python -u -m lerobot.scripts.lerobot_rollout \
  --config_path="$ROOT/configs/xtrainer/remote_real.json" --robot.execute=true "$@" \
  2>&1 | tee "outputs/standard_logs/real_${RUN_ID}.log"

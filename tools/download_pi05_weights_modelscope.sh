#!/usr/bin/env bash
set -Eeuo pipefail
ENV_NAME="xtrainer-pi05"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-name)
      [[ $# -ge 2 && "$2" != --* && -n "$2" ]] || { printf 'ERROR: --env-name requires a value\n' >&2; exit 2; }
      ENV_NAME="$2"; shift 2 ;;
    -h|--help)
      printf 'Usage: bash tools/download_pi05_weights_modelscope.sh [--env-name NAME] [download options]\n'
      printf 'Options: --repo-id ID --output-dir PATH --revision REV --tokenizer-repo-id ID\n'
      printf '         --tokenizer-revision REV --endpoint URL --dry-run\n'
      printf 'Default environment: xtrainer-pi05. Full Python CLI: tools/download_pi05_weights.py --help\n'
      exit 0 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
[[ "$ENV_NAME" =~ ^[A-Za-z0-9._-]+$ ]] || { printf 'ERROR: invalid environment name\n' >&2; exit 2; }
command -v conda >/dev/null || { printf 'ERROR: conda not found\n' >&2; exit 1; }
exec conda run --no-capture-output -n "$ENV_NAME" python "$SCRIPT_DIR/download_pi05_weights.py" --source modelscope "${ARGS[@]}"

#!/usr/bin/env bash
# Adapted from X-Trainer-XVLA/tools/install_xtrainer_env.sh.
set -Eeuo pipefail
ENV_NAME="xtrainer-pi05"
SOURCE="china"
CPU_ONLY=0
SYSTEM_PACKAGES=1
DRY_RUN=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
usage() {
  cat <<'HELP'
Usage: bash tools/install_xtrainer_env.sh [OPTIONS]
Create or reuse a Python 3.12 Conda environment for Pi05 / LeRobot.
  --env-name NAME          Default: xtrainer-pi05
  --source china|official  Default: china (Python packages only)
  --cpu-only              CPU wheels for data conversion and mock checks
  --skip-system-packages  Skip apt packages (ffmpeg, build tools, USB runtime)
  --dry-run               Print commands without changing the system
  -h, --help              Show help
Requires Conda and Ubuntu x86_64. CUDA wheels use cu128.
PIP_INDEX_URL and TORCH_INDEX_URL override package indexes for this invocation.
HELP
}
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-name|--source)
      [[ $# -ge 2 && "$2" != --* && -n "$2" ]] || die "$1 requires a value"
      if [[ "$1" == --env-name ]]; then ENV_NAME="$2"; else SOURCE="$2"; fi
      shift 2 ;;
    --cpu-only) CPU_ONLY=1; shift ;;
    --skip-system-packages) SYSTEM_PACKAGES=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[[ "$ENV_NAME" =~ ^[A-Za-z0-9._-]+$ && "$ENV_NAME" != base ]] || die "use a named project environment"
case "$SOURCE" in
  china) INDEX="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}" ;;
  official) INDEX="${PIP_INDEX_URL:-https://pypi.org/simple}" ;;
  *) die "source must be china or official" ;;
esac
WHEEL_FLAVOR=cu128
[[ "$CPU_ONLY" == 0 ]] || WHEEL_FLAVOR=cpu
TORCH_INDEX="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/${WHEEL_FLAVOR}}"
run() {
  if [[ "$DRY_RUN" == 1 ]]; then printf '%q ' "$@"; printf '\n'; else "$@"; fi
}
if [[ "$DRY_RUN" == 0 ]]; then
  [[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || die "requires Linux x86_64"
  source /etc/os-release
  [[ "${ID:-}" == ubuntu ]] || die "requires Ubuntu (recommended: 24.04)"
  command -v conda >/dev/null || die "install Miniconda/Miniforge first"
  if [[ "$CPU_ONLY" == 0 ]]; then
    command -v nvidia-smi >/dev/null || die "NVIDIA driver is required; use --cpu-only for CPU"
    nvidia-smi
  fi
fi
if [[ "$SYSTEM_PACKAGES" == 1 ]]; then
  SUDO=()
  [[ "${EUID}" == 0 ]] || SUDO=(sudo)
  run "${SUDO[@]}" apt-get update
  run "${SUDO[@]}" apt-get install -y build-essential ffmpeg git libusb-1.0-0 udev
fi
if [[ "$DRY_RUN" == 1 ]] || ! conda env list | awk 'NF && $1 !~ /^#/ {print $1}' | grep -Fxq "$ENV_NAME"; then
  run conda create -n "$ENV_NAME" python=3.12 pip -y
fi
PYTHON=(conda run --no-capture-output -n "$ENV_NAME" python)
run "${PYTHON[@]}" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Expected Python 3.12 in the project environment"'
run "${PYTHON[@]}" -m pip install --index-url "$INDEX" --upgrade pip 'setuptools>=71,<82' wheel
run "${PYTHON[@]}" -m pip install --index-url "$TORCH_INDEX" torch==2.8.0 torchvision==0.23.0
run "${PYTHON[@]}" -m pip install --index-url "$INDEX" -c "$SCRIPT_DIR/constraints-pi05.txt" -e "$REPO_ROOT[training,pi05,xtrainer,peft,intelrealsense,test]" modelscope
run "${PYTHON[@]}" -m pip install --index-url "$INDEX" -c "$SCRIPT_DIR/constraints-pi05.txt" -r "$REPO_ROOT/deploy/xtrainer/real/requirements.txt"
run "${PYTHON[@]}" -m pip check
run "${PYTHON[@]}" "$SCRIPT_DIR/check_environment.py" $([[ "$CPU_ONLY" == 0 ]] && printf '%s' '--require-cuda' || true)
printf 'Activate with: conda activate %s\n' "$ENV_NAME"

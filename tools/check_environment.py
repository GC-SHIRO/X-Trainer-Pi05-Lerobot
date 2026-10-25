"""Check Pi05 training, video and deployment imports without loading model weights."""
import argparse
import importlib
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-cuda", action="store_true")
    args = parser.parse_args()
    failures = []
    print(f"Python {platform.python_version()} ({sys.executable})")
    if sys.version_info < (3, 12):
        failures.append("Python 3.12+ required")
    for name in ("torch", "torchvision", "torchcodec", "av", "cv2", "datasets", "pyarrow",
                 "transformers", "accelerate", "wandb", "msgpack", "aiohttp", "yaml",
                 "serial", "pyrealsense2", "huggingface_hub", "modelscope",
                 "lerobot.policies.pi05", "deploy.xtrainer"):
        try:
            module = importlib.import_module(name)
            print(f"OK {name} {getattr(module, '__version__', '')}")
        except Exception as exc:
            failures.append(f"{name}: {exc}")
    if not shutil.which("ffmpeg"):
        failures.append("ffmpeg executable not found")
    if args.require_cuda:
        try:
            import torch
            if not torch.cuda.is_available():
                failures.append("CUDA unavailable")
            else:
                print(f"GPU: {torch.cuda.get_device_name(0)}; CUDA wheel: {torch.version.cuda}")
        except ImportError:
            pass
    if failures:
        raise SystemExit("Environment check failed:\n- " + "\n- ".join(failures))
    print("Environment check passed (no model inference or robot connection performed)")


if __name__ == "__main__":
    main()

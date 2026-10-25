"""Launch Pi05 fine-tuning with a local LeRobot v3 dataset."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def build_command(args):
    root = Path(args.dataset_root).resolve()
    info = json.loads((root / "meta/info.json").read_text(encoding="utf-8"))
    if info.get("codebase_version") != "v3.0":
        raise ValueError("Expected LeRobot v3.0 data; convert raw recordings with convert_raw_to_lerobot.py")
    for key in ("action", "observation.state"):
        if info["features"][key]["shape"] != [14]:
            raise ValueError(f"{key} must have 14 dimensions")
    for camera in ("top", "left_wrist", "right_wrist"):
        if f"observation.images.{camera}" not in info["features"]:
            raise ValueError(f"Missing camera: {camera}")
    stats = json.loads((root / "meta/stats.json").read_text(encoding="utf-8"))
    for key in ("action", "observation.state"):
        for quantile in ("q01", "q99"):
            if quantile not in stats.get(key, {}):
                raise ValueError(f"Pi05 requires {key}/{quantile} normalization statistics")
    if args.resume:
        checkpoint = Path(args.resume).resolve()
        if checkpoint.is_dir():
            checkpoint /= "train_config.json"
        if not checkpoint.is_file():
            raise FileNotFoundError(checkpoint)
        command = [sys.executable, "-m", "lerobot.scripts.lerobot_train",
                   f"--config_path={checkpoint}", "--resume=true"]
    else:
        command = [sys.executable, "-m", "lerobot.scripts.lerobot_train",
                   f"--config_path={ROOT / 'configs/xtrainer/train_pi05.yaml'}",
                   "--policy.input_features={}"]
        policy_path = args.policy_path
        local_base = ROOT / "models/pi05-base"
        if not policy_path and (local_base / "config.json").is_file():
            policy_path = str(local_base)
        if policy_path:
            command.append(f"--policy.path={policy_path}")
            tokenizer = Path(policy_path).expanduser().resolve() / "tokenizer"
            if tokenizer.is_dir():
                command.append(f"--policy.text_tokenizer_name={tokenizer}")
    command += [f"--dataset.root={root}", f"--dataset.repo_id={args.repo_id}"]
    for attr, flag in (("steps", "steps"), ("batch_size", "batch_size"),
                       ("device", "policy.device"), ("output_dir", "output_dir")):
        value = getattr(args, attr)
        if value is not None:
            command.append(f"--{flag}={value}")
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--repo-id", default="xtrainer/pi05")
    parser.add_argument("--policy-path", help="Local base checkpoint or Hugging Face repo ID")
    parser.add_argument("--resume", help="Saved train_config.json or its pretrained_model directory")
    parser.add_argument("--steps", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--device")
    parser.add_argument("--output-dir")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.resume and args.policy_path:
        parser.error("--resume cannot be combined with --policy-path")
    command = build_command(args)
    print(subprocess.list2cmdline(command))
    if not args.dry_run:
        subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()

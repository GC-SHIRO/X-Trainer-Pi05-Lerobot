"""Launch Pi05 fine-tuning with a local LeRobot v3 dataset."""
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAMERA_KEYS = {f"observation.images.{name}" for name in ("top", "left_wrist", "right_wrist")}
JOINT_NAMES = ([f"left_joint{i}.pos" for i in range(1, 7)] + ["left_gripper.pos"]
               + [f"right_joint{i}.pos" for i in range(1, 7)] + ["right_gripper.pos"])


def validate_dataset(info, stats):
    features = info["features"]
    cameras = {key for key, value in features.items()
               if key.startswith("observation.images.") or value.get("dtype") in {"image", "video"}}
    if cameras != CAMERA_KEYS:
        raise ValueError(f"Expected exactly these cameras: {sorted(CAMERA_KEYS)}; got {sorted(cameras)}")
    for key in CAMERA_KEYS:
        feature = features[key]
        shape = feature.get("shape", [])
        if (feature.get("dtype") not in {"image", "video"} or len(shape) != 3
                or shape[-1] != 3 or any(not isinstance(n, int) or n <= 0 for n in shape)):
            raise ValueError(f"{key} must be an RGB image/video with shape [height, width, 3]")
    for key in ("action", "observation.state"):
        feature = features[key]
        if feature.get("shape") != [14] or feature.get("dtype") != "float32":
            raise ValueError(f"{key} must have 14 float32 dimensions")
        if feature.get("names") != JOINT_NAMES:
            raise ValueError(f"{key} joint order must be {JOINT_NAMES}")
        for quantile in ("q01", "q99"):
            values = stats.get(key, {}).get(quantile, [])
            if (len(values) != 14 or any(not isinstance(v, (int, float)) or not math.isfinite(v)
                                         for v in values)):
                raise ValueError(f"Pi05 requires 14 finite {key}/{quantile} normalization statistics")
        if any(lo > hi for lo, hi in zip(stats[key]["q01"], stats[key]["q99"])):
            raise ValueError(f"{key}: q01 must not exceed q99")


def validate_resume(checkpoint):
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    policy = saved["policy"]
    features = policy.get("input_features", {})
    cameras = {key for key in features if key.startswith("observation.images.")}
    if cameras != CAMERA_KEYS or saved.get("rename_map"):
        raise ValueError("Resume checkpoint must use X-Trainer camera names without rename_map; migrate it first")
    if (policy.get("type") != "pi05"
            or features.get("observation.state", {}).get("shape") not in ([14], [policy.get("max_state_dim", 32)])
            or policy.get("output_features", {}).get("action", {}).get("shape") != [14]
            or policy.get("action_feature_names") != JOINT_NAMES):
        raise ValueError("Resume checkpoint must have Pi05 X-Trainer 14-joint features and joint order")
    if (policy.get("use_visual_memory") or policy.get("use_proprioceptive_memory")
            or policy.get("use_relative_actions") or policy.get("empty_cameras", 0)
            or policy.get("n_obs_steps", 1) != 1
            or (policy.get("rtc_config") or {}).get("enabled")):
        raise ValueError("Resume checkpoint must use single-frame absolute actions without RTC or empty cameras")


def build_command(args):
    root = Path(args.dataset_root).resolve()
    info = json.loads((root / "meta/info.json").read_text(encoding="utf-8"))
    if info.get("codebase_version") != "v3.0":
        raise ValueError("Expected LeRobot v3.0 data; convert raw recordings with convert_raw_to_lerobot.py")
    stats = json.loads((root / "meta/stats.json").read_text(encoding="utf-8"))
    validate_dataset(info, stats)
    if args.resume:
        checkpoint = Path(args.resume).resolve()
        if checkpoint.is_dir():
            checkpoint /= "train_config.json"
        if not checkpoint.is_file():
            raise FileNotFoundError(checkpoint)
        validate_resume(checkpoint)
        command = [sys.executable, "-m", "lerobot.scripts.lerobot_train",
                   f"--config_path={checkpoint}", "--resume=true"]
    else:
        command = [sys.executable, "-m", "lerobot.scripts.lerobot_train",
                   f"--config_path={ROOT / 'configs/xtrainer/train_pi05.yaml'}",
                   "--policy.input_features={}", "--policy.rtc_config=null"]
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

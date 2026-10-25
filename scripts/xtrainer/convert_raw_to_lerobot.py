"""Convert trusted X-Trainer pickle recordings to a local LeRobot v3 dataset."""
import argparse
import pickle
from pathlib import Path

import numpy as np
from PIL import Image

CAMERAS = {"top": "topImg", "left_wrist": "leftImg", "right_wrist": "rightImg"}
JOINT_NAMES = ([f"left_joint{i}.pos" for i in range(1, 7)] + ["left_gripper.pos"]
               + [f"right_joint{i}.pos" for i in range(1, 7)] + ["right_gripper.pos"])


def vector(value, label):
    array = np.asarray(value, dtype=np.float32)
    if array.shape != (14,) or not np.isfinite(array).all():
        raise ValueError(f"{label}: expected 14 finite values, got {array.shape}")
    if np.any(array[[6, 13]] < 0) or np.any(array[[6, 13]] > 1):
        raise ValueError(f"{label}: grippers at indices 6 and 13 must be in [0, 1]")
    return array


def read_frame(episode, observation, task):
    # Only load recordings from a trusted source: pickle can execute Python code.
    with observation.open("rb") as handle:
        raw = pickle.load(handle)
    frame = {"observation.state": vector(raw["joint_positions"], str(observation)),
             "action": vector(raw["control"], str(observation)), "task": task}
    for name, folder in CAMERAS.items():
        matches = [episode / folder / f"{observation.stem}{ext}" for ext in (".jpg", ".jpeg", ".png")]
        path = next((path for path in matches if path.is_file()), None)
        if path is None:
            raise FileNotFoundError(f"Missing {folder} image for {observation}")
        with Image.open(path) as image:
            frame[f"observation.images.{name}"] = np.asarray(image.convert("RGB")).copy()
    return frame


def convert(args):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    source, target = Path(args.raw_root).resolve(), Path(args.output).resolve()
    if not source.is_dir():
        raise NotADirectoryError(source)
    if target.exists():
        raise FileExistsError(f"Output must be a new directory: {target}")
    if args.fps <= 0 or not args.task.strip():
        raise ValueError("fps must be positive and task must be non-empty")
    episodes = []
    for episode in sorted(source.iterdir()):
        if not episode.is_dir():
            continue
        frames = sorted((episode / "observation").glob("*.pkl"),
                        key=lambda p: int(p.stem))
        if not frames:
            continue
        ids = [int(p.stem) for p in frames]
        if any(b != a + 1 for a, b in zip(ids, ids[1:])):
            raise ValueError(f"Missing observation frames in {episode}; cannot assume constant fps")
        episodes.append((episode, frames))
    if not episodes:
        raise ValueError("No episodes with observation/*.pkl found")
    first = read_frame(episodes[0][0], episodes[0][1][0], args.task)
    features = {key: {"dtype": "float32", "shape": (14,), "names": JOINT_NAMES}
                for key in ("action", "observation.state")}
    for name in CAMERAS:
        key = f"observation.images.{name}"
        features[key] = {"dtype": "image" if args.images else "video",
                         "shape": first[key].shape, "names": ["height", "width", "channels"]}
    dataset = LeRobotDataset.create(repo_id=args.repo_id, root=target, fps=args.fps,
                                     robot_type="xtrainer", features=features,
                                     use_videos=not args.images)
    try:
        for episode, frames in episodes:
            for observation in frames:
                frame = read_frame(episode, observation, args.task)
                for name in CAMERAS:
                    key = f"observation.images.{name}"
                    if frame[key].shape != features[key]["shape"]:
                        raise ValueError(f"Image resolution changed: {observation}, {name}")
                dataset.add_frame(frame)
            dataset.save_episode()
    finally:
        dataset.finalize()
    print(f"Converted {len(episodes)} episodes to {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repo-id", default="xtrainer/pi05")
    parser.add_argument("--task", required=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--images", action="store_true", help="Store images instead of encoded videos")
    convert(parser.parse_args())


if __name__ == "__main__":
    main()

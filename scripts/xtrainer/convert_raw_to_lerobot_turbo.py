#!/usr/bin/env python
"""Convert X-Trainer raw recordings to v3 using parallel reads and in-memory video encoding."""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.xtrainer.convert_raw_to_lerobot import CAMERAS, JOINT_NAMES, read_frame


def ordered_frames(pool, episode, observations, task, prefetch):
    """Bound decoded frames in memory while yielding the original numeric order."""
    observations = iter(observations)
    pending = deque()
    try:
        for _ in range(prefetch):
            path = next(observations, None)
            if path is None:
                break
            pending.append(pool.submit(read_frame, episode, path, task))
        while pending:
            yield pending.popleft().result()
            path = next(observations, None)
            if path is not None:
                pending.append(pool.submit(read_frame, episode, path, task))
    finally:
        for future in pending:
            future.cancel()


def convert(args):
    source, target = Path(args.raw_root).expanduser().resolve(), Path(args.output).expanduser().resolve()
    if not source.is_dir():
        raise NotADirectoryError(source)
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("Output must be separate from the raw source, not its parent or child")
    if target.exists():
        raise FileExistsError(f"Output must be a new directory: {target}")
    if min(args.fps, args.workers, args.prefetch, args.encoder_threads, args.encoder_queue_size) <= 0:
        raise ValueError("fps, workers, prefetch and encoder limits must be positive")
    if not args.task.strip() or not 0 <= args.crf <= 51:
        raise ValueError("task must be non-empty and crf must be between 0 and 51")
    episodes = []
    for episode in sorted(source.iterdir()):
        if not episode.is_dir():
            continue
        observations = sorted((episode / "observation").glob("*.pkl"), key=lambda p: int(p.stem))
        if not observations:
            continue
        ids = [int(path.stem) for path in observations]
        if any(b != a + 1 for a, b in zip(ids, ids[1:])):
            raise ValueError(f"Missing observation frames in {episode}; cannot assume constant fps")
        episodes.append((episode, observations))
    if not episodes:
        raise ValueError("No episodes with observation/*.pkl found")

    from lerobot.configs import RGBEncoderConfig
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".xtrainer-turbo-", dir=target.parent) as temporary:
        staging = Path(temporary) / "dataset"
        dataset = None
        features = None
        try:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for index, (episode, observations) in enumerate(episodes):
                    for frame in ordered_frames(pool, episode, observations, args.task, args.prefetch):
                        if dataset is None:
                            features = {key: {"dtype": "float32", "shape": (14,), "names": JOINT_NAMES}
                                        for key in ("action", "observation.state")}
                            features.update({f"observation.images.{name}": {
                                "dtype": "video", "shape": frame[f"observation.images.{name}"].shape,
                                "names": ["height", "width", "channels"]} for name in CAMERAS})
                            dataset = LeRobotDataset.create(
                                repo_id=args.repo_id, root=staging, fps=args.fps, robot_type="xtrainer",
                                features=features, use_videos=True, streaming_encoding=True,
                                rgb_encoder=RGBEncoderConfig(vcodec="libx264", crf=args.crf, preset=args.preset),
                                encoder_threads=args.encoder_threads, encoder_queue_maxsize=args.encoder_queue_size)
                        for name in CAMERAS:
                            key = f"observation.images.{name}"
                            if frame[key].shape != features[key]["shape"]:
                                raise ValueError(f"Image resolution changed: {episode}, {name}")
                        dataset.add_frame(frame)
                    dataset.save_episode()
                    print(f"[{index + 1}/{len(episodes)}] {episode.name}: {len(observations)} frames", flush=True)
        except BaseException:
            if dataset is not None:
                dataset.clear_episode_buffer()
            raise
        finally:
            if dataset is not None:
                dataset.finalize()
        staging.rename(target)
    print(f"Created LeRobot v3 dataset: {target}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repo-id", default="xtrainer/pi05")
    parser.add_argument("--task", required=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--workers", type=int, default=4, help="Parallel raw frame reader threads")
    parser.add_argument("--prefetch", type=int, default=16, help="Maximum pending decoded frames (three cameras each)")
    parser.add_argument("--encoder-threads", type=int, default=2)
    parser.add_argument("--encoder-queue-size", type=int, default=16)
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--preset", default="fast", choices=["ultrafast", "superfast", "veryfast", "faster",
                                                              "fast", "medium", "slow", "slower", "veryslow"])
    return parser.parse_args(argv)


if __name__ == "__main__":
    convert(parse_args())

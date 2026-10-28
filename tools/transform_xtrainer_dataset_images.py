#!/usr/bin/env python
"""Copy a video-backed X-Trainer LeRobot v3 dataset and rotate its right camera 180 degrees."""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

CAMERA_KEYS = tuple(f"observation.images.{name}" for name in ("top", "left_wrist", "right_wrist"))
MARKER = "xtrainer_camera_orientation.json"


def transform_frame(camera_key, image):
    if camera_key not in CAMERA_KEYS:
        raise KeyError(f"Unsupported camera key: {camera_key}")
    return np.ascontiguousarray(image[::-1, ::-1] if camera_key == CAMERA_KEYS[2] else image)


def _validate_source(root):
    info = json.loads((root / "meta/info.json").read_text(encoding="utf-8"))
    if info.get("codebase_version") != "v3.0":
        raise ValueError("Expected a LeRobot v3.0 dataset")
    if (root / "meta" / MARKER).exists():
        raise ValueError("This dataset has already been orientation-corrected; use the original dataset")
    if info.get("video_path") != "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4":
        raise ValueError("Expected the standard LeRobot v3 video_path layout")
    videos = {}
    for key in CAMERA_KEYS:
        if info.get("features", {}).get(key, {}).get("dtype") != "video":
            raise ValueError(f"{key} must be video-backed; --images datasets are not supported")
        videos[key] = sorted((root / "videos" / key).glob("chunk-*/file-*.mp4"))
        if not videos[key]:
            raise ValueError(f"No videos found for {key}")
    # Each camera can have different chunk boundaries in v3; do not pair file indices.
    return info, videos


def _timestamps(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
         "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(path)],
        check=True, capture_output=True, text=True)
    times = [float(frame["best_effort_timestamp_time"]) for frame in json.loads(result.stdout)["frames"]]
    if not times or not np.isfinite(times).all():
        raise ValueError(f"Video has no valid frame timestamps: {path}")
    return times


def _run_ffmpeg(source, destination, crf, preset):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-copyts", "-i", str(source),
         "-map", "0:v:0", "-vf", "vflip,hflip", "-fps_mode", "passthrough",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(crf), "-preset", preset,
         "-an", "-avoid_negative_ts", "disabled", "-movflags", "+faststart", str(destination)],
        check=True)
    before, after = _timestamps(source), _timestamps(destination)
    if len(before) != len(after) or not np.allclose(before, after, atol=1e-5, rtol=0):
        raise ValueError(f"Frame count/timestamps changed for {source}; refusing misaligned dataset")


def transform_dataset(source_root, output_root, *, crf=18, preset="medium", dry_run=False):
    source = Path(source_root).expanduser().resolve()
    output = Path(output_root).expanduser().resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("Output must be separate from source, not its parent or child")
    if output.exists():
        raise FileExistsError(f"Output must be a new directory: {output}")
    if not 0 <= crf <= 51:
        raise ValueError("crf must be between 0 and 51")
    info, videos = _validate_source(source)
    print("top=unchanged, left_wrist=unchanged, right_wrist=vflip+hflip (180 degrees)")
    print(f"Right-camera video files: {len(videos[CAMERA_KEYS[2]])}")
    if dry_run:
        return
    for executable in ("ffmpeg", "ffprobe"):
        if shutil.which(executable) is None:
            raise RuntimeError(f"Install {executable} and add it to PATH")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Publish only after all files pass the timing check; failed runs leave no output dataset.
    with tempfile.TemporaryDirectory(prefix=".xtrainer-orientation-", dir=output.parent) as temporary:
        staging = Path(temporary) / "dataset"
        shutil.copytree(source, staging)
        for video in videos[CAMERA_KEYS[2]]:
            _run_ffmpeg(video, staging / video.relative_to(source), crf, preset)
        video_info = info["features"][CAMERA_KEYS[2]].setdefault("info", {})
        video_info.update({"video.codec": "h264", "video.pix_fmt": "yuv420p", "has_audio": False})
        (staging / "meta/info.json").write_text(json.dumps(info, indent=4) + "\n", encoding="utf-8")
        (staging / "meta" / MARKER).write_text(json.dumps({
            "source": str(source), "transforms": {CAMERA_KEYS[2]: "vflip,hflip"},
            "crf": crf, "preset": preset,
        }, indent=4) + "\n", encoding="utf-8")
        staging.rename(output)
    print(f"Created corrected dataset: {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    transform_dataset(args.input_root, args.output_root, crf=args.crf, preset=args.preset, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

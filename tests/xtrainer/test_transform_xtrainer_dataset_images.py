import json
from pathlib import Path

import numpy as np
import pytest

from tools import transform_xtrainer_dataset_images as transform


def source_dataset(root):
    (root / "meta").mkdir(parents=True)
    info = {"codebase_version": "v3.0",
            "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
            "features": {key: {"dtype": "video", "info": {"video.codec": "av1"}}
                         for key in transform.CAMERA_KEYS}}
    (root / "meta/info.json").write_text(json.dumps(info))
    (root / "meta/stats.json").write_text('{"unchanged": true}')
    for index, key in enumerate(transform.CAMERA_KEYS):
        # Different file counts per camera are valid in v3.
        folder = root / "videos" / key / "chunk-000"
        folder.mkdir(parents=True)
        for number in range(index + 1):
            (folder / f"file-{number:03d}.mp4").write_bytes(b"original")
    return info


@pytest.mark.parametrize("index", [0, 1, 2])
def test_orientation(index):
    image = np.arange(18).reshape(2, 3, 3)
    result = transform.transform_frame(transform.CAMERA_KEYS[index], image)
    np.testing.assert_array_equal(result, image[::-1, ::-1] if index == 2 else image)
    assert result.flags.c_contiguous


def test_copy_and_metadata(tmp_path, monkeypatch):
    source, output = tmp_path / "source", tmp_path / "corrected"
    source_dataset(source)
    monkeypatch.setattr(transform.shutil, "which", lambda _: "available")
    calls = []

    def convert(src, dst, crf, preset):
        calls.append(src)
        dst.write_bytes(b"rotated")

    monkeypatch.setattr(transform, "_run_ffmpeg", convert)
    transform.transform_dataset(source, output)
    assert len(calls) == 3
    for video in source.glob("videos/*/chunk-*/*.mp4"):
        assert video.read_bytes() == b"original"
        expected = b"rotated" if transform.CAMERA_KEYS[2] in video.parts else b"original"
        assert (output / video.relative_to(source)).read_bytes() == expected
    assert (output / "meta/stats.json").read_bytes() == (source / "meta/stats.json").read_bytes()
    info = json.loads((output / "meta/info.json").read_text())
    assert info["features"][transform.CAMERA_KEYS[2]]["info"]["video.codec"] == "h264"
    with pytest.raises(ValueError, match="already"):
        transform.transform_dataset(output, tmp_path / "twice")


def test_dry_run_and_failure_leave_no_output(tmp_path, monkeypatch):
    source, output = tmp_path / "source", tmp_path / "corrected"
    source_dataset(source)
    transform.transform_dataset(source, output, dry_run=True)
    assert not output.exists()
    monkeypatch.setattr(transform.shutil, "which", lambda _: "available")

    def fail(*args):
        raise RuntimeError("encoding failed")

    monkeypatch.setattr(transform, "_run_ffmpeg", fail)
    with pytest.raises(RuntimeError, match="encoding failed"):
        transform.transform_dataset(source, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".xtrainer-orientation-*"))


def test_reject_wrong_layout_and_unsafe_output(tmp_path):
    source = tmp_path / "source"
    info = source_dataset(source)
    for output in (source, source / "child", tmp_path):
        with pytest.raises(ValueError, match="separate"):
            transform.transform_dataset(source, output)
    info["codebase_version"] = "v2.1"
    (source / "meta/info.json").write_text(json.dumps(info))
    with pytest.raises(ValueError, match="v3.0"):
        transform.transform_dataset(source, tmp_path / "output")


@pytest.mark.parametrize("after", [[0.0], [0.0, 0.2]])
def test_timestamp_or_frame_loss_rejected(monkeypatch, after):
    calls = []
    monkeypatch.setattr(transform.subprocess, "run", lambda command, **kwargs: calls.append(command))
    monkeypatch.setattr(transform, "_timestamps", lambda path: [0.0, 0.1] if path == Path("in") else after)
    with pytest.raises(ValueError, match="Frame count/timestamps changed"):
        transform._run_ffmpeg(Path("in"), Path("out"), 18, "medium")
    assert "vflip,hflip" in calls[0]
    assert "passthrough" in calls[0]

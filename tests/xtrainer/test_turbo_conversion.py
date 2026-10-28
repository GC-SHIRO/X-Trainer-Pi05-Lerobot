import pickle
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from scripts.xtrainer import convert_raw_to_lerobot_turbo as turbo


def recording(root):
    for episode in ("episode_b", "episode_a"):
        path = root / episode
        (path / "observation").mkdir(parents=True)
        for camera in turbo.CAMERAS.values():
            (path / camera).mkdir()
        for frame in (10, 9, 11):
            state = np.full(14, frame / 20, dtype=np.float32)
            with (path / "observation" / f"{frame}.pkl").open("wb") as file:
                pickle.dump({"joint_positions": state, "control": state}, file)
            for camera in turbo.CAMERAS.values():
                Image.new("RGB", (10, 8), (frame, 0, 0)).save(path / camera / f"{frame}.png")


def test_streaming_output_and_order(tmp_path, monkeypatch):
    source, output = tmp_path / "raw", tmp_path / "v3"
    recording(source)
    frames, events = [], []
    def create(**kwargs):
        assert kwargs["streaming_encoding"] is True
        assert kwargs["encoder_threads"] == 2
        assert kwargs["features"]["action"]["names"] == turbo.JOINT_NAMES
        assert kwargs["features"]["observation.images.top"]["shape"] == (8, 10, 3)
        kwargs["root"].mkdir()
        return SimpleNamespace(add_frame=frames.append, save_episode=lambda: events.append("save"),
                               finalize=lambda: events.append("finalize"), clear_episode_buffer=lambda: None)
    module = ModuleType("lerobot.datasets.lerobot_dataset")
    module.LeRobotDataset = SimpleNamespace(create=create)
    config = ModuleType("lerobot.configs")
    config.RGBEncoderConfig = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "lerobot.datasets.lerobot_dataset", module)
    monkeypatch.setitem(sys.modules, "lerobot.configs", config)
    args = turbo.parse_args(["--raw-root", str(source), "--output", str(output), "--task", "pick",
                             "--workers", "3", "--prefetch", "2"])
    turbo.convert(args)
    assert output.is_dir()
    assert events == ["save", "save", "finalize"]
    assert [int(frame["observation.images.top"][0, 0, 0]) for frame in frames] == [9, 10, 11] * 2
    assert all(frame["task"] == "pick" for frame in frames)
    assert not list(tmp_path.glob(".xtrainer-turbo-*"))


def test_missing_frame_rejected_before_output(tmp_path):
    source, output = tmp_path / "raw", tmp_path / "v3"
    recording(source)
    (source / "episode_a/observation/10.pkl").unlink()
    args = turbo.parse_args(["--raw-root", str(source), "--output", str(output), "--task", "pick"])
    with pytest.raises(ValueError, match="Missing observation"):
        turbo.convert(args)
    assert not output.exists()

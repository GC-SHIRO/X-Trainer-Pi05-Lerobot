"""X-Trainer Pi05 integration contracts; no GPU or hardware required."""
import argparse
import asyncio
import json
import pickle
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from deploy.xtrainer.pi05_policy import CAMERAS, PI05XTrainerPolicy
from deploy.xtrainer.websocket_client_policy import XTrainerWebSocketPolicyClient
from deploy.xtrainer.websocket_policy_server import XTrainerWebSocketPolicyServer
from scripts.xtrainer import convert_raw_to_lerobot as convert
from scripts.xtrainer.run_real import _validate_server_metadata
from scripts.xtrainer.serve_mock_policy import HoldCurrentMockPolicy
from scripts.xtrainer.train_pi05 import build_command


def payload():
    return {"state": np.zeros(14, dtype=np.float32), "task": "pick up the object",
            "images": {name: np.zeros((8, 10, 3), dtype=np.uint8) for name in CAMERAS}}


def config():
    return SimpleNamespace(chunk_size=50,
        input_features={"observation.state": SimpleNamespace(shape=(14,))},
        output_features={"action": SimpleNamespace(shape=(14,))},
        image_features={f"observation.images.{name}": None for name in CAMERAS},
        use_visual_memory=False, use_proprioceptive_memory=False, rtc_config=None)


def test_checkpoint_contract():
    cfg = config()
    PI05XTrainerPolicy.validate_config(cfg, 32)
    for count in (0, -1, 51):
        with pytest.raises(ValueError):
            PI05XTrainerPolicy.validate_config(cfg, count)
    cfg.use_visual_memory = True
    with pytest.raises(ValueError):
        PI05XTrainerPolicy.validate_config(cfg, 32)
    cfg.use_visual_memory = False
    cfg.output_features["action"].shape = (32,)
    with pytest.raises(ValueError):
        PI05XTrainerPolicy.validate_config(cfg, 32)


@pytest.mark.parametrize("field,value", [("state", np.zeros(13)), ("state", np.full(14, np.nan)),
                                        ("task", ""), ("images", {})])
def test_reject_bad_observations(field, value):
    observation = payload()
    observation[field] = value
    with pytest.raises(ValueError):
        PI05XTrainerPolicy.validate_payload(observation)


def test_adapter_preprocess_predict_postprocess():
    import torch
    adapter = PI05XTrainerPolicy.__new__(PI05XTrainerPolicy)
    adapter.actions_per_chunk = 5
    def preprocess(batch):
        assert batch["observation.images.top"].shape == (3, 8, 10)
        assert batch["observation.images.top"].max() == 1
        assert batch["observation.state"].shape == (14,)
        return batch
    adapter.preprocessor = preprocess
    adapter.postprocessor = lambda actions: actions * 2 + 1
    adapter.policy = SimpleNamespace(predict_action_chunk=lambda _: torch.ones(1, 50, 14))
    observation = payload()
    observation["images"]["top"].fill(255)
    result = adapter.infer(observation)["action"]
    assert result.shape == (5, 14)
    np.testing.assert_array_equal(result, np.full((5, 14), 3))
    adapter.policy.predict_action_chunk = lambda _: torch.full((1, 50, 14), float("nan"))
    with pytest.raises(ValueError):
        adapter.infer(observation)


def test_mock_server_roundtrip():
    async def run():
        server = XTrainerWebSocketPolicyServer(HoldCurrentMockPolicy(chunk_size=5), port=0)
        await server.start()
        client = XTrainerWebSocketPolicyClient(f"http://127.0.0.1:{server.port}")
        try:
            metadata = await client.connect()
            assert _validate_server_metadata(metadata)["model_type"] == "pi05"
            await client.reset()
            result = await client.infer(payload())
            np.testing.assert_array_equal(result["action"], np.zeros((5, 14)))
            metadata["policy"]["model_type"] = "xvla"
            with pytest.raises(RuntimeError):
                _validate_server_metadata(metadata)
        finally:
            await client.close()
            await server.stop()
    asyncio.run(run())


def test_launcher(tmp_path):
    meta = tmp_path / "meta"
    meta.mkdir()
    features = {key: {"shape": [14]} for key in ("action", "observation.state")}
    features.update({f"observation.images.{name}": {} for name in CAMERAS})
    (meta / "info.json").write_text(json.dumps({"codebase_version": "v3.0", "features": features}))
    (meta / "stats.json").write_text(json.dumps({key: {"q01": [0]*14, "q99": [1]*14}
                                               for key in ("action", "observation.state")}))
    args = argparse.Namespace(dataset_root=str(tmp_path), repo_id="xtrainer/pi05",
        resume=None, policy_path="local/base", steps=2, batch_size=1, device="cpu", output_dir=None)
    cmd = build_command(args)
    assert "--policy.input_features={}" in cmd
    assert "--policy.path=local/base" in cmd
    assert "--steps=2" in cmd
    (meta / "stats.json").write_text("{}")
    with pytest.raises(ValueError, match="normalization"):
        build_command(args)


def test_raw_conversion_contract(tmp_path, monkeypatch):
    episode = tmp_path / "raw" / "episode1"
    (episode / "observation").mkdir(parents=True)
    state = np.zeros(14, dtype=np.float32)
    for index in range(2):
        with (episode / "observation" / f"{index}.pkl").open("wb") as handle:
            pickle.dump({"joint_positions": state, "control": state + 0.1}, handle)
        for folder in convert.CAMERAS.values():
            (episode / folder).mkdir(exist_ok=True)
            Image.new("RGB", (10, 8), (255, 0, 0)).save(episode / folder / f"{index}.png")
    frames, saved = [], []
    writer = SimpleNamespace(add_frame=frames.append, save_episode=lambda: saved.append(True),
                             finalize=lambda: saved.append("finalized"))
    def create(**kwargs):
        assert kwargs["features"]["action"]["shape"] == (14,)
        assert kwargs["features"]["observation.images.top"]["shape"] == (8, 10, 3)
        assert kwargs["features"]["action"]["names"][6] == "left_gripper.pos"
        return writer
    module = ModuleType("lerobot.datasets.lerobot_dataset")
    module.LeRobotDataset = SimpleNamespace(create=create)
    monkeypatch.setitem(sys.modules, "lerobot.datasets.lerobot_dataset", module)
    args = argparse.Namespace(raw_root=str(tmp_path / "raw"), output=str(tmp_path / "out"),
        task="pick", repo_id="xtrainer/pi05", fps=30, images=True)
    convert.convert(args)
    assert len(frames) == 2 and saved == [True, "finalized"]
    np.testing.assert_array_equal(frames[0]["observation.images.top"][0, 0], [255, 0, 0])
    np.testing.assert_allclose(frames[0]["action"], 0.1)
    (episode / "observation" / "1.pkl").rename(episode / "observation" / "2.pkl")
    with pytest.raises(ValueError, match="Missing observation"):
        convert.convert(args)

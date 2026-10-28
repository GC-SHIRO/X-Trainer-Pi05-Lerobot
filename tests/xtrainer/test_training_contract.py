"""Check X-Trainer metadata before spending time on GPU training."""
import copy
import json

import pytest

from scripts.xtrainer.train_pi05 import CAMERA_KEYS, JOINT_NAMES, validate_dataset, validate_resume


def dataset():
    features = {key: {"shape": [14], "dtype": "float32", "names": list(JOINT_NAMES)}
                for key in ("action", "observation.state")}
    features.update({key: {"dtype": "video", "shape": [480, 640, 3]} for key in CAMERA_KEYS})
    stats = {key: {"q01": [-1.0] * 14, "q99": [1.0] * 14}
             for key in ("action", "observation.state")}
    return {"features": features}, stats


def test_valid_dataset():
    validate_dataset(*dataset())


@pytest.mark.parametrize("problem", ["old_camera", "extra_camera", "channels", "dimension",
                                     "joint_order", "stats_length", "nan", "quantile_order"])
def test_bad_dataset(problem):
    info, stats = dataset()
    features = info["features"]
    if problem == "old_camera":
        features["observation.images.base_0_rgb"] = features.pop("observation.images.top")
    elif problem == "extra_camera":
        features["observation.images.extra"] = features["observation.images.top"]
    elif problem == "channels":
        features["observation.images.top"]["shape"] = [3, 480, 640]
    elif problem == "dimension":
        features["action"]["shape"] = [32]
    elif problem == "joint_order":
        features["observation.state"]["names"].reverse()
    elif problem == "stats_length":
        stats["action"]["q01"] = [0.0] * 32
    elif problem == "nan":
        stats["action"]["q01"][0] = float("nan")
    elif problem == "quantile_order":
        stats["action"]["q01"][0] = 2.0
    with pytest.raises(ValueError):
        validate_dataset(info, stats)


def test_resume_contract(tmp_path):
    features = {key: {"shape": [3, 480, 640]} for key in CAMERA_KEYS}
    features["observation.state"] = {"shape": [14]}
    cfg = {"policy": {"type": "pi05", "input_features": features,
                      "output_features": {"action": {"shape": [14]}},
                      "action_feature_names": JOINT_NAMES}}
    path = tmp_path / "train_config.json"
    path.write_text(json.dumps(cfg))
    validate_resume(path)
    for field, value in [("use_relative_actions", True), ("use_visual_memory", True),
                         ("use_proprioceptive_memory", True), ("empty_cameras", 1),
                         ("rtc_config", {"enabled": True}), ("n_obs_steps", 2),
                         ("action_feature_names", list(reversed(JOINT_NAMES)))]:
        invalid = copy.deepcopy(cfg)
        invalid["policy"][field] = value
        path.write_text(json.dumps(invalid))
        with pytest.raises(ValueError):
            validate_resume(path)

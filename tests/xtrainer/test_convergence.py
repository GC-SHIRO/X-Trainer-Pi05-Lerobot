"""Offline checks for the first deployment migration stage."""
import importlib.util
from pathlib import Path
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("compare_smoothing", ROOT / "scripts/xtrainer/compare_smoothing.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_smoothing_preserves_endpoints_and_grippers():
    actions = np.zeros((7,14))
    actions[1:-1:2,:] = 1
    result = module.smooth_chunk(actions)
    np.testing.assert_array_equal(result[[0,-1]],actions[[0,-1]])
    np.testing.assert_array_equal(result[:,[6,13]],actions[:,[6,13]])
    assert np.max(np.abs(np.diff(result[:,0]))) < np.max(np.abs(np.diff(actions[:,0])))


def test_standard_adapter_readonly_and_explicit_feature_order(tmp_path):
    pytest.importorskip("draccus")
    pytest.importorskip("torch")
    from types import SimpleNamespace
    from lerobot.robots.xtrainer import XTrainer, XTrainerConfig
    from lerobot.robots.xtrainer.xtrainer import JOINT_NAMES
    calls = []
    env = SimpleNamespace(reset=lambda: calls.append("connect"), close=lambda: calls.append("close"),
        enable_arms=lambda: calls.append("enable"), cameras={},
        apply_action=lambda values,pace: values.copy())
    robot = XTrainer(XTrainerConfig(calibration_dir=tmp_path),environment=env)
    robot.connect()
    assert calls == ["connect"]
    with pytest.raises(RuntimeError,match="execute"):
        robot.send_action(dict.fromkeys(JOINT_NAMES,0))
    robot.config.execute = True
    action = {name:i/20 for i,name in reversed(list(enumerate(JOINT_NAMES)))}
    applied = robot.send_action(action)
    assert list(applied) == list(JOINT_NAMES)
    assert applied == action
    assert calls == ["connect","enable"]
    robot.disconnect()
    assert not robot.is_connected


def test_pi05_chunk_contract_accepts_its_own_resize_and_padding():
    pytest.importorskip("torch")
    from types import SimpleNamespace
    from lerobot.configs.types import FeatureType, PolicyFeature
    from lerobot.policies.chunk import FeatureSpec
    from lerobot.policies.pi05.modeling_pi05 import PI05Policy
    policy = object.__new__(PI05Policy)
    config = SimpleNamespace(
        input_features={"observation.images.top": PolicyFeature(FeatureType.VISUAL,(3,224,224)),
                        "observation.state": PolicyFeature(FeatureType.STATE,(32,))},
        image_features={"observation.images.top":None}, max_state_dim=32)
    object.__setattr__(policy,"config",config)
    rgb = FeatureSpec("observation.images.top",(480,640,3),"uint8",kind="rgb",semantics="rgb")
    state = FeatureSpec("observation.state",(14,),"float32",semantics="rad")
    policy.validate_chunk_input_features((rgb,state))
    with pytest.raises(ValueError):
        policy.validate_chunk_input_features((rgb,FeatureSpec("observation.state",(33,),"float32",semantics="rad")))
    with pytest.raises(ValueError):
        policy.validate_chunk_input_features((state,))

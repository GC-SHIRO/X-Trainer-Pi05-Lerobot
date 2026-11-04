"""Offline real-checkpoint comparison; never connects to robot hardware."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import numpy as np
import torch
from deploy.xtrainer.pi05_policy import PI05XTrainerPolicy
from lerobot.inference import PolicyRunner, FeatureSpec, ObservationSnapshot
from lerobot.robots.xtrainer.xtrainer import JOINT_NAMES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(4)
    legacy = PI05XTrainerPolicy(args.checkpoint, "cuda", 50, rtc={"enabled":False})
    # Both paths share weights, but never share mutable processor state.
    pre, post = deepcopy((legacy.preprocessor,legacy.postprocessor))
    from lerobot.processor import RenameObservationsProcessorStep
    for step in pre.steps:
        if isinstance(step, RenameObservationsProcessorStep):
            if any(key != value for key,value in step.rename_map.items()):
                raise ValueError("Non-identity checkpoint rename_map requires explicit feature mapping")
            step.rename_map = {}
    semantics = "xtrainer:absolute_joint_rad;gripper_0_closed_1_open:v1"
    features = (FeatureSpec("observation.state", (14,), "float32", names=JOINT_NAMES, semantics=semantics),) + tuple(
        FeatureSpec("observation.images."+name,(480,640,3),"uint8",kind="rgb",semantics="rgb_legacy_training_transform_v1")
        for name in ("top","left_wrist","right_wrist"))
    runner = PolicyRunner(legacy.policy, pre, post, action_interval=1/33, features=features,
        action_feature=FeatureSpec("action",(14,),"float32",names=JOINT_NAMES,semantics=semantics),robot_type="xtrainer")
    rng = np.random.default_rng(42)
    state = np.asarray(legacy.metadata()["reset_pose"],dtype=np.float32)
    images = {name:rng.integers(0,256,(480,640,3),dtype=np.uint8) for name in ("top","left_wrist","right_wrist")}
    payload = {"state":state,"task":"pick up the box","images":images}
    snapshot = ObservationSnapshot({"observation.state":state,**{"observation.images."+k:v for k,v in images.items()}},0.0,payload["task"])
    torch.manual_seed(123)
    old = legacy.infer(payload)["action"]
    runner.reset()
    torch.manual_seed(123)
    new = runner.predict(snapshot).canonical_actions.numpy()
    delta = np.abs(old-new)
    report = {"shape":list(new.shape),"finite":bool(np.isfinite(new).all()),
        "max_abs_difference":float(delta.max()),"mean_abs_difference":float(delta.mean()),
        "allclose_atol_1e-5":bool(np.allclose(old,new,rtol=1e-5,atol=1e-5)),
        "observation":"synthetic RGB and reset state; not physical robot validation"}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
    if not report["allclose_atol_1e-5"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

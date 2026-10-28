"""Pi05 adapter for the X-Trainer WebSocket protocol."""
from pathlib import Path
import numpy as np

from deploy.xtrainer.real.constants import XTRAINER_RESET_POSE

CAMERAS = ("top", "left_wrist", "right_wrist")


class PI05XTrainerPolicy:
    """Load a fine-tuned 14-joint checkpoint and its saved normalization pipeline."""

    def __init__(self, checkpoint, device="cuda", actions_per_chunk=50):
        import torch
        from lerobot.policies import PI05Config, make_pre_post_processors
        from lerobot.policies.pi05.modeling_pi05 import PI05Policy

        path = Path(checkpoint).resolve()
        for filename in ("config.json", "model.safetensors",
                         "policy_preprocessor.json", "policy_postprocessor.json"):
            if not (path / filename).is_file():
                raise FileNotFoundError(f"Deploy a complete fine-tuned checkpoint: missing {path / filename}")
        if (path / "adapter_config.json").exists():
            raise ValueError("Merge adapter weights into a complete checkpoint before deployment")
        config = PI05Config.from_pretrained(path)
        if config.type != "pi05":
            raise ValueError("Expected a Pi05 checkpoint")
        self.validate_config(config, actions_per_chunk)
        if str(device).startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but unavailable")
        config.device = device
        config.compile_model = False
        self.policy = PI05Policy.from_pretrained(path, config=config).eval()
        self.preprocessor, self.postprocessor = make_pre_post_processors(
            policy_cfg=config, pretrained_path=path,
            preprocessor_overrides={"device_processor": {"device": device}},
        )
        self.actions_per_chunk = actions_per_chunk

    @staticmethod
    def validate_config(config, count):
        if not 0 < count <= config.chunk_size:
            raise ValueError("actions_per_chunk must be between 1 and checkpoint chunk_size")
        # Pi05 pads state to max_state_dim internally, so the saved config may report 32 instead of 14.
        if tuple(config.input_features["observation.state"].shape) not in {(14,), (config.max_state_dim,)}:
            raise ValueError("Checkpoint state must have 14 dimensions (or max_state_dim when padded)")
        if tuple(config.output_features["action"].shape) != (14,):
            raise ValueError("Checkpoint action must have 14 dimensions")
        expected = {f"observation.images.{name}" for name in CAMERAS}
        if set(config.image_features) != expected:
            raise ValueError(f"Checkpoint must use camera keys {sorted(expected)}")
        if config.use_visual_memory or config.use_proprioceptive_memory:
            raise ValueError("This deployment adapter accepts single-frame Pi05 checkpoints only")
        if config.rtc_config is not None and config.rtc_config.enabled:
            raise ValueError("This synchronous adapter requires RTC to be disabled")

    def metadata(self):
        return {"model_type": "pi05", "schema_version": 1, "action_dim": 14,
                "state_dim": 14, "chunk_size": self.actions_per_chunk,
                "reset_pose": list(XTRAINER_RESET_POSE)}

    def reset(self):
        self.policy.reset()
        for processor in (self.preprocessor, self.postprocessor):
            reset = getattr(processor, "reset", None)
            if callable(reset):
                reset()

    @staticmethod
    def validate_payload(payload):
        state = np.asarray(payload.get("state"), dtype=np.float32)
        if state.shape != (14,) or not np.isfinite(state).all():
            raise ValueError("state must contain 14 finite values")
        if not isinstance(payload.get("task"), str) or not payload["task"].strip():
            raise ValueError("task must be a non-empty string")
        images = payload.get("images")
        if not isinstance(images, dict):
            raise ValueError("images must be a map")
        for name in CAMERAS:
            image = np.asarray(images.get(name))
            if image.dtype != np.uint8 or image.ndim != 3 or image.shape[-1] != 3 or min(image.shape) < 1:
                raise ValueError(f"{name} must be a nonempty HWC uint8 RGB image")
        return state

    def infer(self, payload):
        import torch
        state = self.validate_payload(payload)
        batch = {"observation.state": torch.from_numpy(state), "task": payload["task"]}
        for name in CAMERAS:
            image = np.asarray(payload["images"][name]).copy()
            batch[f"observation.images.{name}"] = torch.from_numpy(image).permute(2, 0, 1).float() / 255
        with torch.inference_mode():
            actions = self.policy.predict_action_chunk(self.preprocessor(batch))
            actions = self.postprocessor(actions).detach().float().cpu().numpy()
        if actions.ndim != 3 or actions.shape[0] != 1 or actions.shape[2] != 14:
            raise ValueError(f"Unexpected model action shape: {actions.shape}")
        actions = actions[0, :self.actions_per_chunk]
        if actions.shape != (self.actions_per_chunk, 14) or not np.isfinite(actions).all():
            raise ValueError("Model returned an incomplete or non-finite action chunk")
        return {"action": actions}

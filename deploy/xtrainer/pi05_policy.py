"""Pi05 adapter for the X-Trainer WebSocket protocol."""
from pathlib import Path
import logging
import time
import numpy as np

from deploy.xtrainer.real.constants import XTRAINER_RESET_POSE

CAMERAS = ("top", "left_wrist", "right_wrist")


class PI05XTrainerPolicy:
    """Load a fine-tuned 14-joint checkpoint and its saved normalization pipeline."""

    def __init__(self, checkpoint, device="cuda", actions_per_chunk=50, rtc=None):
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
        self.rtc_enabled = bool(rtc and rtc.get("enabled"))
        if self.rtc_enabled:
            from lerobot.policies.rtc.configuration_rtc import RTCConfig
            if rtc.get("mode", "guided") != "guided":
                raise ValueError("X-Trainer currently supports guided RTC only")
            config.rtc_config = RTCConfig(**rtc)
            if actions_per_chunk != config.chunk_size:
                raise ValueError("RTC requires the full checkpoint chunk_size")
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
                "rtc_enabled": getattr(self, "rtc_enabled", False), "state_dim": 14, "chunk_size": self.actions_per_chunk,
                "reset_pose": list(XTRAINER_RESET_POSE)}

    def reset(self):
        self.policy.reset()
        for processor in (self.preprocessor, self.postprocessor):
            reset = getattr(processor, "reset", None)
            if callable(reset):
                reset()

    def warmup(self):
        """Initialize ordinary and guided inference on the serving thread."""
        import torch

        device = torch.device(self.policy.config.device)
        cuda_devices = [device.index if device.index is not None else torch.cuda.current_device()] if device.type == "cuda" else []
        height, width = self.policy.config.image_resolution
        payload = {
            "state": np.asarray(XTRAINER_RESET_POSE, dtype=np.float32),
            "task": "Warm up the policy.",
            "images": {name: np.zeros((height, width, 3), dtype=np.uint8) for name in CAMERAS},
        }
        logger = logging.getLogger(__name__)
        started = time.perf_counter()
        logger.info("Policy warmup starting on %s (RTC=%s)", device, self.rtc_enabled)
        # Startup sampling must not change the random sequence for real requests.
        with torch.random.fork_rng(devices=cuda_devices):
            try:
                self.reset()
                result = self.infer(payload)
                if self.rtc_enabled:
                    payload.update(prev_chunk_left_over=result["model_action"], inference_delay=1)
                    self.infer(payload)
                if device.type == "cuda":
                    torch.cuda.synchronize(device)
            finally:
                self.reset()
        logger.info("Policy warmup complete in %.1f ms", (time.perf_counter() - started) * 1000)

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
        kwargs = {}
        if getattr(self, "rtc_enabled", False):
            previous = payload.get("prev_chunk_left_over")
            delay = payload.get("inference_delay", 0)
            if type(delay) is not int or delay < 0:
                raise ValueError("inference_delay must be a nonnegative integer")
            if previous is not None:
                previous = np.asarray(previous, dtype=np.float32)
                if previous.ndim != 2 or previous.shape[1] != 14 or not 0 < len(previous) <= self.actions_per_chunk or not np.isfinite(previous).all() or delay >= len(previous):
                    raise ValueError("Invalid RTC prefix or insufficient delay coverage")
                previous = torch.from_numpy(previous).to(self.policy.config.device).unsqueeze(0)
            kwargs = dict(prev_chunk_left_over=previous, inference_delay=delay)
        with torch.no_grad():
            actions = self.policy.predict_action_chunk(self.preprocessor(batch), **kwargs)
            model_actions = actions.detach().float().cpu().numpy().copy()
            actions = self.postprocessor(actions).detach().float().cpu().numpy()
        if actions.ndim != 3 or actions.shape[0] != 1 or actions.shape[2] != 14:
            raise ValueError(f"Unexpected model action shape: {actions.shape}")
        actions = actions[0, :self.actions_per_chunk]
        if actions.shape != (self.actions_per_chunk, 14) or not np.isfinite(actions).all():
            raise ValueError("Model returned an incomplete or non-finite action chunk")
        result = {"action": actions}
        if getattr(self, "rtc_enabled", False):
            result["model_action"] = model_actions[0, :self.actions_per_chunk]
        return result

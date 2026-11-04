"""Standard Robot adapter; hardware transport is shared with legacy deployment."""
import numpy as np
from ..robot import Robot
from .config_xtrainer import XTrainerConfig

JOINT_NAMES = tuple(
    [f"left_joint{i}.pos" for i in range(1, 7)] + ["left_gripper.pos"]
    + [f"right_joint{i}.pos" for i in range(1, 7)] + ["right_gripper.pos"]
)
CAMERA_NAMES = ("top", "left_wrist", "right_wrist")


class XTrainer(Robot):
    config_class = XTrainerConfig
    name = "xtrainer"
    supports_position_hold = True

    def __init__(self, config: XTrainerConfig, *, environment=None):
        super().__init__(config)
        self.config = config
        self._environment = environment
        self._connected = False
        self._motion_enabled = False

    @property
    def observation_features(self):
        return {**self.action_features, **{
            name: (self.config.height, self.config.width, 3) for name in CAMERA_NAMES
        }}

    @property
    def action_features(self):
        # Insertion order is the training dataset's 14-vector order.
        return dict.fromkeys(JOINT_NAMES, float)

    @property
    def cameras(self):
        return {} if self._environment is None else self._environment.cameras

    @property
    def is_connected(self):
        return self._connected

    @property
    def is_calibrated(self):
        # Dobot controller calibration and gripper ranges are provided externally.
        return True

    def calibrate(self):
        pass

    def configure(self):
        pass

    def _build_environment(self):
        from deploy.xtrainer.real.environment import XTrainerRealEnvironment, XTrainerSafetyConfig
        from deploy.xtrainer.real.hardware.dobot_xtrainer import XTrainerDobotArm
        from deploy.xtrainer.real.hardware.feetech import XTrainerFeetechGripper, XTrainerFeetechGripperConfig
        from deploy.xtrainer.real.hardware.realsense_camera import build_xtrainer_cameras
        c = self.config
        return XTrainerRealEnvironment(
            left_arm=XTrainerDobotArm.from_parts(ip=c.left_robot_ip, control_hz=c.control_hz),
            right_arm=XTrainerDobotArm.from_parts(ip=c.right_robot_ip, control_hz=c.control_hz),
            left_gripper=XTrainerFeetechGripper(XTrainerFeetechGripperConfig(c.left_gripper_port, c.left_gripper_id)),
            right_gripper=XTrainerFeetechGripper(XTrainerFeetechGripperConfig(c.right_gripper_port, c.right_gripper_id)),
            cameras=build_xtrainer_cameras(top_serial=c.top_serial, left_wrist_serial=c.left_wrist_serial,
                right_wrist_serial=c.right_wrist_serial, width=c.width, height=c.height, fps=c.camera_fps),
            task="", control_hz=c.control_hz,
            safety=XTrainerSafetyConfig(max_joint_delta_rad=c.max_joint_delta_rad),
        )

    def connect(self, calibrate=True):
        if self._connected:
            raise RuntimeError("X-Trainer already connected")
        if self._environment is None:
            self._environment = self._build_environment()
        try:
            self._environment.reset()
            self.configure()
        except BaseException:
            self._environment.close()
            raise
        self._connected = True

    def get_observation(self):
        if not self.is_connected:
            raise RuntimeError("X-Trainer is not connected")
        raw = self._environment.get_observation()
        state = np.asarray(raw["observation.state"])
        if state.shape != (14,) or not np.isfinite(state).all():
            raise ValueError("Expected finite 14-D X-Trainer state")
        result = {name: float(state[i]) for i, name in enumerate(JOINT_NAMES)}
        for name in CAMERA_NAMES:
            image = raw[f"observation.images.{name}"]
            if name == "top":
                # Same crop, resize and 180-degree flip as the legacy policy payload.
                import cv2
                h, w = image.shape[:2]
                top, left = min(int(.2 * h), h - 1), min(int(.2 * w), w - 1)
                bottom, right = min(int(.2 * h), h - top - 1), min(int(.2 * w), w - left - 1)
                image = cv2.resize(image[top:h-bottom, left:w-right], (w, h))[::-1, ::-1]
            result[name] = np.ascontiguousarray(image)
        return result

    def send_action(self, action):
        if not self.is_connected:
            raise RuntimeError("X-Trainer is not connected")
        if not self.config.execute:
            raise RuntimeError("Motion requires robot.execute=true")
        if set(action) != set(JOINT_NAMES):
            raise ValueError("Action keys must exactly match the 14 X-Trainer joint/gripper names")
        target = np.asarray([action[name] for name in JOINT_NAMES], dtype=np.float64)
        if not np.isfinite(target).all():
            raise ValueError("Action contains non-finite values")
        if not self._motion_enabled:
            self._environment.enable_arms()
            self._motion_enabled = True
        applied = self._environment.apply_action(target, pace=False)
        return {name: float(applied[i]) for i, name in enumerate(JOINT_NAMES)}

    def disconnect(self):
        try:
            if self._environment is not None:
                self._environment.close()
        finally:
            self._connected = self._motion_enabled = False

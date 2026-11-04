"""X-Trainer hardware configuration for the standard rollout engine."""
from dataclasses import dataclass
import math
from ..config import RobotConfig


@RobotConfig.register_subclass("xtrainer")
@dataclass
class XTrainerConfig(RobotConfig):
    left_robot_ip: str = "192.168.5.1"
    right_robot_ip: str = "192.168.5.2"
    left_gripper_port: str = "/dev/ttyUSB1"
    right_gripper_port: str = "/dev/ttyUSB0"
    left_gripper_id: int = 21
    right_gripper_id: int = 22
    top_serial: str = "409122273405"
    left_wrist_serial: str = "412622272997"
    right_wrist_serial: str = "412622271417"
    width: int = 640
    height: int = 480
    camera_fps: int = 30
    control_hz: float = 33.0
    # Connection remains read-only until motion is explicitly authorized.
    execute: bool = False
    max_joint_delta_rad: float = float("inf")

    def __post_init__(self):
        super().__post_init__()
        if not math.isfinite(self.control_hz) or not 1 / 3600 <= self.control_hz <= 50:
            raise ValueError("control_hz must match a ServoJ duration in [0.02, 3600] s")
        if min(self.width, self.height, self.camera_fps) <= 0:
            raise ValueError("Camera size and fps must be positive")
        if math.isnan(self.max_joint_delta_rad) or self.max_joint_delta_rad <= 0:
            raise ValueError("max_joint_delta_rad must be positive")

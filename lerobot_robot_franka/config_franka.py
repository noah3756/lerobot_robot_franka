from dataclasses import dataclass, field

from lerobot.cameras import CameraConfig

from lerobot.robots.config import RobotConfig

@RobotConfig.register_subclass("lerobot_robot_franka")
@dataclass
class FrankaConfig(RobotConfig):
    use_effort: bool = False
    use_velocity: bool = False
    use_acceleration: bool = False
    cameras: dict[str, CameraConfig] = field(default_factory=dict)

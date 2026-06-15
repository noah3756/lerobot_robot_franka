from lerobot_robot_franka.config_franka import FrankaConfig
from lerobot_robot_franka.franka import Franka

cfg = FrankaConfig(
    cameras={}
)
robot = Franka(cfg)

print("action_features =", robot.action_features)
print("observation_features =", robot.observation_features)

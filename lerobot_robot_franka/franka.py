import logging
import time
from typing import Any
import numpy as np
import sys

sys.path.append('/home/robot/01_remote_control_new/src')

from teleoperation_system.scripts.franka_state_pub_zmq import ZMQStateSub
from teleoperation_system.scripts.franka_action_pub_zmq import ZMQActionPub

from lerobot.cameras import make_cameras_from_configs
from lerobot.utils.errors import DeviceNotConnectedError, DeviceAlreadyConnectedError
from lerobot.robots.robot import Robot

from .config_franka import FrankaConfig

logger = logging.getLogger(__name__)


class FrankaGripper:
    def __init__(self, ns="/franka_gripper"):
        self.ns = ns
        self._prev_gripper_state = None
        self._gripper_state = 0.0

    def set_gripper_state(self, command_width: float) -> None:
        if command_width > 0.04:
            self._gripper_state = "open"
        else:
            self._gripper_state = "closed"
        self._prev_gripper_state = self._gripper_state

    def get_gripper_state(self) -> float:
        return 1.0 if self._prev_gripper_state == "open" else 0.0

    def reset_gripper(self) -> None:
        self._prev_gripper_state = None


class Franka(Robot):
    config_class = FrankaConfig
    name = "franka"

    def __init__(self, config: FrankaConfig):
        super().__init__(config)
        self.cameras = make_cameras_from_configs(config.cameras)

        self.config = config
        self._is_connected = False
        self._gripper = None

        self._robot_state = None
        self._gripper_state = 0.0
        self._prev_observation = None

    def connect(self, calibrate: bool = True) -> None:
        if self.is_connected:
            raise DeviceAlreadyConnectedError(f"{self} already connected")

        self._state_sub = ZMQStateSub("tcp://127.0.0.1:5556")
        self._command_pub = ZMQActionPub("tcp://127.0.0.1:5558")

        self._gripper = FrankaGripper()

        for cam in self.cameras.values():
            cam.connect()

        self._is_connected = True
        print("Franka already connected.")

    @property
    def _motors_ft(self) -> dict[str, Any]:
        motors = {f"joint_{i}.cmd_pos": float for i in range(1, 8)}
        motors["gripper.cmd_pos"] = float
        return motors

    @property
    def action_features(self) -> dict[str, Any]:
        return self._motors_ft

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        if not self.is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")

        joint_cmd = []
        gripper_cmd = []

        for i in range(1, 8):
            joint_cmd.append(float(action[f"joint_{i}.cmd_pos"]))

        if "gripper.cmd_pos" in action:
            gripper_cmd.append(float(action["gripper.cmd_pos"]))

        command_pos = np.asarray(joint_cmd + gripper_cmd, dtype=np.float32)

        self._command_pub.publish(command_pos)

        return action

    def get_observation(self) -> dict[str, Any]:
        if not self.is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")

        self._robot_state = self._state_sub.get_obs()

        obs_pos = np.asarray(self._robot_state["obs_pos"][:7], dtype=np.float32)
        joint_external_torques = np.asarray(self._robot_state["obs_torque"][:7], dtype=np.float32)
        gripper_pos = float(self._robot_state["obs_pos"][7])

        obs_dict = {}
        for i in range(1, 8):
            obs_dict[f"joint_{i}.obs_pos"] = float(obs_pos[i - 1])
            obs_dict[f"joint_{i}.obs_external_torque"] = float(joint_external_torques[i - 1])

        obs_dict["gripper.obs_pos"] = float(gripper_pos)

        for cam_key, cam in self.cameras.items():
            start = time.perf_counter()
            obs_dict[cam_key] = cam.async_read()
            dt_ms = (time.perf_counter() - start) * 1e3
            logger.debug(f"{self} read {cam_key}: {dt_ms:.1f}ms")

        self._prev_observation = obs_dict
        return obs_dict

    def reset(self):
        if self._gripper:
            self._gripper.reset_gripper()

    def disconnect(self) -> None:
        if not self.is_connected:
            return

        if self._gripper is not None:
            self._gripper = None

        for cam in self.cameras.values():
            cam.disconnect()

        self.is_connected = False
        logger.info(f"{self} disconnected.")

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        if not self.is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")

    def is_calibrated(self) -> bool:
        return self.is_connected

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @is_connected.setter
    def is_connected(self, value: bool) -> None:
        self._is_connected = value

    @property
    def _cameras_ft(self) -> dict[str, tuple]:
        return {
            cam: (self.config.cameras[cam].height, self.config.cameras[cam].width, 3)
            for cam in self.cameras
        }

    @property
    def observation_features(self) -> dict[str, Any]:
        features = {f"joint_{i}.obs_pos": float for i in range(1, 8)}
        for i in range(1, 8):
            features[f"joint_{i}.obs_external_torque"] = float
        features["gripper.obs_pos"] = float
        features.update(self._cameras_ft)

        if self.config.use_effort:
            for i in range(1, 8):
                features[f"joint_{i}.cmd_effort"] = float
        if self.config.use_velocity:
            for i in range(1, 8):
                features[f"joint_{i}.cmd_vel"] = float
        if self.config.use_acceleration:
            for i in range(1, 8):
                features[f"joint_{i}.cmd_acc"] = float
        return features

    @property
    def cameras(self):
        return self._cameras

    @cameras.setter
    def cameras(self, value):
        self._cameras = value

    @property
    def config(self):
        return self._config

    @config.setter
    def config(self, value):
        self._config = value

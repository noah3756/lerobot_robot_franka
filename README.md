# lerobot_robot_franka

`lerobot_robot_franka` 是一个 LeRobot robot 插件，用来把已有遥操作系统里的 Franka 从臂接入 LeRobot 框架。这个项目本身不重写 Franka 底层控制系统，也不替代已有的 ROS/libfranka 控制链路；它的作用是通过 ZMQ 在 LeRobot 和已有从臂控制系统之间做桥接。

整体定位可以理解为：

```text
LeRobot teleoperator / policy / replay
        |
        | action: joint_*.cmd_pos, gripper.cmd_pos
        v
lerobot_robot_franka
        |
        | ZMQ action publisher: tcp://127.0.0.1:5558
        v
已有遥操作系统中的 Franka 从臂控制节点
        |
        | ROS / libfranka / gripper driver
        v
Franka 从臂

Franka 从臂状态
        |
        | ROS / libfranka 状态采集
        v
已有遥操作系统中的状态发布节点
        |
        | ZMQ state subscriber: tcp://127.0.0.1:5556
        v
lerobot_robot_franka
        |
        | observation: joint pos, external torque, gripper, cameras
        v
LeRobot dataset / policy pipeline
```

它适合用于在已有主从遥操作系统基础上，使用 LeRobot 做数据采集、数据集管理、策略评估、策略回放和后续模仿学习训练。

## 项目功能

- 注册一个 LeRobot `Robot` 子类，机器人名称为 `franka`。
- 注册 LeRobot robot 配置类型 `lerobot_robot_franka`。
- 通过 ZMQ 接收已有从臂系统发布的 Franka 观测数据。
- 通过 ZMQ 向已有从臂系统发送 LeRobot action。
- 默认支持 7 个 Franka 关节位置控制和 1 个夹爪位置控制。
- 支持通过 LeRobot camera config 接入相机图像。
- 支持记录关节位置、关节外力矩、夹爪位置和图像观测。

## 代码结构

```text
.
├── pyproject.toml
├── readme.txt
└── lerobot_robot_franka
    ├── __init__.py
    ├── config_franka.py
    ├── franka.py
    └── test_franka.py
```

核心文件说明：

- `lerobot_robot_franka/franka.py`
  - 定义 `Franka` 类，继承 `lerobot.robots.robot.Robot`。
  - 在 `connect()` 中创建 ZMQ 状态订阅器和动作发布器。
  - 在 `send_action()` 中把 LeRobot action 转成 Franka 从臂控制命令。
  - 在 `get_observation()` 中读取 Franka 状态和相机图像，并返回 LeRobot observation。

- `lerobot_robot_franka/config_franka.py`
  - 定义 `FrankaConfig`。
  - 通过 `@RobotConfig.register_subclass("lerobot_robot_franka")` 注册 LeRobot robot 类型。
  - 支持 `use_effort`、`use_velocity`、`use_acceleration` 和 `cameras` 配置。

- `lerobot_robot_franka/test_franka.py`
  - 简单打印 `action_features` 和 `observation_features`，用于检查插件注册和 feature 定义。

- `pyproject.toml`
  - 定义包名、版本、依赖和打包规则。

## 与已有遥操作系统的关系

这个包假设你已经有一套可工作的 Franka 从臂遥操作底层系统。该底层系统通常负责：

- Franka 机器人连接。
- Franka 状态读取。
- Franka 关节位置控制。
- 夹爪控制。
- ROS 节点通信。
- libfranka 或 franka_ros 相关控制逻辑。
- 安全限制、限位、滤波、运动约束等底层保护。

`lerobot_robot_franka` 不负责这些底层功能。它只负责把 LeRobot 的统一接口接到已有系统上：

- LeRobot 调用 `send_action()` 时，本包通过 ZMQ 把目标关节位置发给已有从臂系统。
- LeRobot 调用 `get_observation()` 时，本包通过 ZMQ 从已有从臂系统读取状态。
- LeRobot 需要图像时，本包通过 LeRobot camera API 读取相机。

## 通信接口

### 状态订阅

在 `Franka.connect()` 中，代码创建状态订阅器：

```python
self._state_sub = ZMQStateSub("tcp://127.0.0.1:5556")
```

这表示已有 Franka 从臂系统需要在本机 `5556` 端口发布机器人状态。

如果已有从臂系统不在同一台机器上，需要把地址改成对应 IP，例如：

```python
self._state_sub = ZMQStateSub("tcp://192.168.x.x:5556")
```

### 动作发布

在 `Franka.connect()` 中，代码创建动作发布器：

```python
self._command_pub = ZMQActionPub("tcp://127.0.0.1:5558")
```

这表示本包会把 LeRobot action 发布到本机 `5558` 端口，由已有从臂控制系统接收并执行。

典型链路是：

```text
LeRobot send_action()
        |
        v
ZMQActionPub("tcp://127.0.0.1:5558")
        |
        v
已有 Franka 从臂控制节点
        |
        v
Franka 机器人
```

## ZMQ 数据格式约定

### 从臂状态格式

`get_observation()` 会调用：

```python
self._robot_state = self._state_sub.get_obs()
```

并期望返回一个字典，至少包含：

```python
{
    "obs_pos": [...],
    "obs_torque": [...],
}
```

字段含义：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `obs_pos` | list / array | Franka 关节和夹爪位置 |
| `obs_torque` | list / array | Franka 关节外力矩 |

当前代码使用：

```python
obs_pos = self._robot_state["obs_pos"][:7]
joint_external_torques = self._robot_state["obs_torque"][:7]
gripper_pos = self._robot_state["obs_pos"][7]
```

因此默认要求：

- `obs_pos` 至少包含 8 个元素：7 个关节位置 + 1 个夹爪位置。
- `obs_torque` 至少包含 7 个元素：7 个关节外力矩。

### 发给从臂的动作格式

`send_action()` 接收 LeRobot action 字典，并按顺序组装成 `command_pos`：

```python
[
    joint_1_cmd_pos,
    joint_2_cmd_pos,
    joint_3_cmd_pos,
    joint_4_cmd_pos,
    joint_5_cmd_pos,
    joint_6_cmd_pos,
    joint_7_cmd_pos,
    gripper_cmd_pos,
]
```

然后通过：

```python
self._command_pub.publish(command_pos)
```

发送给已有 Franka 从臂系统。

如果 action 中不包含 `gripper.cmd_pos`，则只发送 7 个关节位置。

## LeRobot action 定义

`Franka.action_features` 当前返回：

```python
{
    "joint_1.cmd_pos": float,
    "joint_2.cmd_pos": float,
    "joint_3.cmd_pos": float,
    "joint_4.cmd_pos": float,
    "joint_5.cmd_pos": float,
    "joint_6.cmd_pos": float,
    "joint_7.cmd_pos": float,
    "gripper.cmd_pos": float,
}
```

这些 key 需要和 teleoperator、policy 或 replay 数据集中的 action 字段保持一致。比如如果搭配 `lerobot_teleoperator_teleop` 使用，两边默认都是：

```text
joint_1.cmd_pos
joint_2.cmd_pos
joint_3.cmd_pos
joint_4.cmd_pos
joint_5.cmd_pos
joint_6.cmd_pos
joint_7.cmd_pos
gripper.cmd_pos
```

## LeRobot observation 定义

默认 observation 包含：

```python
{
    "joint_1.obs_pos": float,
    "joint_2.obs_pos": float,
    "joint_3.obs_pos": float,
    "joint_4.obs_pos": float,
    "joint_5.obs_pos": float,
    "joint_6.obs_pos": float,
    "joint_7.obs_pos": float,
    "joint_1.obs_external_torque": float,
    "joint_2.obs_external_torque": float,
    "joint_3.obs_external_torque": float,
    "joint_4.obs_external_torque": float,
    "joint_5.obs_external_torque": float,
    "joint_6.obs_external_torque": float,
    "joint_7.obs_external_torque": float,
    "gripper.obs_pos": float,
}
```

如果配置了相机，还会额外加入图像字段。每个相机字段的 feature 形状为：

```python
(height, width, 3)
```

例如：

```text
cam_left: (480, 640, 3)
cam_right: (480, 640, 3)
```

## 配置项

`FrankaConfig` 当前定义如下：

```python
@RobotConfig.register_subclass("lerobot_robot_franka")
@dataclass
class FrankaConfig(RobotConfig):
    use_effort: bool = False
    use_velocity: bool = False
    use_acceleration: bool = False
    cameras: dict[str, CameraConfig] = field(default_factory=dict)
```

配置项说明：

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `use_effort` | `bool` | `False` | 是否在 observation feature 中声明 `joint_*.cmd_effort` |
| `use_velocity` | `bool` | `False` | 是否在 observation feature 中声明 `joint_*.cmd_vel` |
| `use_acceleration` | `bool` | `False` | 是否在 observation feature 中声明 `joint_*.cmd_acc` |
| `cameras` | `dict[str, CameraConfig]` | `{}` | LeRobot 相机配置 |

注意：当前代码中 `use_effort`、`use_velocity`、`use_acceleration` 只影响 `observation_features` 声明；`get_observation()` 目前没有实际填充这些字段。如果打开这些配置，需要同步扩展 `get_observation()` 的返回值，否则 LeRobot 数据记录时可能出现 feature 和实际 observation 不一致。

## 环境依赖

Python 版本：

```text
Python >= 3.10
```

Python 包依赖：

```text
numpy
teleop
lerobot>=0.4
```

此外，代码依赖已有遥操作系统中的 Python 模块：

```python
sys.path.append('/home/robot/01_remote_control_new/src')

from teleoperation_system.scripts.franka_state_pub_zmq import ZMQStateSub
from teleoperation_system.scripts.franka_action_pub_zmq import ZMQActionPub
```

也就是说，运行环境必须能导入：

```python
teleoperation_system.scripts.franka_state_pub_zmq
teleoperation_system.scripts.franka_action_pub_zmq
```

如果你的遥操作系统路径不是 `/home/robot/01_remote_control_new/src`，需要修改 `franka.py` 中的路径，或者使用 `PYTHONPATH`：

```bash
export PYTHONPATH=/path/to/your/remote_control_system/src:$PYTHONPATH
```

长期维护时，更推荐把已有遥操作系统打包成可安装 Python 包，而不是在源码里写死绝对路径。

## 安装

在本项目根目录执行：

```bash
pip install -e .
```

如果 LeRobot 在 conda 环境中：

```bash
conda activate <your_lerobot_env>
pip install -e .
```

安装后可以检查导入：

```python
from lerobot_robot_franka.config_franka import FrankaConfig
from lerobot_robot_franka.franka import Franka
```

也可以运行：

```bash
python lerobot_robot_franka/test_franka.py
```

它会打印 robot 的 action 和 observation feature。

## 使用前准备

### 1. 启动已有 Franka 从臂系统

先启动已有遥操作系统中的 Franka 从臂控制节点，确保它完成：

- Franka 连接。
- 夹爪连接。
- 状态采集。
- ZMQ 状态发布到 `tcp://127.0.0.1:5556`。
- ZMQ 动作接收到 `tcp://127.0.0.1:5558`。

### 2. 检查相机

如果需要采集图像，可以用 LeRobot 工具查看相机：

```bash
lerobot-find-cameras opencv
```

确认 `/dev/video*` 或相机 index 后，再写入 `--robot.cameras` 配置。

### 3. 确认 action/observation 字段对齐

如果搭配遥操作插件使用，需要确保 teleoperator 输出的 action key 与本 robot 的 `action_features` 一致。

默认匹配：

```text
lerobot_teleoperator_teleop -> lerobot_robot_franka
joint_1.cmd_pos             -> joint_1.cmd_pos
...
joint_7.cmd_pos             -> joint_7.cmd_pos
gripper.cmd_pos             -> gripper.cmd_pos
```

## 数据采集示例

### 不使用相机

```bash
lerobot-record \
  --robot.type=lerobot_robot_franka \
  --teleop.type=lerobot_teleoperator_teleop \
  --dataset.repo_id=debug/tmp \
  --dataset.root=./data_grab_cube2 \
  --dataset.push_to_hub=false \
  --dataset.num_episodes=5 \
  --dataset.episode_time_s=10 \
  --dataset.reset_time_s=10 \
  --dataset.fps=25 \
  --dataset.single_task="Grab the cube" \
  --dataset.streaming_encoding=true \
  --dataset.vcodec=h264 \
  --dataset.encoder_threads=2 \
  2>&1 | grep -v '^\[libx264'
```

### 使用双相机

```bash
lerobot-record \
  --robot.type=lerobot_robot_franka \
  --robot.cameras="{cam_left: {type: opencv, index_or_path: /dev/video10, width: 640, height: 480, fps: 30}, cam_right: {type: opencv, index_or_path: /dev/video4, width: 640, height: 480, fps: 30}}" \
  --teleop.type=lerobot_teleoperator_teleop \
  --dataset.repo_id=debug/tmp \
  --dataset.root=./data_grab_cube3 \
  --dataset.push_to_hub=false \
  --dataset.num_episodes=15 \
  --dataset.episode_time_s=10 \
  --dataset.reset_time_s=8 \
  --dataset.fps=30 \
  --dataset.single_task="Grab the cube" \
  --dataset.streaming_encoding=false \
  --dataset.vcodec=h264 \
  2>&1 | grep -v '^\[libx264'
```

这里的 `teleop.type=lerobot_teleoperator_teleop` 表示主端遥操作输入来自另一个 LeRobot teleoperator 插件；而 `robot.type=lerobot_robot_franka` 表示从臂 Franka 的执行和观测由本包负责。

## 策略评估示例

使用训练好的 policy 控制 Franka：

```bash
lerobot-record \
  --robot.type=lerobot_robot_franka \
  --robot.cameras="{cam_left: {type: opencv, index_or_path: /dev/video10, width: 640, height: 480, fps: 30}, cam_right: {type: opencv, index_or_path: /dev/video4, width: 640, height: 480, fps: 30}}" \
  --policy.path=/home/robot/lerobot/outputs/franka_pick_cube_dp \
  --policy.device=cuda \
  --dataset.repo_id=debug/eval_franka \
  --dataset.root=./eval_dp \
  --dataset.push_to_hub=false \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=40 \
  --dataset.reset_time_s=10 \
  --dataset.fps=30 \
  --dataset.single_task="Grab the cube" \
  --dataset.streaming_encoding=false \
  --dataset.vcodec=h264 \
  2>&1 | grep -v '^\[libx264'
```

此时不再使用 teleoperator，而是由 policy 直接输出 action，本包负责把 action 通过 ZMQ 发给 Franka 从臂控制系统。

## 数据集查看

可视化本地数据集：

```bash
lerobot-dataset-viz \
  --repo-id debug/tmp \
  --root /home/robot/lerobot/eval_dp \
  --mode local \
  --episode-index 0
```

## 数据集回放

可以用 `lerobot-replay` 回放已有数据集中的动作：

```bash
lerobot-replay \
  --robot.type=lerobot_robot_franka \
  --dataset.repo_id=debug/merged \
  --dataset.root=<dataset_root> \
  --dataset.episode=0
```

回放时仍然需要先启动已有 Franka 从臂底层系统，因为本包只是通过 ZMQ 下发动作，不直接控制 Franka 硬件。

## Hugging Face 数据集上传

如果需要把数据集上传到 Hugging Face，需要先登录：

```bash
export HUGGINGFACE_TOKEN=<your_token>
hf auth login --token ${HUGGINGFACE_TOKEN} --add-to-git-credential
git config --global credential.helper store
hf auth whoami
```

不要把真实 token 写入 README、脚本或 Git 仓库。`readme.txt` 中原先记录的 token 样例应视为敏感信息，公开仓库前建议删除或替换。

## 当前实现限制

- ZMQ 地址被写死为 `tcp://127.0.0.1:5556` 和 `tcp://127.0.0.1:5558`。
- 已有遥操作系统路径被写死为 `/home/robot/01_remote_control_new/src`。
- `get_observation()` 没有处理 `self._state_sub.get_obs()` 返回 `None` 的情况。
- `get_observation()` 假设 `obs_pos` 至少 8 维、`obs_torque` 至少 7 维，目前没有长度检查。
- `send_action()` 假设 action 中一定包含 7 个 `joint_*.cmd_pos` 字段。
- `FrankaGripper` 当前只做简单开闭状态转换，实际夹爪控制仍依赖已有从臂系统。
- `calibrate()` 是空实现，默认 Franka 标定和初始化由已有系统完成。
- `use_effort`、`use_velocity`、`use_acceleration` 目前只影响 feature 声明，没有同步填充 observation 数据。
- `disconnect()` 会断开相机，但没有显式关闭 ZMQ socket。

这些限制符合“LeRobot 适配层”的最小实现方式。如果要作为长期维护的开源项目，建议逐步把地址、路径、关节数量、夹爪策略和字段校验都改成配置项。

## 常见问题

### 这个包能单独控制 Franka 吗？

不能。它依赖已有 Franka 从臂控制系统。真正连接 Franka、执行控制和做安全保护的是原来的 ROS/libfranka 系统；本包只负责 LeRobot 接口和 ZMQ 桥接。

### 为什么要用 ZMQ？

ZMQ 用来把 LeRobot 的 Python 进程和已有遥操作系统解耦。这样原来的 Franka 控制逻辑可以继续留在 ROS/C++/libfranka 侧，LeRobot 侧只需要处理统一的 action 和 observation。

### 为什么 observation 里有外力矩？

当前 Franka 从臂状态中读取了 `obs_torque`，并映射成：

```text
joint_*.obs_external_torque
```

这些数据可以用于数据记录、分析或后续策略训练。

### 相机是通过 ZMQ 传的吗？

不是。当前相机通过 LeRobot camera config 创建，并在 `get_observation()` 中调用 `cam.async_read()` 读取。ZMQ 只负责 Franka 状态和动作通信。

### `franka_ros` 和 `libfranka` 的关系是什么？

现有说明中提到 `franka_ros` 没有提供所需的关节力矩控制接口，因此底层控制后来改成了 `libfranka`。本包不直接依赖二者的 C++ 接口，只依赖已有系统通过 ZMQ 暴露出来的状态和动作接口。

## 建议后续改进

- 将 ZMQ state/action 地址加入 `FrankaConfig`。
- 将遥操作系统 Python 路径改为环境变量或正式 Python 依赖。
- 为 `obs_pos`、`obs_torque` 和 action 字段增加校验与错误提示。
- 在 `disconnect()` 中关闭 ZMQ publisher/subscriber。
- 将关节名称、关节数量、夹爪字段做成可配置。
- 明确 `use_effort`、`use_velocity`、`use_acceleration` 的数据来源，并在 `get_observation()` 中实际返回对应字段。
- 删除公开文档中的 Hugging Face token 或其他私人路径信息。


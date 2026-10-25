# X-Trainer Pi05 · LeRobot

面向 X-Trainer 的 PI0.5（Pi05）训练与部署工程。它以 Hugging Face
[LeRobot](https://github.com/huggingface/lerobot) 为基础，只保留 Pi05 的模型、
数据集、训练、实时动作分块（RTC）和硬件接入基础设施。

已接入 X-Trainer 原始数据转换、Pi05 训练启动、WebSocket 推理服务和双臂真机客户端。
通信、相机与机械臂代码复用 X-Trainer-XVLA；Pi05 使用自己的模型与归一化处理器。
当前默认支持单帧、绝对关节动作、同步分块推理。

## 保留内容

- `src/lerobot/policies/pi05/`：Pi05 模型、配置与预/后处理器。
- `src/lerobot/policies/common/`、`rtc/`、`pi_gemma.py`：Pi05 必需的流匹配、
  实时动作分块及 Gemma 组件。
- `src/lerobot/datasets/`、`processor/`、`scripts/lerobot_train.py`：LeRobot 数据
  格式、处理管线和训练入口。
- `src/lerobot/{cameras,motors,robots,teleoperators}/`：后续接入 X-Trainer
  真机所需的硬件扩展点。

## 已移除内容

- 其他策略及其依赖：ACT、Diffusion、Pi0、XVLA、SmolVLA、GROOT 等。
- 上游通用示例、测试、文档站、Docker 镜像、CI 配置和媒体资源；
  本项目的回归测试位于 `tests/xtrainer/`。
- 与本项目无关的模拟任务与策略依赖组合。

## 环境安装

训练和真实模型推理需要 Python 3.12+，推荐 Linux + NVIDIA GPU。安装锁定依赖：

```powershell
uv sync --locked --extra all --python 3.12
```

数据转换输入格式与 XVLA 工程相同，每个 episode 具有
`observation/0.pkl`、`topImg/0.jpg`、`leftImg/0.jpg`、`rightImg/0.jpg` 等同步帧。
pickle 必须来自可信采集源；每帧的 `joint_positions` 和 `control` 均为 14 维，
顺序为左臂 6 关节、左夹爪、右臂 6 关节、右夹爪。关节单位为弧度，夹爪为 0–1。
每次转换使用一条任务描述，不同任务应分别处理。

```powershell
uv run python scripts/xtrainer/convert_raw_to_lerobot.py --raw-root /path/to/collect_data --output /path/to/dataset_v3 --task "pick up the object" --fps 30
```

转换直接生成当前 LeRobot v3 格式及 Pi05 所需统计量。输出目录必须不存在；
缺帧、非有限数值、错误动作维度会报错。默认输出视频，`--images` 可改为图片存储。
这里不支持直接读取 XVLA 工程的 v2.1 数据集。

训练配置在 [configs/xtrainer/train_pi05.yaml](configs/xtrainer/train_pi05.yaml)。
默认基座为 `lerobot/pi05_base`，需要可访问该模型及 PaliGemma tokenizer；
也可以通过 `--policy-path` 指定本地完整基座。务必使用以下启动脚本，
它会从数据集重新推导相机和状态输入，避免沿用基座的相机名称：

```bash
uv run python scripts/xtrainer/train_pi05.py --dataset-root /path/to/dataset_v3 --batch-size 4 --steps 30000
# 检查数据元信息并打印命令，不开始训练：
uv run python scripts/xtrainer/train_pi05.py --dataset-root /path/to/dataset_v3 --dry-run
# 从保存的训练状态继续：
uv run python scripts/xtrainer/train_pi05.py --dataset-root /path/to/dataset_v3 --resume outputs/train/xtrainer_pi05/checkpoints/last/pretrained_model
```

服务器使用微调后检查点内保存的预处理、归一化及反归一化参数。
归一化是把关节数值转换到模型使用的尺度；缺失这些参数时不能正确还原机器人动作，
因此服务端要求完整检查点，不会使用空统计量兜底。默认全参数微调，暂未增加 LoRA
专属训练与合并脚本；服务端拒绝未合并的适配器和启用历史记忆/RTC 的检查点。

```bash
uv run python scripts/xtrainer/serve_policy.py --checkpoint outputs/train/xtrainer_pi05/checkpoints/last/pretrained_model --host 0.0.0.0 --port 8000
```

默认配置只监听本机；跨机器连接时显式设置 host。通信沿用 XVLA 的可信局域网
WebSocket 协议，无认证和 TLS。可以先启动不加载模型的模拟服务：

```bash
uv run python scripts/xtrainer/serve_mock_policy.py --host 127.0.0.1 --port 8000
```

真机端复用 XVLA 的相机、Dobot 双臂和 Feetech 夹爪驱动。
安装硬件依赖后，按实际设备填写 IP、串口及相机序列号；可用
`scripts/xtrainer/check_real_hardware.py --help` 查看硬件检查入口。

```bash
uv pip install -r deploy/xtrainer/real/requirements.txt
uv run python scripts/xtrainer/run_real.py --help
# 以下命令会实际使能和移动机器人，先核对设备参数与现场状态：
uv run python scripts/xtrainer/run_real.py --host SERVER_IP --task "pick up the object" --action-horizon 32 --max-steps 100 --execute
```

客户端沿用 XVLA 的控制频率、可选动作平滑和退出清理；必须显式指定
`--execute` 才会使能机械臂。Pi05 服务默认预测 50 步，客户端可以执行前 32 步
后重新获取观测。硬件参数通过客户端命令行设置，服务配置中的参数仅作用于服务端。

验证命令：

```bash
uv sync --locked --extra all --extra test
uv run pytest tests/xtrainer -q
```

已通过 48 项无硬件测试，包含真实本地 WebSocket 往返和模拟模型的处理链检查。
原始数据转换使用模拟 writer 验证接口；完整 v3 文件写入、GPU 训练、真实检查点
推理及真机表现仍须在目标环境验证。本地轻量测试环境不等同于完整训练环境。

## 上游基线

本目录从 LeRobot commit `3991580a5673f5f0219a4e8835a5f973eeccf9a7` 创建，
遵循上游 Apache-2.0 许可证；完整许可证见 [LICENSE](LICENSE)。

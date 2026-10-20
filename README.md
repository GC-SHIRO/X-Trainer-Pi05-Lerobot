# X-Trainer Pi05 · LeRobot

面向 X-Trainer 的 PI0.5（Pi05）训练与部署工程。它以 Hugging Face
[LeRobot](https://github.com/huggingface/lerobot) 为基础，只保留 Pi05 的模型、
数据集、训练、实时动作分块（RTC）和硬件接入基础设施。

当前仓库是第一阶段骨架：已完成 LeRobot 上游代码的克隆与瘦身；下一阶段将在此
接入 X-Trainer 的数据转换、训练配置和真机部署适配。

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
- 上游示例、测试、文档站、Docker 镜像、CI 配置和媒体资源。
- 与本项目无关的模拟任务与策略依赖组合。

## 环境安装

需要 Python 3.12 及支持的 CUDA/PyTorch 环境。使用 `uv` 安装 Pi05 训练依赖：

```powershell
uv sync --extra all
```

最小训练入口仍使用 LeRobot 的标准命令：

```powershell
uv run lerobot-train --policy.type=pi05 ...
```

X-Trainer 专用配置会在下一步增加到 `configs/xtrainer/`。

## 上游基线

本目录从 LeRobot commit `3991580a5673f5f0219a4e8835a5f973eeccf9a7` 创建，
遵循上游 Apache-2.0 许可证；完整许可证见 [LICENSE](LICENSE)。

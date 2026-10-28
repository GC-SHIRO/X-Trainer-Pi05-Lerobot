# X-Trainer Pi05 环境与模型工具

这些工具参照 XVLA 工程整理，参数与依赖已改为本仓库的 Pi05 / LeRobot 实现。
从仓库根目录运行，Linux/Bash 使用 Conda；已配置 Python 环境也可以直接运行 Python 下载入口。

| 工具 | 用途 |
| --- | --- |
| `install_xtrainer_env.sh` | 创建或复用 `xtrainer-pi05`，安装训练、视频与硬件依赖 |
| `constraints-pi05.txt` | 固定 PyTorch 2.8.0 / TorchVision 0.23.0 / TorchCodec 0.7.0 |
| `check_environment.py` | 检查 Python、关键依赖、FFmpeg 及可选 CUDA |
| `download_pi05_weights_hf.sh` | Hugging Face 下载入口 |
| `download_pi05_weights_modelscope.sh` | ModelScope 下载入口 |
| `download_pi05_weights.py` | 共享下载、完整性检查及离线 tokenizer 路径配置 |
| `transform_xtrainer_dataset_images.py` | 生成 v3 视频数据集副本，仅将右手图像旋转 180°；用法见主 README 第 5.1 节 |

## 环境

```bash
bash tools/install_xtrainer_env.sh
conda activate xtrainer-pi05
python tools/check_environment.py --require-cuda
```

安装器要求 Ubuntu x86_64 和已有 Conda，推荐 Ubuntu 24.04。
默认 CUDA wheel 为 cu128，CPU 模式用 `--cpu-only`。
`--source china|official` 控制 Python 包索引；PyTorch 默认始终使用官方源。
可用 `PIP_INDEX_URL`、`TORCH_INDEX_URL` 覆盖本次运行的索引。

其他选项：

```bash
bash tools/install_xtrainer_env.sh --help
bash tools/install_xtrainer_env.sh --env-name xtrainer-pi05-dev --source official
bash tools/install_xtrainer_env.sh --cpu-only --skip-system-packages
bash tools/install_xtrainer_env.sh --dry-run
```

默认通过 apt 安装 FFmpeg、编译工具、USB runtime；没有系统安装权限时用
`--skip-system-packages`，并自行准备这些依赖。已有同名环境必须为 Python 3.12。
安装器复用环境，不删除环境；不安装显卡驱动、不下载模型、不连接机器人。

## 模型

```bash
bash tools/download_pi05_weights_hf.sh
bash tools/download_pi05_weights_modelscope.sh
```

默认为 `models/pi05-base`，其中包括基座完整快照和 `tokenizer/`。
共享参数：

| 参数 | 作用 |
| --- | --- |
| `--env-name NAME` | Bash 包装器使用的 Conda 环境名 |
| `--repo-id ID` / `--model-id ID` | 基座 ID，默认 `lerobot/pi05_base` |
| `--output-dir PATH` | 自定义下载目录 |
| `--revision REV` | 基座版本 |
| `--tokenizer-repo-id ID` / `--tokenizer-model-id ID` | tokenizer 来源 |
| `--tokenizer-revision REV` | 独立的 tokenizer 版本 |
| `--endpoint URL` | Hugging Face API / 镜像地址，仅作用于 HF |
| `--dry-run` | 仅输出计划，不联网、不写文件 |

Hugging Face 默认 tokenizer 为 `google/paligemma-3b-pt-224`；
ModelScope 默认 tokenizer 为 `AI-ModelScope/paligemma-3b-pt-224`。
只下载 tokenizer 相关文件，不下载第二份 PaliGemma 权重。
需授权的资源使用平台登录或 `HF_TOKEN` / `MODELSCOPE_API_TOKEN`。

直接使用当前 Python，无需 Conda 包装器：

```bash
python tools/download_pi05_weights.py --source hf --endpoint https://hf-mirror.com
python tools/download_pi05_weights.py --source modelscope --dry-run
```

完成后检查模型类型、必要配置、权重文件与离线 tokenizer 加载。
下载器会修改本地模型与预处理器的 tokenizer 路径，写入绝对路径并记录
`xtrainer_download.json`。移动模型目录后重新运行工具。
已有完整快照的源文件可能被下载库刷新，因此每次下载完成都会重新配置并校验 tokenizer。

训练启动器优先选择默认本地模型；自定义目录通过 `--policy-path PATH` 传入。
完整流程见 [主 README](../README.md)。

本目录不包含 XVLA 的 v2.1 数据集相机翻转工具；它与本项目 v3 布局不同。
当前转换保留 raw 图像朝向，采集与部署应使用一致的相机安装方式。

# X-Trainer 标准链路首次实机部署

2026-11-04。代理仅准备目录、安装依赖、检查配置；实机入口由用户手动运行。

## 已准备环境

- 服务端：dell211@192.168.20.107，`/Volume/xtrainer-standard-20261104`。
- real 端：dobot@192.168.20.118，`/home/dobot/Pi05/xtrainer-standard-20261104`。
- 两端使用各自 `miniconda3/envs/xtrainer-pi05` 的 Python，脚本自动设置源代码路径。
- Zenoh 1.10.2 已安装，服务端监听 TCP 7447。首次跨机/实机运行尚未验收。
- 权重沿用 `/Volume/X-Trainer-Pi05-Lerobot/outputs/train/pi05_expert_box200/checkpoints/120000/pretrained_model`，不复制、不修改。
- 两端正式工作区原有未提交修改未覆盖，迁移版本位于上面的独立目录。

## 先开服务端

```bash
cd /Volume/xtrainer-standard-20261104
bash scripts/xtrainer/run_standard_server.sh
```

等待模型加载、预热并开始服务，再启动 real。加载失败时先保留 server 日志，不启动 real。

## 用户手动开 real

```bash
cd /home/dobot/Pi05/xtrainer-standard-20261104
bash scripts/xtrainer/run_standard_real.sh --duration=10 --task="pick up the box"
```

任务文字替换为训练/当前实验使用的原任务。脚本显式传入 `--robot.execute=true`，会允许首次动作时使能机械臂。两个启动脚本都可追加参数覆盖配置。不要同时保留旧 run_real 或其他程序控制同一设备。

## 本轮行为与记录

- 非 RTC 普通 chunk 模式，标准远程异步执行与 aligned 动作衔接；预测/执行配置为 50 步。
- 控制频率 33 Hz，插值倍率 1，ServoJ 的 t 约 30.303 ms。
- 目前未恢复旧三点平滑，不把迁移成功等同于已解决抖动。
- 新入口没有旧 run_real 从服务端 metadata 读取复位姿态并自动 smooth_reset 的步骤；首次试运行前由用户确认起始姿态。
- 相机沿用原 serial、640×480 和 30 fps；顶视图保持旧训练变换。需要换硬件时在 `remote_real.json` 的 robot 项里显式覆盖。
- 默认仍使用原 Dobot 端口，未迁移协议版本。
- 双端日志均在各自部署目录的 `outputs/standard_logs/`，文件名包含启动时间。
- 中断后检查 real 日志中的停止与资源清理信息。跨机握手/故障收尾尚未通过实机验收。

## 回退

先结束新 real 入口，再退出新服务端；回到各自主项目目录，使用原来的服务端和 run_real 启动命令。迁移目录与原工作区相互独立。代理没有运行任何实机入口。

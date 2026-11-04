# X-Trainer 部署收敛计划

日期：2026-11-04。范围：规划，尚未切换运行代码。

## 目标与边界

复用当前仓库的 LeRobot 模型加载、保存的预处理/后处理、远程推理、RTC 和动作执行组件。自定义代码集中于 X-Trainer 的设备连接、双臂数据映射与训练图像适配。这里的“标准”指当前仓库已有的接口；尚未核实其与最新上游完全一致，也未通过本机真实模型或实机验收。

默认控制频率保持 33 Hz，ServoJ 单点时间保持与控制频率联动。训练数据帧率、相机帧率和控制频率分开记录，不随迁移自动修改。若训练数据为 30 Hz，33 Hz 消费动作会改变动作时间尺度，必须作为对照变量明确记录。暂不调整现有 Dobot 端口及协议版本。

## 已核实的复用入口

| 现有组件 | 目标组件 | 处理方式 |
| --- | --- | --- |
| PI05XTrainerPolicy | PI05Policy + inference/policy_runner + remote_inference/deployment | 复用 checkpoint 和保存的处理器，逐步移除重复加载逻辑 |
| 自定义 WebSocket server/client | lerobot-policy-server + remote_inference + ZenohTransport | 客户端与服务端成对迁移，协议不能混用 |
| rtc_runner.py | rollout + remote inference engine + ChunkRuntime | 复用请求调度、动作衔接与停止流程，避免另写一套队列 |
| XTrainerRealEnvironment | Robot 接口的 X-Trainer 适配器 | 实现连接、观测、动作、断连、特征与保持能力 |
| Dobot、Feetech、RealSense 驱动 | 现有底层驱动 | 先复用，避免同时改动驱动和调度 |
| 图像变换、夹爪语义 | 明确的数据处理步骤 | 只执行一次，保证与训练数据一致 |

参考源码：`src/lerobot/scripts/lerobot_rollout.py`、`src/lerobot/scripts/lerobot_policy_server.py`、`src/lerobot/remote_inference/README.md`、`src/lerobot/remote_inference/configs.py`、`src/lerobot/robots/robot.py`。

## 阶段 0：冻结对照与定位消抖回归

保存当前提交、checkpoint、双端配置、实际启动参数和 real 端逐步日志。以 c272666 的父提交作为旧消抖实现的参考，而不是整体回滚仓库。

该提交删除了段内三点平滑（默认强度 0.5）、段首 6 步过渡和段尾 6 步减速。先用同一份记录的动作序列离线重放这些处理，分别比较三项效果；报告相邻目标变化、速度/加速度变化、路径偏差。不能把离线目标更平滑直接等同于实机更稳定。

交付：基线记录、动作对比、需保留的平滑行为说明。保持模型、频率与硬件参数一致，避免同时调整 gain 与调度。

## 阶段 1：接入标准 Robot 接口

新增 X-Trainer RobotConfig 与 Robot 实现，注册到当前仓库支持的机器人入口。初期包装现有驱动与硬件能力。

固定 14 维顺序：左臂 6 关节、左夹爪、右臂 6 关节、右夹爪。保留关节 rad 与 Dobot deg 的边界转换，明确夹爪 [0,1] 的开闭方向。以 checkpoint/dataset 的实际 feature names 决定字段名与顺序，不凭字典排序生成向量。

保持双臂并发发送，每个连接单个在途请求；动作发送成功与物理到达区分。适配器不能自行再睡一个周期，由 rollout 统一负责节拍。明确连接与使能分离、复位入口、正常保持、异常退出和下使能的语义；不得仅因 Robot.connect 被调用就意外开始运动。

交付：硬件适配模块与 feature 映射说明。通过假设备验证单位、顺序、并发失败收尾；再做只读设备连接检查。

## 阶段 2：模型输入输出等价性

使用同一 checkpoint、同一组保存观测，比较旧适配器与标准 PolicyRunner 的输入。重点核对顶视相机裁剪及水平/垂直翻转、腕部图像、RGB 顺序、图像尺寸、任务文本、状态排列与 dtype。

服务端使用 checkpoint 保存的 processor，核实归一化/反归一化只发生一次。标准远程协议需要明确的 semantics 与 FeatureSpec；为 14 维关节/夹爪数据建立描述，若 checkpoint 信息不完整则显式补齐。

Pi05 推理含随机采样：固定噪声或随机源后比较输出误差，不用两次独立采样“不完全相同”判定迁移失败。核对截取动作长度和模型坐标空间的 RTC 前缀。

交付：数据契约、配置文件、等价性结果。此阶段不连接运动执行。

## 阶段 3：双机标准远程部署，先关闭 RTC

服务端使用 lerobot-policy-server，机器人端使用 lerobot-rollout 的 remote 后端。当前仓库已有普通 chunk 模式；先用此模式建立与现有非 RTC 流程的对照，再切 guided RTC。

配置目标：rollout fps=33、服务端 execution.action_fps=33、interpolation_multiplier=1；具体配置字段与命令在实施时由配置类核实。保留相机原有帧率。动作预测长度与执行长度分别配置，日志中明确显示实际值，解决服务端 50 点与客户端执行 32 点的隐式差异。

Zenoh 是另一种通信实现，需配置双机连接端点、可达性及依赖；旧 WebSocket 端口与参数不能原样照搬。先假设备联调，再确认机器人端是否需要 checkpoint 或仅需远程描述，避免不必要的本地模型加载。

验证：迟到结果、队列耗尽、断网、服务端退出、Ctrl-C、资源清理；确认保持/停止行为可解释，没有旧动作无限排队或重新连接后自动继续运动。现有日志中的重复 Ctrl-C 后 native core dump 单列排查，不在无调用栈时归因于某个库。

交付：一份服务端配置、一份 real 端配置、两条可复现命令及部署依赖说明。

## 阶段 4：明确平滑与 RTC 的分工

标准 ActionInterpolator 是线性插值，会把控制频率乘以 multiplier；它不是旧三点滤波，也不保证加速度连续。33 Hz 下 multiplier=2 会成为 66 Hz，因此初始设为 1，不用提高发送频率来替代本次消抖工作。

先评估标准普通 chunk 对齐/混合能否覆盖段首过渡。若仍需要三点段内平滑，在统一动作处理位置保留一个可配置的小组件，不重建整套执行器；夹爪不随关节滤波。速度、加速度限值需有设备/任务依据，再决定是否增加约束。

guided RTC 的输入前缀必须代表实际计划继续执行的动作，不能对物理命令滤波后仍无条件把原始未滤波模型动作作为前缀。审查归一化、相对动作和后处理的映射，在方案明确前不默认组合 RTC 与新滤波。

对照顺序：普通 chunk 原始动作、普通 chunk 加段内平滑、guided RTC、经前缀一致性验证的 guided RTC 加平滑。不得在同一轮同时更改控制频率、伺服增益和滤波。

## 阶段 5：验收后清理重复流程

验证通过后才将标准命令设为默认；旧脚本先保留为回退入口。再删除不再使用的自定义模型包装、WebSocket 协议和 rtc_runner，保留有用的输入校验、设备驱动与逐步日志。每阶段单独提交，能够明确回退到上个可运行阶段。

验收至少覆盖：33 Hz 下发送间隔分布与最大停顿、段内目标反向变化、段间跳变、实测关节跟踪误差、双臂发送偏差、任务成功率和正常退出。具体数值阈值在取得基线后制定；不能仅凭平均帧率或“不报错”判定通过。

## 执行顺序

阶段 0 与阶段 1 先做；阶段 2 是切换执行入口的前置条件；阶段 3 通过后再进入阶段 4。阶段 5 最后做。此次只提交规划文档，未切换控制链路或操作实机。

## 首批实施进度（2026-11-04）

- 已新增 `src/lerobot/robots/xtrainer/`，注册 `robot.type=xtrainer` 并接入标准机器人工厂与 rollout 入口。
- 固定字段名与 `convert_raw_to_lerobot.py` 的 JOINT_NAMES 一致；使用现有驱动，`send_action` 不额外休眠。顶视图保持旧路径的裁剪、缩放、180 度翻转。
- `connect` 只连接和读取设备；必须设置 `robot.execute=true` 才可在首次动作前使能。此行为仍需结合标准 rollout 的启动/保持流程验证。
- 已新增 `scripts/xtrainer/compare_smoothing.py`，只依赖 NumPy，不加载模型或连接机器人。比较真实日志中原始目标与旧三点平滑的指令变化；段首混合、段尾减速尚未纳入该工具。
- 对照工具用法（horizon 必须与该次真实运行一致）：

```bash
python scripts/xtrainer/compare_smoothing.py outputs/debug_logs/control.jsonl \
  --horizon 32 --control-hz 33 \
  --output outputs/debug_logs/smoothing_comparison.json
```

- 验证：离线平滑测试 1 项通过；标准适配器测试因缺少 draccus 被跳过。当前解释器还缺少 torch、cv2。新增文件语法检查通过。
- 未具备真实 checkpoint、完整逐步动作日志及本地模型运行依赖，因此没有声称输入输出等价、远程连通或实机消抖验收完成。
- 下步：在具备 LeRobot 依赖的部署环境运行适配器测试，再完成 checkpoint 特征描述与标准远程配置。尚未生成可直接控制真机的迁移命令，也尚未移除旧执行入口。

## 远端离线验证进度

- real 主机：dobot@192.168.20.118，项目 `/home/dobot/Pi05/X-Trainer-Pi05-Lerobot`。
- 模型主机：dell211@192.168.20.107，项目 `/Volume/X-Trainer-Pi05-Lerobot`。
- 两端 Pi05 环境均可用，真实权重位于模型主机 `outputs/train/pi05_expert_box200/checkpoints/120000/pretrained_model`。
- 双端原项目均有未提交修改，验证代码放在 `/tmp/xtrainer-convergence-20261104`，未覆盖原工作区。
- 用户明确要求：不得由代理启动 run_real；标准 rollout 的实机执行也留给用户手动启动。
- real 主机上的离线适配/平滑/模型输入契约测试共 3 项通过，测试使用假设备；没有连接、使能机械臂。
- 实际 checkpoint 标注视觉输入 224×224、state 32，但旧部署实际接受 640×480、state 14。Pi05 本身实现保比例补边缩放与 state padding；为标准 chunk 契约补上 policy 层的对应校验，不修改权重或物理观测数据。
- 新增 `scripts/xtrainer/validate_policy_runner.py`，共享一份真实模型权重、隔离两套处理器、固定随机种子，以合成图像和复位状态比较旧适配与标准 PolicyRunner。它不导入或运行硬件执行入口。
- 两端当前均未安装 Zenoh，远程新协议尚未联调。
- 已读取 real 端现存 `stutter.jsonl`（82 步，RTC=False），按 horizon=32 比较三点平滑：目标步长 p95 从 0.071959 降到 0.031870 rad。该统计是指令变化，不是实测运动误差，分段长度需要与当次启动参数再次核对。

### 本轮离线结果补充

- 真实 checkpoint 的固定随机种子对照通过：50×14 输出均有限，最大绝对差、平均绝对差均为 0。输入是合成 RGB 与复位状态，尚未覆盖真实相机样本或 RTC 模式。
- 保存的 rename_map 仅包含相机名称到自身的映射；离线对照按照标准部署方式清空此恒等映射，未改变输入含义，未编辑 checkpoint 文件。
- 已生成 `configs/xtrainer/remote_server.json` 与 `remote_real.json`，分别在模型端/real 端通过 draccus 配置解析。real 配置 `robot.execute=false`，仅解析配置不连接硬件。
- 以上文件均位于独立验证目录；没有启动 run_real、标准 rollout 或机械臂使能。Zenoh 依赖与假设备跨机联调仍待完成。

### 首次真机部署准备

用户选择手动直接试运行。已在 `/Volume/xtrainer-standard-20261104` 与 `/home/dobot/Pi05/xtrainer-standard-20261104` 准备独立版本，双端安装 eclipse-zenoh 1.10.2。启动脚本与配置解析检查通过，未启动真实 rollout。详见 `xtrainer_standard_deployment.md`；跨机和实机验收待用户运行后完成。

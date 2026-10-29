# 基于 PYNQ 的音视频监控系统 · ARM + FPGA 异构双算力对照评测

> 传统工业监控的滤波算法多为出厂固化参数，难以适配昼夜光照波动、现场粉尘干扰、生产设备更换及工况调整等
> 动态场景变化，普遍存在画面细节丢失、声音特征模糊的问题，监控效果随环境波动明显；同时现代工业生产愈发
> 依赖音视频技术实现设备异响预警、人员入侵检测等智能分析，传统监控的输出质量难以支撑后续智能识别需求。
> 针对这一痛点，本作品基于 PYNQ-Z2 开发板构建 ARM+FPGA 异构双算力工业音视频智能监控系统，
> 打造"现场适配评测—实时部署运行"的一体化解决方案。

| 项目 | 值 |
|---|---|
| 硬件平台 | PYNQ-Z2（TUL），XC7Z020CLG400-1，双核 Cortex-A9 + 85K 逻辑单元 |
| 软硬件划分 | 视频 3×3 邻域滤波与音频 255 抽头 FIR 各有 ARM / FPGA 双实现，在线切换 |
| 工具链 | Vivado 2024.1、Vitis HLS 2024.1、PYNQ 3.1（Release 3.1 镜像） |
| PL 主频 | 100 MHz（视频像素路径与 AXI DMA 同域） |
| 音频契约 | 48 kHz 标称、PCM16 单声道、255 抽头 Q1.15 定点 FIR、4 模式 |
| 视频契约 | 处理区 ≤320×240、BGR888、3×3 邻域、复制边界、定点饱和输出 |
| 显示 | 网页 JPEG 预览 + 720p60 HDMI（640×360 RGB332 双缓冲，左右同屏） |

---

## 1. 系统能做什么

系统只有两个页面，职责互不重叠：

**① 素材评测页（`/`）** —— 上传一段现场视频后自动完成：

| 能力 | 说明 |
|---|---|
| 画面三效果 | 平滑、边缘提取、锐化；同一段视频抽同一组帧，ARM 与 FPGA 各跑一遍 |
| 音轨三频段 | 直接从这段视频里取音轨，做低通 800 Hz / 高通 3000 Hz / 带通 800–2500 Hz |
| 结果与波形 | 处理画面预览、原始 / ARM / FPGA 三路波形同图对比（纵轴按本段信号自动缩放） |
| 运行数据 | 每个功能的 ARM 与 FPGA 耗时（均值与 P95）、逐像素/逐样本误差、帧率、丢帧 |
| 通道选择与建议 | 六项功能（视频 3 + 音频 3）各自可选 ARM 或 FPGA，并按"实测误差优先、P95 耗时次之"给出推荐理由 |
| 方案确认 | 六项选择确认后进入实时监控，所选通道即为监控页的初始配置 |

**② 实时监控页（`/monitor`）** —— 摄像头 + 麦克风现场采集：

| 能力 | 说明 |
|---|---|
| 采集 | 板载 USB 摄像头（UVC / V4L2）与 USB 麦克风（ALSA，自动重采样到 48 kHz）；也可用电脑浏览器摄像头经本地代理回传 |
| 处理 | 每帧 3×3 滤波 + 每块 PCM 的 255 抽头 FIR，通道（ARM / FPGA）与效果/频段可在线切换 |
| 显示 | 处理画面同时送网页（JPEG 预览）与 HDMI 外接显示器（720p60，左右同屏：原图 / 处理结果） |
| 回放 | 处理后的声音从板载 3.5 mm 音频口输出，由硬件 FIFO 按 48 kHz 时钟推进 |
| 状态 | 帧率、每帧处理耗时、累计帧数、丢帧数、音频已播采样数、欠载计数实时上报 |

两个页面共用同一套后端（`host/app/`）与同一块 Overlay，切换只换页面不重启服务。

---

## 2. 目录结构（严格按赛题 3.2.5.5）

```text
shenghua_av_monitor/
├── README.md              本文件：项目简介 + 复现步骤 + 目录说明
├── docs/
│   ├── architecture.md    系统架构图与数据流图（计算单元 / 传感器 / 执行器 / 通信链路）
│   ├── interface.md       寄存器映射、AXI 接口、HTTP 报文、数据类型与时序约定
│   ├── hardware_setup.md  器件与外设清单、接线、供电、物理复原
│   ├── environment.md     运行环境：OS、驱动、依赖版本、板卡与器件型号
│   ├── demo_guide.md      两个页面的操作手册与排错
│   └── filelist.txt       全量文件清单（含体积）
├── fpga/
│   ├── src/               RTL / HLS 源码
│   │   ├── rtl/           视频滤波路由、HDMI 帧缓冲、音频 FIFO 及 testbench
│   │   ├── hls/           255 抽头 FIR 的 HLS 核、系数头、C 仿真
│   │   ├── board/         ARM C 参考核、PYNQ AXI-DMA 驱动、加载自检
│   │   ├── sim/           主机侧数值测试 + 黄金向量（data/golden、data/vectors）
│   │   ├── scripts/       Vivado / Vitis HLS 构建 tcl、系数与向量生成
│   │   ├── reports/       coefficients.json（构建脚本生成）
│   │   └── vendor/        第三方 IP（rgb2dvi、audio_fifo_ctrl）与来源哈希
│   ├── build/             构建脚本 + 产出
│   │   ├── build_all.ps1 / build_all.sh    一键构建入口
│   │   ├── scripts/video_effects_vectors.py
│   │   ├── audio_live.bit / audio_live.hwh 最终构建产物（可直接上板）
│   │   └── BUILD_OK       构建成功标记（tcl 写入、打包脚本校验）
│   └── report/            综合与实现报告：timing / utilization / drc、HLS csynth+cosim、里程碑 PPA
├── host/
│   ├── model/MODEL.md     "模型与数值精度"说明（本作品无 ML 模型，见该文件）
│   ├── app/               板端应用与通信层：HTTP 服务、视频/音频引擎、FPGA 通道、HDMI、监控、测量
│   └── deploy/            部署与启动：素材准备、单文件启动器打包、上板核对脚本、主机侧摄像头代理
├── metrics/
│   ├── metrics.csv        指标汇总表（七列，一行一项指标）
│   ├── logs/              原始日志（CSV / JSON，未转述）
│   ├── scripts/           可重跑的测试与校验脚本
│   └── evidence/          证据截图 + 未提供示波器证据的说明
├── skill/                 可复用 Skill 与工作流（加分项）
│   └── README.md          每条的适用范围、使用方法、失效条件、复用结果
└── report/
    └── design_report.md   设计报告（按 3.2.5.4 八项组织，含摘要）
```

目录与赛题 3.2.5.5 的推荐结构一一对应。构建产物 `audio_live.bit` 与 `audio_live.hwh` 位于 `fpga/build/`，
成对加载即完成 PYNQ Overlay 部署。

### 2.1 命名规范与例外

除下列例外，所有目录名与文件名均为纯英文小写（字母、数字、下划线、连字符）：

| 例外 | 原因 |
|---|---|
| `README.md`、`LICENSE` | 通用约定，赛题 3.2.5.5 的示例目录本身也使用 `README.md` |
| `fpga/src/vendor/**` 中的 `ClockGen.vhd`、`TMDS_Encoder.vhd`、`LICENSE_PYNQ.txt` 等 | 第三方 IP 原始文件名，改名会破坏 `component.xml` 的引用，导致 Vivado 打包 IP 失败 |
| `fpga/build/BUILD_OK` | 构建脚本写入的成功标记，`build_video_effects.tcl` 按该名字检查 |

---

## 3. 环境

**主机侧**（Windows 10/11 或 Linux，用于构建与打包）

- Vivado 2024.1 + Vitis HLS 2024.1（需 XC7Z020 器件文件）
- Python 3.8+，`python -m pip install -r requirements.txt`
  （`numpy`、`opencv-python`、`Pillow`、`imageio-ffmpeg`）

**板卡侧**（PYNQ-Z2，PYNQ 3.1 镜像）

- 已含 `pynq` 3.1.1、`numpy`、`opencv`；`sudo apt install alsa-utils`（USB 麦克风采集用 `arecord`）
- 板卡与主机同一网段；Jupyter 可访问（板端 9090），作品服务端口 **8080**

---

## 4. 快速开始

### 4.1 构建 PL（一条命令）

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File fpga\build\build_all.ps1
```

```bash
# Linux / macOS
bash fpga/build/build_all.sh
```

入口脚本依次执行：生成 FIR 系数 → HLS C 仿真 / C 综合 / RTL 联合仿真 / 导出 IP →
Vivado 用仓库内 RTL、IP 与 PS7 预设重建 PYNQ-Z2 设计（综合、布局、布线、bitgen）→
把 `timing.rpt`、`utilization.rpt`、`drc.rpt` 收进 `fpga/report/`。

也可以分步执行：

```text
vitis_hls -f fpga/src/scripts/build_hls.tcl
vivado -mode batch -source fpga/src/scripts/build_video_effects.tcl
```

产物：`fpga/src/build/video_effects_output/audio_live.bit` 与 `audio_live.hwh`，
复制到 `fpga/build/` 即为随包提交的那一份（`fpga/build/` 中已附现成产物，可跳过构建直接上板）。

### 4.2 RTL 仿真

```text
python fpga/build/scripts/video_effects_vectors.py          # 生成硬件输入与 ARM 黄金期望输出
cd fpga/src/build/video_effects_sim
xvlog ../../rtl/video_smooth_router.v ../../rtl/tb_video_effects.v
xelab tb_video_effects -s tb_video_effects
xsim tb_video_effects -runall
```

24 组用例覆盖四种路由模式、随机像素、1×1 / 1×19 / 17×1 窄图、240×320 棋盘、
脉冲边界（四角为 255）、饱和值、AXI 背压、连续帧与音频旁路。

### 4.3 上板运行

```text
# 1) 准备素材（自备有权使用的视频）
python host/deploy/prepare_mv.py "path/to/movie.mp4" --start 30 --output host/media/demo_mv

# 2) 打成一个单文件启动器，落在 dist/
python host/deploy/package_live.py --video-effects --mv-dir host/media/demo_mv

# 3) 把启动器上传到板卡 Jupyter 根目录，在 Notebook 里执行
%run ./start_shenghua_video_effects_avsync.py

# 4) 浏览器打开
http://<board-ip>:8080          # 素材评测页
http://<board-ip>:8080/monitor  # 实时监控页
```

板载按键：BTN0 / BTN1 / BTN2 = 低通 / 高通 / 带通，BTN3 = 切换 ARM / FPGA 通道（监控运行时切 HDMI 画面 / 音频分析视图）。开始与停止都在网页上。

### 4.4 复测与自检

```text
python host/deploy/check_video_effects_board.py --host <board-ip>   # 四种效果逐像素核对 + 两轮完整播放
python host/deploy/summarize_board_reports.py --source <原始报告目录>  # 把板端原始 JSON 脱敏汇总
python skill/checks/compare_golden.py --host <board-ip>               # 与黄金参考自动比对
python skill/checks/check_ppa.py --build-dir fpga/src/build/video_effects_output
python skill/checks/verify_repo.py                                    # 交付包自检
```

不同机器**不以毫秒完全相等**作为通过条件：正确性以"逐像素误差为 0""音频采样数与欠载为 0""时序无负裕量"为准，耗时看同口径重复测量的中位趋势。

---

## 5. 实测摘要

完整表格见 [`metrics/metrics.csv`](metrics/metrics.csv)，每行都写了测量条件与证据文件；原始日志在 [`metrics/logs/`](metrics/logs/)。

### 5.1 资源与时序（布线后，100 MHz）

| 资源 / 时序 | 结果 | 器件占比 |
|---|---:|---:|
| Slice LUT | 8,484 | 15.95% |
| 寄存器 | 9,839 | 9.25% |
| BRAM Tile | 138 / 140 | 98.57% |
| DSP | 4 | 1.82% |
| WNS / WHS | +0.202 ns / +0.018 ns | 无负裕量 |
| TNS / THS | 0 / 0 ns | — |

### 5.2 单次滤波调用（320×180，预热 3 次、测量 10 次，逐次与 ARM 参考核对）

| 效果 | ARM 均值 (ms) | FPGA 均值 (ms) | ARM/FPGA | 最大像素误差 |
|---|---:|---:|---:|---:|
| 平滑 | 7.682 | 11.582 | 0.66× | 0 |
| 边缘提取 | 32.228 | 11.535 | 2.79× | 0 |
| 锐化 | 15.505 | 11.670 | 1.33× | 0 |
| 原画直通 | 0.559 | 11.638 | 0.05× | 0 |

口径：**FPGA 侧含边界填充、像素打包、DMA 与结果回拷，不含解码、合成、显示与音频**。
比值 <1 表示该路径在该口径下更慢——所以本作品**不把结论概括为"FPGA 全面加速"**，
而是按项目给出建议：边缘提取与锐化走 FPGA，平滑与原画走 ARM。

### 5.3 音画同步（30 秒同源播放，硬件音频时钟推进）

```text
submitted=1440127 played=1440127 seconds=30.004121 expected=30.002646 underruns=0
```
视频按已播采样调度，未及时渲染则跳帧；HDMI 输出 1280×720 / 60 Hz，画布 640×360 RGB332。

---

## 6. 已知边界

1. **HDMI 物理链路未远程确认**：板端只报告 `output_active`，不检测 EDID 与显示器是否锁到信号。
2. **无光学/声学端到端测量**：同步误差在 HDMI 提交点测量，不含显示器与扬声器时延。
3. **FPGA 并非所有模式更快**：平滑与原画在该口径下更慢，如实保留。
4. **单滤波倍数 ≠ 整段播放倍数**：两类口径分别报告，只有同范围数据才算比值。
5. **视频未达 15 FPS 全帧实时**：实测约 7.3–8.4 FPS，丢帧 198–231 / 450。
6. **BRAM 只剩 2 个 Tile**：再加帧缓存或滤波通道前应先改存储结构（外部 DDR 或流式行缓存）。
7. **音频实际采样时钟未独立测量**：靠硬件 FIFO 的采样数与秒数对账。
8. **参数不可在线任意调节**：滤波器只有固定预设（800 / 3000 / 800–2500 Hz）。
9. **网页无认证**：仅适用于本地实验网络，不应直接暴露到公网。
10. **DRC 未清零**：6 项非致命告警/提示保留在 `fpga/report/drc.rpt`。

---

## 7. 第三方与许可

- 本项目自写代码采用 BSD-3-Clause，见 [`LICENSE`](LICENSE)。
- `fpga/src/vendor/` 中的 Digilent / Xilinx / PYNQ IP 保留原始版权声明，
  来源提交、文件哈希与本地改动记录在 `*_provenance.json`，汇总见 [`third_party_notices.md`](third_party_notices.md)。
- `fpga/build/audio_live.bit` 是构建产物：公开源代码不等于授予 Vivado / Vitis 工具或 Xilinx 器件之外的任何使用许可。
- 素材（音乐、MV、上传视频、摄像头画面）**不在仓库中**，使用者需自备并自行确认授权。

# 第三方文件与来源声明

本仓库的 `LICENSE`（BSD-3-Clause）只覆盖本队自行编写的文件。下列第三方文件保留其原始版权与许可，逐文件校验值记录在对应的 provenance 文件里。

## 1. 随仓库分发的第三方源码

- `fpga/src/vendor/audio_fifo_ctrl_v1.0/` —— PYNQ/Xilinx 音频 codec 控制 IP 源码。`src/user_logic.vhd` 是本队构建使用的本地变体，其余文件与钉住的 PYNQ 提交一致。许可见 `fpga/src/vendor/LICENSE_PYNQ.txt`，来源提交与逐文件 SHA-256 见 `fpga/src/vendor/audio_provenance.json`。
- `fpga/src/vendor/rgb2dvi_v1_2/` —— Digilent RGB-to-DVI 编码 IP，各源文件保留原始 BSD-3-Clause 头。来源与哈希见 `fpga/src/vendor/hdmi_provenance.json`。
- `fpga/src/vendor/hdmi_audio.xdc` —— 由 PYNQ-Z2 板定义派生的 HDMI/音频引脚约束。最终构建不需要完整的官方板级 XDC 与 base overlay，因此不再分发。

## 2. 不再分发、仅记录来源的第三方内容

- **PS7 配置预设**：`fpga/src/scripts/ps7_preset.tcl` 提取自官方 PYNQ-Z2 base 设计中的 `ps7_0` 属性（`CONFIG.PCW_*`，>400 条），来源为
  `https://raw.githubusercontent.com/Xilinx/PYNQ/master/boards/Pynq-Z2/base/base.tcl`。提取脚本为 `fpga/src/scripts/extract_ps_preset.py`，需要使用者自行下载该 base.tcl 后运行；仓库不再分发原始 base.tcl。
- 仓库中不含 Xilinx Vitis Vision / Vitis Libraries 或 PYNQ 官方 overlay 的源码副本。

## 3. 工具与运行环境

Xilinx/AMD Vivado、Vitis HLS、PYNQ、NumPy、OpenCV、Pillow、imageio-ffmpeg 均为各自所有者的软件，本仓库不再授权，也不随仓库分发。构建产物 `fpga/build/audio_live.bit` 由 Vivado 生成：**公开源代码不等于授予 Vivado/Vitis 工具或 Xilinx 器件以外的任何使用许可**。

## 4. 被明确排除的第三方内容

- 用户提供的音乐、MV、上传图片及其派生物（PCM 片段、抽帧截图、内嵌媒体的单文件启动器）**均不在仓库中**，需要使用者自备并自行确认授权。
- 浏览器界面截图（`report/figures/board_live_ui.png`）只包含本工程的合成测试画面（生成色块与文字），不含第三方影像内容。
- 原始板端测量 JSON 中的媒体文件名与标题在入库前已被 `host/deploy/summarize_board_reports.py` 删除。

再分发本仓库中的构建产物时，请保留本节与各 provenance 文件。

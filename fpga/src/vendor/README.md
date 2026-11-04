# Third-party IP used by the final build

本目录只保留**最终构建真正用到**的第三方源码，来源、提交与逐文件 SHA-256 记录在 provenance 文件里。这些文件保留其原始版权声明，不受本仓库 LICENSE 覆盖。

## 1. `audio_fifo_ctrl_v1.0/` — PYNQ/Xilinx 音频 codec 控制 IP

| 项 | 值 |
|---|---|
| 仓库 | `https://github.com/Xilinx/PYNQ` |
| 提交 | `e054c09c52db3244ef35c8ae08a2e62c1e4955fd` |
| 许可 | BSD-3-Clause，见 [`LICENSE_PYNQ.txt`](LICENSE_PYNQ.txt) |
| 本地改动 | `src/user_logic.vhd` 是本队构建使用的本地变体（其余文件与钉住的 PYNQ 源一致） |
| 哈希记录 | [`audio_provenance.json`](audio_provenance.json) |

用途：驱动 ADAU1761 codec、产生 10 MHz codec 时钟、经 PS I2C1 EMIO 配置寄存器，并向 I2S 串行器提供采样流。

## 2. `rgb2dvi_v1_2/` — Digilent RGB-to-DVI/TMDS 编码 IP

| 项 | 值 |
|---|---|
| 仓库 | `https://github.com/Xilinx/PYNQ` |
| 提交 | `e054c09c52db3244ef35c8ae08a2e62c1e4955fd` |
| 许可 | Digilent BSD-3-Clause（各源文件头部保留） |
| 哈希记录 | [`hdmi_provenance.json`](hdmi_provenance.json) |

用途：把 720p60 的 RGB 像素流转成 TMDS 差分输出。本设计**停用了它自带的 generated-clock XDC**（像素时钟由工程的 clock wizard 产生并约束），其余时序/IO 约束保留。

## 3. `hdmi_audio.xdc` — 板级引脚约束

从 PYNQ-Z2 板定义派生的 HDMI/音频相关引脚约束。完整的官方板级 XDC 与 base overlay 不由本仓库再分发。

## 4. `ps7_preset.tcl`（在 `../scripts/`）— PS7 配置预设

| 项 | 值 |
|---|---|
| 来源 | `https://raw.githubusercontent.com/Xilinx/PYNQ/master/boards/Pynq-Z2/base/base.tcl` |
| 提取方式 | [`../scripts/extract_ps_preset.py`](../scripts/extract_ps_preset.py) 只抽取 `ps7_0` 的 `CONFIG.PCW_*` 属性（>400 条），写出 [`../scripts/ps7_preset.tcl`](../scripts/ps7_preset.tcl) |
| 复现 | 需要自行下载上述 base.tcl 到 `fpga/src/vendor/pynq_z2_base.tcl` 后运行该脚本；文件本身不再分发 |

它保证 DDR、MIO、时钟与 PLL 设置与官方 PYNQ-Z2 base 设计一致——这是"只启用本作品需要的 PL 接口"这一软硬件划分的前提。

## 5. 其他依赖

Xilinx Vivado/Vitis、PYNQ、NumPy、OpenCV、Pillow、imageio-ffmpeg 均为各自所有者的软件，本仓库不再授权。构建产物 `../fpga/build/audio_live.bit` 的使用仍受工具与器件许可约束。

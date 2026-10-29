# 运行环境说明（赛题 3.2.5.2「运行环境说明」项）

> 本文列出实际使用的版本，供环境重建使用。

## 1. 板卡与器件

| 项 | 值 |
|---|---|
| 板卡 | PYNQ-Z2（TUL） |
| 器件 | XC7Z020CLG400-1（Zynq-7000，双核 Cortex-A9 + Artix-7 85K LC） |
| 内存 / 存储 | 512 MB DDR3 / microSD（PYNQ 3.1 镜像） |
| PL 主时钟 | 100 MHz（视频像素路径与 AXI-DMA 同域） |
| 功耗模式 | 板卡常压供电，无 DVFS 调频；PL 时钟固定 100 MHz |

## 2. 板卡侧软件

| 项 | 版本 / 说明 |
|---|---|
| 操作系统 | Ubuntu 22.04（PYNQ 3.1 镜像自带） |
| PYNQ | `pynq` 3.1.1（Release 3.1） |
| Python | 镜像自带（3.10） |
| 依赖 | `numpy`、`opencv-python`（镜像自带）；`alsa-utils`（USB 麦克风采集需要 `arecord`） |
| 音频驱动 | ALSA；板载 codec 走官方 PYNQ 设备树，PS I2C1 经 EMIO |
| 摄像头驱动 | V4L2 / UVC 免驱 |
| 服务端口 | 8080（作品 HTTP 服务）、9090（Jupyter） |

## 3. 主机侧软件（构建与打包）

| 项 | 版本 |
|---|---|
| Vivado | 2024.1（需 XC7Z020 器件文件） |
| Vitis HLS | 2024.1 |
| 操作系统 | Windows 10/11 或 Linux（构建脚本两套：`build_all.ps1` / `build_all.sh`） |
| Python | 3.8+ |
| Python 依赖 | 见根目录 `requirements.txt`：`numpy>=1.24,<2`、`opencv-python>=4.8,<5`、`Pillow>=10,<12`、`imageio-ffmpeg>=0.5,<1` |
| 其他 | `gcc`（板端现场编译 `reference.c`；主机侧跑 `fpga/src/sim` 的 C 测试也用它） |

## 4. 关键版本对结果的影响

| 版本 | 影响 |
|---|---|
| Vivado / Vitis HLS 2024.1 | 资源与 WNS 与 `fpga/report/` 中的报告对应；换版本后 LUT/FF 与裕量会变，报告需重出 |
| PYNQ 3.1.1 | `mem_dict` / `ip_dict` 的划分与本文档一致；换镜像后需重新确认 overlay 是否配套（`fpga/src/board/check_hardware.py` 会在加载前拒绝不配套的 HWH） |
| numpy < 2 | 板上与主机侧都用 1.x；升到 2.x 需重新核对 `audio_benchmark.py` 等脚本的整数行为 |
| OpenCV 4.8+ | ARM 参考实现的所有权重大小与边界处理依赖 OpenCV 的 `Sobel`/`borderType` 语义 |

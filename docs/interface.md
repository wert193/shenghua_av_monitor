# 接口定义：寄存器映射、AXI 接口、HTTP 报文与时序约定

本系统有三段接口：**浏览器 ↔ 板端（HTTP）**、**PS ↔ PL（AXI-Lite / AXI-Stream / AXI-DMA）**、
**像素与音频码流（数据格式契约）**。三段都以"ARM 侧实现"为唯一数值标准。

---

## 1. PS ↔ PL：寄存器映射

### 1.1 `video_smooth_router`（视频滤波 / 音频旁路路由）

控制字 `config_word` 由板端驱动经 AXI-Lite 写入：

| 位域 | 名称 | 含义 |
|---|---|---|
| `[31]` | `video_mode` | `1` = 视频 3×3 滤波；`0` = 音频旁路（`S_AXIS→AUDIO_IN`、`AUDIO_OUT→M_AXIS` 直通） |
| `[21:20]` | `effect` | `0` 平滑、`1` 边缘提取、`2` 锐化、`3` 原画直通 |
| `[9:0]` | `width` | 显示区域宽度（像素），用于行计数判边界 |

数值约定（**ARM 实现是唯一标准**）：

| 效果 | 运算 | 舍入 / 饱和 |
|---|---|---|
| 平滑 | binomial 3×3 `[[1,2,1],[2,4,2],[1,2,1]]/16` | 累加后 `+8` 再 `>>4` |
| 边缘提取 | `gray=(29R+150G+77B+128)>>8`，Sobel `Gx`/`Gy`，`(|Gx|+|Gy|+2)>>2` | 饱和到 255 |
| 锐化 | 中心增强 `5·c − t − b − l − r` | 饱和到 `[0,255]` |
| 边界 | **复制边界，填充由 ARM 侧完成**：输入 `w+2 × h+2`，输出 `w × h` | RTL 内部不处理越界 |

### 1.2 `audio_fir`（Vitis HLS 生成的 IP，`shenghua.org:audio:audio_fir:1.0`）

接口：`s_axi_control` + `S_AXIS` + `M_AXIS`。

| AXI-Lite 偏移 | 名称 | 说明 |
|---|---|---|
| `0x00` | `control` | bit0 `ap_start`、bit1 `ap_done`、bit2 `ap_idle`、bit3 `ap_ready` |
| `0x10` | `sample_count` | 本次交易的样本数 |
| `0x18` | `mode` | `0` 低通 800 Hz、`1` 高通 3000 Hz、`2` 带通 800–2500 Hz、`3` 原样延时 127 |
| `0x20` | `clear_history` | `1` = 清零 256 样本环形历史 |

- 传输字是**符号扩展的 32 位**；驱动把 PCM16 提升到 `int32`，DMA 长度按 `n×4` 字节编程。
- **模式在一次交易内固定**；960 样本线性交叉淡化在板端完成，IP 内部不做淡化。
- 只有一个输出字带 `TLAST`（HLS 标注），因此 **`TLAST` 是"交易结束"的硬判据**。
- 累加不舍入，最后一次 `(sum + 16384) / 32768` 后饱和；255 抽头线性相位，群延时 127 样本。

### 1.3 `audio_fifo_arch`（硬件播放 FIFO）

| 项 | 值 |
|---|---|
| 深度 | 8192 样本（单声道 PCM16） |
| 消耗节拍 | 48 kHz 采样帧率（由 PL 时钟分频产生） |
| 寄存器签名 | `0x53414631`（用于确认 overlay 与驱动配套） |
| 欠载 | 记录并推进计数，会话结束时按 `submitted / played / seconds / expected / underruns` 对账 |
| 寄存器偏移 | 见 `fpga/src/rtl/audio_fifo_arch.vhd` 实体端口与 `host/app/pcm_fifo_sink.c` 生产者实现 |

### 1.4 地址映射（来自最终构建的 HWH）

| IP / 区域 | 基地址 | 大小 | 备注 |
|---|---|---|---|
| `screen_bram` | `0x42000000` | 512 KiB | HDMI 帧缓冲；HWH 中 `MEMTYPE=MEMORY`，**位于 `mem_dict` 而非 `ip_dict`** |
| `screen_control` | `0x41260000` | 4 KiB | 缓冲确认 / 换页控制 |
| `audio_fir_0`、`axi_dma_0` | 由 HWH 分配 | — | 板端从 `overlay.ip_dict` 取地址，不写死 |
| 音频 codec 控制器 | `0x43c00000` | — | 沿用官方 PYNQ 设备树地址，PS I2C1 走 EMIO |

---

## 2. 数据格式

| 数据 | 格式 | 约束 |
|---|---|---|
| 音频输入 / 输出 | PCM16 单声道、小端、48 kHz 标称 | 单块 ≤ 8192 样本（监控路径） |
| 音频传输字 | `int32`（PCM16 符号扩展） | DMA 长度 `n×4` 字节 |
| 视频像素 | BGR888 打包成 32 位：`R \| G<<8 \| B<<16` | `TKEEP = 4'hf` |
| 处理区尺寸 | ≤ 320×240 | 大于该尺寸的静态图按 318×238 核心 + 1 像素 halo 分块 |
| HDMI 画布 | 640×360 RGB332，双缓冲 | 扫描输出 1280×720@60 |
| 网页预览 | JPEG，质量 75 | 监控单帧 ≤ 512 KB（浏览器回传时） |
| 上传视频 | 任意 OpenCV 可解封装格式 | ≤ 100 MB |
| 上传图片 | JPEG / PNG | ≤ 10 MB，且 `w×h ≤ 16,000,000` |

---

## 3. 浏览器 ↔ 板端：HTTP 接口（默认 :8080）

### 3.1 页面

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 素材评测页 |
| GET | `/monitor` | 实时监控页 |
| GET | `/api/status` | 全量状态 JSON（视频、音频、监控、测量、HDMI、按键） |
| GET | `/api/export` | 导出测量记录 JSON（附件下载） |
| GET | `/video/live.jpg` | 最近一帧处理后的画面 |
| GET | `/image/original.jpg` | 当前原图 |
| GET | `/api/monitor/devices` | 可选采集设备列表 |
| GET | `/api/monitor/waveform` | 监控波形数据 |

### 3.2 素材评测：视频 / 图片

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/video/upload` | 上传现场视频（multipart） |
| POST | `/api/video/start`、`/api/video/stop` | 开始 / 停止逐帧处理与播放 |
| POST | `/api/video/mode` | 切换效果：`smooth` / `edge` / `sharpen` / `original` |
| POST | `/api/video/backend` | 切换通道：`ARM` / `FPGA` |
| POST | `/api/image/upload`、`/api/image/mode`、`/api/image/backend` | 图片素材的同名操作 |
| POST | `/api/av/start`、`/api/av/stop` | 音画同步播放（HDMI 画面 + 板载音频） |

### 3.3 素材评测：音频

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/audio/start`、`/api/audio/stop` | 开始 / 停止板载音频输出 |
| POST | `/api/audio/mode` | `0` 低通、`1` 高通、`2` 带通、`3` 原曲延时对齐 |
| POST | `/api/audio/source` | 换成上传视频内嵌的音轨 |
| POST | `/api/audio/source/default` | 恢复默认示例音轨 |

### 3.4 实时监控

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/monitor/start`、`/api/monitor/stop` | 启动 / 停止监控会话 |
| POST | `/api/monitor/frame` | 浏览器回传一帧 JPEG（≤ 512 KB） |
| POST | `/api/monitor/audio` | 浏览器回传一段 PCM16（≤ 8192 样本） |
| POST | `/api/monitor/preset` | 下发六项通道选择（来自素材评测的"方案确认"） |
| POST | `/api/monitor/audio_output` | 板载音频输出开关 |
| POST | `/api/monitor/usb/start`、`/api/monitor/usb/stop` | 直接用板载 UVC 摄像头 + USB 麦克风采集 |

### 3.5 测量

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/benchmark/video` | 对视频抽帧做 ARM / FPGA 单滤波测量 |
| POST | `/api/benchmark/video-effects` | 对四种效果逐一遍历测量 |
| POST | `/api/benchmark/video-upload` | 对上传视频抽帧测量 |
| POST | `/api/benchmark/image`、`/api/benchmark/arm` | 图片单滤波 / 纯 ARM 基线 |
| POST | `/api/benchmark/rounds/start`、`/api/benchmark/rounds/stop` | 完整播放分轮测量 |

请求体统一为 JSON（`Content-Type: application/json`），上传类为 `multipart/form-data`；
响应统一为 JSON，错误以 HTTP 4xx/5xx + `{"error": "..."}` 返回。
状态字段示例：

```json
{
  "video": {"status": "playing", "backend": "FPGA", "mode": "edge",
            "frame": 128, "frames_total": 450, "fps": 8.3,
            "filter_ms": 12.37, "display_ms": 29.8, "dropped": 201},
  "audio": {"status": "running", "mode": 0, "backend": "ARM",
            "compute_ms": 15.2, "played": 1440127, "underruns": 0},
  "hdmi": {"status": "output_active", "format": "1280x720 / 60 Hz"}
}
```

---

## 4. 时序约定

| 约定 | 值 / 规则 |
|---|---|
| PL 主时钟 | 100 MHz（视频像素路径与 AXI-DMA 同域） |
| 音频采样率 | 48 kHz 标称；播放进度只认硬件 FIFO 的已播采样计数 |
| 音频块 | 一次交易内模式固定；块间环形历史连续（256 样本） |
| 模式切换 | 960 样本（约 20 ms）线性交叉淡化；过渡中再切从当前混合值出发 |
| 视频帧 | 逐帧独立；`TLAST` 标记帧结束，`TKEEP=0xf` |
| HDMI | 1280×720@60 扫描，画布 640×360 RGB332 双缓冲，换页由 `screen_control` 确认 |
| DMA 轮询 | 有界轮询 + 超时；音频块与视频帧由同一把锁串行化，避免交叉污染 |
| 音画同步 | 音频为时钟源；视频按已播采样调度，来不及时跳帧并累计 `dropped` |

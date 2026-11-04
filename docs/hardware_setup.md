# 硬件与外设：清单、接线、供电与复原

## 1. 器件与外设清单（BOM）

| # | 器件 | 型号 / 规格 | 数量 | 作用 |
|---|---|---|---|---|
| 1 | 开发板 | **PYNQ-Z2（TUL）**，XC7Z020CLG400-1，512 MB DDR3 | 1 | ARM PS + FPGA PL 主控 |
| 2 | microSD 卡 | ≥ 16 GB，Class 10 | 1 | 烧录 PYNQ 3.1（Release 3.1）镜像 |
| 3 | USB 摄像头 | UVC 免驱（代码中实测为 Hikvision DE-UVC12 一类复合设备） | 1 | 现场画面采集（V4L2） |
| 4 | USB 麦克风 | UAC 免驱 | 1 | 现场声音采集（ALSA `arecord`）；也可改用板载 HP MIC |
| 5 | HDMI 显示器 | 支持 1280×720@60 | 1 | 外接显示对照画面 |
| 6 | HDMI 线 | 标准 HDMI | 1 | 板卡 HDMI OUT → 显示器 |
| 7 | 网线 | Cat5e 及以上 | 1 | 板卡 ↔ 上位机（HTTP :8080） |
| 8 | 上位机 | 笔记本 / 台式，Windows 10+ 或 Linux | 1 | 浏览器访问、构建、可选摄像头代理 |
| 9 | 耳机 / 有源音箱 | 3.5 mm | 1 | 监听处理后的声音 |
| 10 | micro-USB 线 | 数据 + 供电 | 1 | 板卡供电与串口 |
| 11 | USB HUB（可选） | **带外部供电** | 1 | 摄像头与麦克风同时插入时保证供电 |

**自制部分**：本作品没有自制 PCB、结构件或线束，全部现成模块，因此无 BOM 图纸与机械图；
需要复原的只有上表与第 2 节的接线。

## 2. 接线

```text
                     ┌──────────────┐
   HDMI 显示器 ◄─────┤ HDMI OUT     │
                     │              │
   3.5mm 耳机 ◄──────┤ 音频口       │
                     │  PYNQ-Z2     │
   USB 摄像头 ──────►┤ USB 主机口   │
   USB 麦克风 ──────►┤ （或经带源 HUB）
                     │              │
   上位机 ◄──────────┤ RJ45 千兆网口 │
                     │              │
   5 V 供电 ────────►┤ micro-USB    │
                     └──────────────┘
```

接线顺序建议：先接 HDMI 与音频（执行器）→ 再接 USB 摄像头 / 麦克风（传感器）→ 最后接网线与供电。
USB 摄像头与麦克风同时插入时，若板卡枚举不稳定，改用**带外部供电的 USB HUB**。

## 3. 供电

| 项 | 说明 |
|---|---|
| 板卡供电 | 5 V 经板载 micro-USB（随板 USB 线）。避免用无源 HUB 或劣质线，USB 摄像头启动瞬间电流较大 |
| 外设供电 | 摄像头与麦克风优先插板载 USB 主机口；不足时用带源 HUB |
| 上电顺序 | 接线完成 → 上电 → 等板卡启动（约 40 s）→ 访问 Jupyter（:9090） |
| 断电 | 先停止网页上的运行任务，再断 USB 供电，避免 microSD 写入中断 |

## 4. 网络（二选一）

**方式 A：板卡直连上位机（推荐，现场无路由器时）**

板端 `/etc/network/interfaces.d/eth0`：

```text
auto eth0
iface eth0 inet static
    address <board-ip>          # 例：<网段>.<板卡号>
    netmask 255.255.255.0
    gateway <host-ip>           # 上位机同网段地址
    dns-nameservers 223.5.5.5
```

上位机网卡设为同网段静态地址（如 `<host-ip>/24`），浏览器访问 `http://<board-ip>:8080`。

**方式 B：板卡与上位机同接一台路由器**，板端 DHCP 获取地址，从路由器管理页查到 IP 后访问。

PYNQ 3.1 是 Ubuntu 22.04，网络可能由 netplan 或 NetworkManager 管理；
改配置前先执行 `ip addr`、`ip route`、`cat /etc/resolv.conf` 确认现状，不要照抄网上的配置。

## 5. 复原步骤（从零到跑通）

1. **烧卡**：把 PYNQ 3.1 镜像写入 microSD，插卡上电。
2. **接线**：按第 2 节接 HDMI、音频、USB 摄像头/麦克风、网线、供电。
3. **联网**：按第 4 节配好板端地址，上位机能 `ping` 通。
4. **确认板端环境**：

   ```text
   # 板卡 Jupyter 里执行
   import pynq; print(pynq.__version__)          # 期望 3.1.1
   import cv2, numpy; print(cv2.__version__, numpy.__version__)
   ```

   USB 麦克风需要 `arecord`：`sudo apt install -y alsa-utils`，用 `arecord -l` 确认设备号。
5. **放入 overlay 与启动器**：把 `fpga/build/audio_live.bit`、`audio_live.hwh` 与
   `host/deploy/package_live.py` 生成的单文件启动器一起上传到板卡 Jupyter 根目录
   （`package_live.py` 会把 overlay、Python 模块、网页一起内嵌进启动器，避免逐个传文件）。
6. **启动**：`%run ./start_shenghua_video_effects_avsync.py`，看到 `ready on port 8080` 即可。
7. **验证**：浏览器打开 `http://<board-ip>:8080` 与 `/monitor`，按 `docs/demo_guide.md` 操作。

## 6. 复原自检清单

| 检查 | 期望 |
|---|---|
| 板卡 Jupyter 可访问 | `:9090` 打开 |
| 作品服务启动 | 日志出现 `ready on port 8080` |
| `/api/status` 可读 | 返回 JSON，含 `video` / `audio` / `hdmi` 字段 |
| HDMI 有画面 | 显示器出现 640×360 画布放大后的左右同屏画面 |
| 音频口有声音 | 播放时耳机能听到滤波后音频 |
| USB 摄像头枚举 | `arecord -l` 有麦克风；`ls /dev/video*` 有设备 |
| 板端时钟 | `timedatectl` 已同步（影响视频容器时间戳，未同步时部分格式解码异常） |

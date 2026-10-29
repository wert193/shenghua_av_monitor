# ⑤ 通用 PYNQ 工程技能（与本队题目解耦）

**适用场景**：任何在 PYNQ 上开发**自定义 Overlay** 的题目——不限于音视频滤波，换算法、换板卡（PYNQ-Z2 / ZU 系列）仍然适用。
**使用方法**：按下面的 8 个阶段推进，每阶段都有"最小动作"与"完成判据"。可直接把判据写进你的自检脚本。
**已验证效果**：本文件的所有条目都来自本队工程的真实失败记录（复位极性、不配套 HWH、`mem_dict`、共享 DMA 竞争、BRAM 撞顶、CDC 例外、口径争议），但已剥离本队算法与文件路径，只保留平台级经验。
**失效条件**：仅覆盖 PYNQ（Linux + Python）流程，不覆盖裸机/Vitis 独立应用；不覆盖纯 HLS 仿真技巧；器件与工具版本升级后需重新确认条目（标注的版本为 Vivado 2024.1 / PYNQ 3.1）。

---

## 阶段 1：把"配置"当成一等公民

**最小动作**：为每一次构建产出一份**配套指纹**：`bit` 的 SHA-256、`hwh` 的 SHA-256、器件型号、工具版本、构建标记文件。

**完成判据**

- 打包/部署脚本能回答："这份 HWH 与这份 bit 是同一次构建吗？"
- 加载前能拒绝已知错误的配置（例如复位极性、地址映射不符）。

**平台要点**

- HWH 决定 IP 名称、地址映射与中断号；与 bit 不配套时症状是"Overlay 能加载、地址能读、写进去不生效"。
- 多轮迭代后目录里会有多个同名产物，**永远不要手工挑文件**，让脚本按指纹取。

## 阶段 2：Overlay 加载与自识别

**最小动作**：写一个 `load_overlay(bit, hwh)` 包装：先校验指纹 → 再加载 → 最后断言必需的 IP 存在。

**完成判据**：缺少任一必需 IP 时**拒绝启动**并打印"缺什么"，而不是运行到一半报 400。

**平台要点**

- 外设可能在 `overlay.ip_dict`，也可能在 `overlay.mem_dict`（HWH 中 `MEMTYPE=MEMORY` 的存储映射对象）。**两本字典都要查**。
- 对没有暴露 `.mmio` 的对象，用 `pynq.MMIO(base_address, size)` 直接映射，地址从 HWH 的 `MEMRANGE` 取并写进断言。
- 同一个 session 里不要并行加载两个 Overlay；换配置前先把上一个应用停干净。

## 阶段 3：寄存器与 DMA 访问模式

**最小动作**：所有 MMIO 轮询加截止时间；所有传输配置加长度/对齐校验；失败路径复位通道并打印状态。

**完成判据**

- 任何"等待完成"的循环都能在 0.5–2 s 内退出，并给出可诊断的寄存器快照。
- 输入的非法参数（长度、地址空间越界、类型）在编程寄存器**之前**就被拒绝。

**平台要点**

- 高层 DMA 封装在通道启动异常时可能无限轮询；把寄存器操作拿回自己手里（用 `ip_dict` 的物理地址 + `MMIO`）通常更可控。
- 传输方向对称：先给接收侧编程地址/长度，再启动发送侧，可避免边角竞态。
- 32 位地址空间的器件（如 Zynq-7000）要注意 `physical_address + length < 2**32`。

## 阶段 4：多任务共享硬件

**最小动作**：为共享资源（DMA、BRAM 端口、加速器实例）定义一把锁与一条清理路径。

**完成判据**：并发发起两个任务时，不会出现"配置被另一个任务改写"的现象（用日志时间戳验证）。

**平台要点**

- 锁的范围要覆盖"配置 → 启动 → 等待 → 取结果 → 清理"**整段**，而不只是启动瞬间。
- 任务结束后把控制字清零，避免下一个任务继承上一个任务的状态。
- 每个异步任务都要有自己的取消与超时路径，并保证在异常时也释放共享资源。

## 阶段 5：时钟、复位与跨时钟域

**最小动作**：为每个时钟域列出时钟来源与约束位置；为每个跨域信号列出同步器结构。

**完成判据**：布线后报告无负裕量（WNS/WHS ≥ 0、TNS/THS = 0），且没有对整段路径的粗放例外。

**平台要点**

- 复位极性必须显式设置并双向核对（IP 配置 + RTL 连接）；"仿真全过、上板不动"的第一怀疑对象就是复位。
- 双级同步器只对**第一阶段**设时序例外，第二阶段保持约束；把同步器在 RTL 里标注出来，方便约束脚本定位。
- 使用厂商 IP 时留意其自带的 generated-clock XDC：若时钟实际由工程内 MMCM/PLL 产生，应停用该 XDC 而保留其余约束。

## 阶段 6：资源预算

**最小动作**：每轮构建后记录 LUT / FF / BRAM / DSP 与上一轮的差值，并把 BRAM 余量写进提交说明。

**完成判据**：在开始新功能前就知道"还剩多少 BRAM / 还剩多少时序裕量"。

**平台要点**

- 大容量存储（帧缓存、大查找表）通常先把 BRAM 用尽；接近上限时小改动也可能布线失败。
- 常见替代路径：外部 DDR、流式行缓存、分布式 RAM、降低位宽（如 RGB332）。
- 新增算子优先"用逻辑换存储"；如果确实需要更多存储，先改存储结构再加功能。

## 阶段 7：板端测量纪律

**最小动作**：为每个性能数字写下**口径字符串**（从哪到哪、包含什么、不含什么），并与数据一起保存。

**完成判据**

- 任意两个数字放在一起比较时，能立刻回答"口径是否相同"。
- 报告里同时存在单算子数据与整链路数据，且**不给跨口径的比值**。

**平台要点**

- 硬件内核的周期数不等于主机侧调用时间：打包、填充、缓存维护、DMA、回拷、锁等待都要算进去。
- 预热 + 多次测量 + P95；整链路测试做多轮；输入用哈希核对。
- 状态寄存器（如"输出有效"）只能说明板端逻辑在动，**不能证明外部设备收到了信号**（显示器、扬声器同理）。

## 阶段 8：交付与恢复

**最小动作**：写一个"一键启动 + 一键停止"的板端入口，停止时恢复到加载前的状态；再写一个交付自检脚本。

**完成判据**

- 崩溃或中断后，能通过一条命令回到可再次运行的状态；恢复失败会**明确报告并要求重启板卡**，而不是假装成功。
- 交付包检查通过：必需文件齐全、无用户媒体、无本机绝对路径/主机名/IP、体积在限内。

**平台要点**

- 单文件启动器方便上传，但**不要把它当作源代码**提交（它通常内嵌了二进制与素材）。
- 生成的缓存、`.pyc`、Vivado 工程目录、原始测量转储一律不进版本库；测量数据先脱敏再入库。

---

## 附：最小板端自检片段（可直接改用）

```python
from pathlib import Path
import hashlib, json
from pynq import Overlay

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load(bit, hwh, fingerprint, required=(), mem_ranges=None):
    """Load an overlay only when it matches the recorded fingerprint."""
    recorded = json.loads(Path(fingerprint).read_text())
    for name, path in (("bit", bit), ("hwh", hwh)):
        if recorded[name] != digest(path):
            raise SystemExit(f"{name} does not match the recorded build fingerprint")
    overlay = Overlay(bit)
    present = set(overlay.ip_dict) | set(overlay.mem_dict)   # both dictionaries matter
    missing = [name for name in required if name not in present]
    if missing:
        raise SystemExit(f"overlay is missing: {missing}")
    for name, (base, size) in (mem_ranges or {}).items():
        entry = overlay.mem_dict.get(name) or overlay.ip_dict.get(name)
        if entry is None:
            raise SystemExit(f"{name} is not mapped by this overlay")
        if entry.get("phys_addr") != base:
            raise SystemExit(f"{name} base address changed: {entry.get('phys_addr'):#x} != {base:#x}")
    return overlay
```

> 说明：真实项目里请把 `bit`/`hwh`/指纹文件的路径参数化，并在恢复路径（`finally`）中把上一次的 Overlay 与服务还原。

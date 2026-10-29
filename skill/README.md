# 技能包（赛题 3.2.5.3）

本目录是可复用的工程技能，不是本作品的说明文档。每一条都写清**适用范围 / 使用方法 / 失效条件 / 已验证的复用结果**，
并且都能指向仓库里真实的产物作为证据。

## 索引

| 文件 | 类型 | 一句话 |
|---|---|---|
| [`prompt-workflows.md`](prompt-workflows.md) | ① 提示词工作流 | 把"做一块板子上的双算力对照"拆成四阶段提示词，含三条硬规则（先定数值契约、先要证据再要结论、不许用"应该可以"） |
| [`templates/`](templates/) | ② 案例模板 | 三份可套用的骨架：工程骨架、报告骨架、脚本骨架（向量生成 / 板端校验 / 测量脱敏） |
| [`checks/`](checks/) | ③ 校验脚本 | 三个可直接运行的检查器：`compare_golden.py`（与黄金参考比对）、`check_ppa.py`（读布线后报告出 PPA）、`verify_repo.py`（交付包自检） |
| [`pitfalls.md`](pitfalls.md) | ④ 踩坑清单 | 复位/加载、DMA 与并发、数值一致性、时序与时钟域、音频与播放五类故障的触发条件与定位步骤 |
| [`pynq-generic.md`](pynq-generic.md) | ⑤ 通用 PYNQ 技能 | 与本题解耦：配置管理、Overlay 加载与自识别、寄存器与 DMA 访问模式、多任务共享硬件、时钟/复位/跨时钟域 |

## 逐条说明

### ① 提示词工作流（`prompt-workflows.md`）

- **适用范围**：用大模型协助"从选型到交付"的嵌入式项目，尤其是需要在 ARM 与 FPGA 之间分工的题目。
- **使用方法**：按四阶段推进——需求与契约 → 数值标准 → 硬件实现 → 测量与报告；每阶段结束要求模型给出"可检查的产物"而不是结论。
- **失效条件**：没有可运行的板卡或没有测量脚本时，"要求证据"这一步会退化成自说自话；此时应先补齐测量脚本。
- **已验证的复用结果**：本仓库的 `host/model/MODEL.md` 数值契约、`metrics/metrics.csv` 的指标行、`report/design_report.md` 的失败分析，
  都是这套流程产出的可检查产物。

### ② 案例模板（`templates/`）

- **适用范围**：新起一个 ARM/FPGA 协同题目时，直接套骨架、脚本与报告三份模板。
- **使用方法**：`project_skeleton.md` 定目录与最小文件清单 → `script_templates.md` 落到三个脚本 → `report_template.md` 定报告章节。
- **失效条件**：题目不含 PL 侧算力、或不需要跨平台复现时，骨架里的 PL 目录与构建脚本会显得冗余。
- **已验证的复用结果**：本仓库目录结构、`host/deploy/` 的三个脚本与 `report/design_report.md` 的章节顺序均来自这套模板。

### ③ 校验脚本（`checks/`）

- **适用范围**：任何"硬件加速 vs 软件参考"的对照项目；`verify_repo.py` 与具体题目无关，只检查交付包体量、隐私与必需文件。
- **使用方法**：

  ```text
  python checks/compare_golden.py --host <board-ip>            # 板端结果与黄金参考逐项比对
  python checks/check_ppa.py --build-dir fpga/src/build/video_effects_output
  python checks/verify_repo.py                                  # 交付包自检
  ```

  提交到 `metrics/scripts/` 的是同一份文件，可直接在提交环境重跑。
- **失效条件**：`compare_golden.py` 依赖板端 HTTP 接口可用；`check_ppa.py` 依赖 Vivado 生成的 `timing.rpt` / `utilization.rpt`，
  没有跑过实现的工程无法使用。
- **已验证的复用结果**：三个脚本在本仓库的最终构建与板端会话上跑过，输出被 `metrics/` 引用。

### ④ 踩坑清单（`pitfalls.md`）

- **适用范围**：PYNQ + 自建 overlay 的常见故障排查。
- **使用方法**：按现象在五类里定位——复位与加载、DMA 与并发、数值一致性、时序与资源、音频与播放；每条给了触发条件与定位顺序。
- **失效条件**：故障来自硬件损坏或镜像本身时，清单只能帮你排除软件侧。
- **已验证的复用结果**：本作品实际踩过并记录的故障（辅助复位极性、DMA 共享锁、`mem_dict` 与 `ip_dict` 混淆、HDMI 无信号）都在清单里有对应条目。

### ⑤ 通用 PYNQ 技能（`pynq-generic.md`）

- **适用范围**：换题目、换板卡仍可用的 PYNQ 工程方法，不绑定音视频。
- **使用方法**：五个阶段依次落地；重点是"把配置当一等公民""Overlay 加载与自识别""多任务共享硬件的加锁与有界轮询"。
- **失效条件**：换成非 PYNQ 的裸机工程（无 Python 运行时）时，Overlay/`ip_dict` 相关部分不适用。
- **已验证的复用结果**：本作品的三层应用结构（`console_app` → `integrated_app` → `video_app`）与 DMA 共享锁设计直接来自该技能。

## 关于"干净环境部署"的说明

本技能包**没有做跨设备、跨场景的迁移实验**，因此不宣称"在干净环境上验证通过"。
可以核实的是：`checks/` 三个脚本只依赖 Python 标准库与 numpy，在一台没装 Vivado 的机器上也能运行
（`check_ppa.py` 需要报告文件，`verify_repo.py` 只需要目录）。

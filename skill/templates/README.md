# 案例模板（templates）

**适用场景**：开一个新题目、或把已有的单算子 demo 整理成可交付工程时，需要"目录怎么分、脚本怎么写、报告怎么组织"的三份现成骨架。
**使用方法**：按 **骨架 → 脚本 → 报告** 的顺序使用（见下方"使用顺序"）。每份模板开头都带元信息块（适用场景 / 使用方法 / 已验证效果 / 失效条件），**先看失效条件再决定要不要套用**；模板里的阈值、字段名、目录名都是示例值，逐条按 `# TODO:` 与实际项目改写。
**已验证效果**：本目录三份模板都由「音视频监控系统」工程反向提炼，并已在原工程中跑通：[`project_skeleton.md`](project_skeleton.md) 对应本仓库的六个顶层目录，[`script_templates.md`](script_templates.md) 对应三类真实脚本，[`report_template.md`](report_template.md) 对应 [`../../report/design_report.md`](../../report/design_report.md)。
**失效条件**：本目录只覆盖"ARM/FPGA 协同 + 下板验证"这一类题目；纯软件项目、不要求数值对账的项目只取报告模板即可。照抄不改必然出错——每个项目的接口路由、字段名、阈值与器件参数都不同。

---

## 1. 三份模板各自管什么

| 模板 | 管的范围 | 不负责 |
|---|---|---|
| [`project_skeleton.md`](project_skeleton.md) | 顶层目录划分、每个目录放什么/谁消费/最小文件清单、三条原则、从 demo 到可交付工程的 6 步改造清单 | 具体算法设计、工具命令、脚本实现 |
| [`script_templates.md`](script_templates.md) | 三类脚本的可复制模板：测试向量生成、板端链路校验、测量脱敏汇总；每类含"必须改哪里"与"通过条件" | 板端应用本体（HTTP 服务、Overlay 与驱动）怎么写 |
| [`report_template.md`](report_template.md) | 报告的十章骨架（每章含"要回答的问题/必填字段/常见漏项"）、两张可直接复制的表格、5 条写作纪律 | 怎样把测量做出来；数据从哪来由前两者决定 |

配套的真实产物可作对照：[`../../fpga/src/sim/data/vectors/vectors.hex`](../../fpga/src/sim/data/vectors/vectors.hex)（向量与黄金值）、[`../../metrics/logs/video_effects_board_check.summary.json`](../../metrics/logs/video_effects_board_check.summary.json)（脱敏实测摘要）、[`../../fpga/report/timing.rpt`](../../fpga/report/timing.rpt) 与 [`../../fpga/report/ppa_evolution.csv`](../../fpga/report/ppa_evolution.csv)（资源与时序证据）。

## 2. 使用顺序（骨架 → 脚本 → 报告）

1. **先建骨架**：用 [`project_skeleton.md`](project_skeleton.md) 建 `build/ board/ data/ fpga/src/ report/ skill/`，把已有文件按"谁消费它"归位，同时把生成物排除出版本库。这一步做完再写代码，返工最少。
2. **再冻结口径**：在骨架的 `report/` 下先写下本次对比**允许改什么、耗时从哪到哪（含什么、不含什么）**，即"计时口径字符串"。脚本与报告都从这句话长出来。
3. **然后写脚本**：按 [`script_templates.md`](script_templates.md) 的顺序——先向量生成器（没有黄金参考就没有正确性判定），再板端校验驱动（断言关键计数），最后脱敏汇总器（原始报告 → 可提交摘要）。
4. **最后写报告**：用 [`report_template.md`](report_template.md) 填空；数据只从 `data/` 与 `metrics/logs/` 取，缺哪个必填字段就回去补测量，**不改数字凑结论**。
5. **回头对账**：报告里每张表都能指到具体文件；骨架里的"最小可用文件清单"逐项勾掉；把本次新踩的坑按"真实发生 + 配一个可重跑检查 + 写明失效条件"补进技能包。

## 3. 每份模板的输入 / 输出 / 验证 / 边界

| 模板 | 你要准备什么 | 产出什么 | 怎么验证它起作用了 | 边界 |
|---|---|---|---|---|
| 骨架 | 现有散落文件清单、评审的提交要求 | 六个顶层目录 + 各目录 `README.md` + 最小文件清单 | 陌生人不问作者就能按 `README.md` 找到源码、向量、实测与报告 | 只适配"PL 出算子、PS 管系统"的题目 |
| 脚本 | 一份独立参考实现、板端 HTTP 接口、原始报告样例 | `vectors.hex`、板端原始 JSON、脱敏摘要 JSON | 向量跑仿真 PASS = 用例数；校验脚本退出码 0 且误差/欠载为 0；摘要无隐私字段 | 假设有参考实现与 HTTP 控制接口 |
| 报告 | 资源/时序报告、实测摘要、口径声明、未验证项 | 十章报告 + 两张表格 | 报告里每个数字都能追到文件；跨口径数据没有算比值 | 评审不要求口径时可精简，但不删未验证项 |

## 4. 必须按实际项目改写的内容

| 位置 | 必须改写的项 | 不改的后果 |
|---|---|---|
| 骨架 | 顶层目录名（若评审规定提交结构，需改名并在顶层 README 给出目录对照表）、最小文件清单 | 与提交要求不符，或交付漏件 |
| 骨架 | `vendor/` 第三方 IP 的来源哈希与本地改动记录 | 许可证合规问题 |
| 向量生成器 | 随机种子、算子/模式列表、`pack()` 的字节序与字宽、边界策略 | 向量与 RTL 不对应：仿真"通过"但上板不一致 |
| 板端校验 | `--host`/环境变量名、端口、**全部 API 路由与请求体字段名**、通过阈值 | 脚本 404，或断言过松把错误数据当合格 |
| 脱敏汇总器 | `DROP_KEYS`、`RENAME_KEYS`、`PATH_PATTERN`、字段裁剪逻辑 | 隐私字段进版本库（路径、主机名、进程号、媒体名、板卡 IP） |
| 报告 | 器件型号、工具版本、时钟频率、资源与时序数字、**每条指标的口径字符串**、未验证项清单 | 数字无法复核；跨口径数据被拿来算比值 |
| 全部 | 示例阈值与示例数字（`0`、`1440127`、`+0.202 ns` 之类） | 把本项目的数字误当成自己项目的预期 |

## 5. 本目录模板 → 仓库真实产物对照

| 模板 | 对应的真实脚本 | 真实产物（可直接打开核对） |
|---|---|---|
| [`script_templates.md`](script_templates.md)（a） | [`../../fpga/build/scripts/video_effects_vectors.py`](../../fpga/build/scripts/video_effects_vectors.py) | [`../../fpga/src/sim/data/vectors/vectors.hex`](../../fpga/src/sim/data/vectors/vectors.hex)、[`../../metrics/logs/rtl_simulation.txt`](../../metrics/logs/rtl_simulation.txt) |
| [`script_templates.md`](script_templates.md)（b） | [`../../host/deploy/check_video_effects_board.py`](../../host/deploy/check_video_effects_board.py) | 板端原始 JSON（板卡上产生，不入库） |
| [`script_templates.md`](script_templates.md)（c） | [`../../host/deploy/summarize_board_reports.py`](../../host/deploy/summarize_board_reports.py) | [`../../metrics/logs/video_effects_board_check.summary.json`](../../metrics/logs/video_effects_board_check.summary.json)、[`../../metrics/logs/full_playback_rounds.json`](../../metrics/logs/full_playback_rounds.json) |
| [`project_skeleton.md`](project_skeleton.md) | —— | 仓库顶层目录与各目录 `README.md` |
| [`report_template.md`](report_template.md) | —— | [`../../report/design_report.md`](../../report/design_report.md)、[`../../report/llm_collaboration.md`](../../report/llm_collaboration.md) |

## 6. 使用这些模板时的常见错误

1. **只改代码不改阈值**：模板里的 `0`、`1440127`、`+0.202 ns` 都是本项目的数字，照抄会让断言形同虚设。
2. **脱敏字段表不重审**：`DROP_KEYS` 是白名单思路，新增字段（新的媒体名、新的日志键）不会自动被删掉，必须逐项核对。
3. **跳过向量直接上板**：没有黄金参考时，上板只能证明"跑起来了"，不能证明"算对了"。
4. **把单算子口径的倍数写进整链路结论**：两个口径的数字不能互相换算，报告里必须分列。
5. **模板引用了不存在的路径**：提交前用 `glob`/`read` 逐个确认引用文件真实存在，不要凭记忆写链接。

## 7. 命名与提交约定

- 目录名与文件名统一小写英文、数字、下划线或连字符；`README.md`、`LICENSE`、`THIRD_PARTY_NOTICES.md` 按通行约定保留大写。中文只出现在文件正文。
- 生成物（Vivado 工程、综合/实现中间目录、打包出的启动器、媒体素材）不进版本库；入库的是**向量、黄金值、脱敏摘要、构建与时序报告**。
- 每份入库数据都要能被复核：向量说明生成命令、摘要说明来源脚本、报告表格写明数据文件。

## 8. 交付前检查清单

- [ ] 六个顶层目录齐备，各 `README.md` 说明本目录放什么、谁消费。
- [ ] `skill/` 内每条经验都有"适用场景 / 使用方法 / 已验证效果 / 失效条件"，且每条配一个可重跑检查。
- [ ] 向量文件入库，仿真 PASS 计数与用例数一致。
- [ ] 板端校验脚本在真板上跑过一次，误差与计数断言全部通过。
- [ ] 脱敏摘要中不含绝对路径、用户名、主机名、板卡 IP、进程号、媒体文件名与标题。
- [ ] 报告十章齐备，两张表格的"口径"列无空缺，未验证项逐条列出。
- [ ] 模板中引用的仓库路径全部真实存在（引用前用 `glob`/`read` 确认，不编造路径）。

> 声明：模板描述的是**一类题目的组织方式与边界**，不构成任何算法或板卡的性能承诺。换题目、换板卡、换工具版本后，请重新做一遍数值一致性与性能测量，并重新审一遍脱敏字段表。

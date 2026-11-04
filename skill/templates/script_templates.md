# 脚本模板（向量生成 / 板端校验 / 测量脱敏）

**适用场景**：ARM/FPGA 协同工程需要补齐三类"可重跑脚本"时——①仿真测试向量生成、②板端整链路验证、③把板端原始报告转成可提交数据；三者分别落在 `fpga/build/scripts/`、`host/deploy/` 与 `metrics/logs/`。
**使用方法**：复制模板到目标仓库，按 `# TODO:` 改成项目事实（导入路径、接口路由、字段名、阈值），**先在本机或仿真上跑通、再上板跑**；每类末尾给出"必须改哪里"与"通过条件"。
**已验证效果**：本仓库三个真实脚本即由这三类模板展开：向量生成见 [`fpga/build/scripts/video_effects_vectors.py`](../../fpga/build/scripts/video_effects_vectors.py) 与产出 [`fpga/src/sim/data/vectors/vectors.hex`](../../fpga/src/sim/data/vectors/vectors.hex)（仿真 PASS 24/24，见 [`metrics/logs/rtl_simulation.txt`](../../metrics/logs/rtl_simulation.txt)）；板端校验见 [`host/deploy/check_video_effects_board.py`](../../host/deploy/check_video_effects_board.py)（两轮播放断言已播样本数与欠载 0）；脱敏汇总见 [`host/deploy/summarize_board_reports.py`](../../host/deploy/summarize_board_reports.py) 与产出 [`metrics/logs/avsync_30s_playback.json`](../../metrics/logs/avsync_30s_playback.json)。
**失效条件**：模板假设存在**一份独立参考实现**能算出黄金期望输出；纯硬件项目可删参考实现字段，但不能删"输入 + 期望输出"结构，否则无法判定正确性。板端校验模板只适用于板上提供 HTTP/JSON 控制接口的工程，走串口或裸机时替换传输层、保留断言结构即可；脱敏模板依赖字段白名单，换项目必须重审字段表，否则会漏掉新的隐私字段。
**风格约定**：与仓库现有脚本一致——紧凑、参数化、带断言；用 `assert` 而不是 `print("警告")`，因为只有断言失败才会返回非零退出码。
**统一命名约定**：`cases` 存放"输入图 → 用例名"，`MODES` 是算子/模式列表，`pack()` 是与 RTL 逐字一致的打包函数，`hexfile()` 是统一落盘方式，`scrub()/summarize()` 是脱敏入口——三类脚本共用这几个名字，方便互相引用。

---

## （a）测试向量生成器

固定随机种子；覆盖退化与极端用例（1×1、1×N、N×1、脉冲边界、饱和值、棋盘）；把"输入 + 黄金期望输出"写成十六进制文本；最后打印用例数并断言。

```python
"""Generate test vectors: packed input + golden expected output, one hex word per line."""
from pathlib import Path
import sys
import numpy as np
root = Path(__file__).resolve().parents[2]             # TODO: 仓库根定位层数
sys.path.insert(0, str(root / "hardware" / "live"))    # TODO: 参考实现所在目录
from image_filters import arm_filter as reference      # TODO: 换成你的参考实现
from image_border import replicate as border           # TODO: 与硬件一致的边界填充
SEED = 73                                              # TODO: 种子一改，向量的每个字都变
MODES = ("smooth", "edge", "sharpen", "original")      # TODO: 算子/模式列表

def load_u8(path, shape):                              # 图像以裸字节入库，免去 OpenCV 依赖
    return np.frombuffer(Path(path).read_bytes(), dtype=np.uint8).reshape(shape)

def pack(frame):
    """BGR888 -> 32-bit word, row-major. TODO: 与 RTL 逐字一致的打包格式。"""
    pixel = frame.astype(np.uint32)
    return (pixel[:, :, 0] | pixel[:, :, 1] << 8 | pixel[:, :, 2] << 16).ravel().tolist()

def hexfile(path, words):
    path.write_text("\n".join(f"{int(v):08x}" for v in words), encoding="ascii")
    print(f"wrote {path}: {len(words)} words")

rng = np.random.default_rng(SEED)
checker = ((np.indices((240, 320)).sum(axis=0) % 2) * 255).astype(np.uint8)   # 棋盘（饱和值）
impulse = np.zeros((7, 9, 3), np.uint8)                                       # 四角为 255 的脉冲
impulse[0, 0] = impulse[3, 4] = impulse[-1, -1] = 255
cases = {rng.integers(0, 256, (15, 13, 3), dtype=np.uint8): "random",         # 随机
         np.full((1, 1, 3), 255, np.uint8): "1x1",                            # 1x1
         np.repeat(checker[:, :, None], 3, axis=2): "checker",                # 棋盘
         impulse: "impulse",                                                  # 脉冲边界
         rng.integers(0, 256, (1, 19, 3), dtype=np.uint8): "1xN",             # 1xN
         rng.integers(0, 256, (17, 1, 3), dtype=np.uint8): "Nx1",             # Nx1
         np.zeros((3, 5, 3), np.uint8): "black",                              # 全黑
         np.full((3, 5, 3), 255, np.uint8): "white"}                          # 全白

paths = [(root / "data" / "vectors" / f"{name}_{mode}_{side}.hex")            # TODO: 入库位置
         for name in cases.values() for mode in MODES for side in ("input", "expected")]
fixtures = [(frame, reference(frame, mode)) for frame in cases for mode in MODES]
for frame, expected in fixtures:                                              # 入参侧走复制填充
    hexfile(paths.pop(0), pack(border(frame, 1)))
    hexfile(paths.pop(0), pack(expected))
assert len(fixtures) == len(cases) * len(MODES) and not paths
print(f"Generated {len(fixtures)} cases ({len(cases)} fixtures x {len(MODES)} modes)")
```

**必须改哪里**：①仓库根定位层数与参考实现导入路径；②`SEED`（种子一改，向量每个字都变，必须重跑仿真并替换向量）；③`MODES` 与文件命名规则；④`pack()` 的字节序与字宽，必须与 RTL 逐字对应；⑤边界填充函数，必须与硬件/PS 侧同一策略；⑥向量入库目录。

**通过条件**：退出码 0；生成用例数等于 `用例数 × 模式数`；每个向量文件每行都是 8 位十六进制的合法字；随即重跑仿真得到 **PASS = 用例数**（新增用例后必须重跑，不接受"只加向量不跑仿真"）。

---

## （b）板端校验驱动

用 `argparse` 接收 `--host`（缺省读环境变量），按 HTTP 接口驱动整条链路，断言关键计数，最后把**原始** JSON 写到指定目录（脱敏是下一类脚本的事）。

```python
"""Drive the whole on-board chain over HTTP and assert the key counters."""
import argparse, json, os, time, urllib.request, urllib.error
from pathlib import Path

parser = argparse.ArgumentParser(description="Validate the live chain on the board.")
parser.add_argument("--host", default=os.environ.get("APP_BOARD_HOST"),
                    required=os.environ.get("APP_BOARD_HOST") is None,
                    help="Board address (or set APP_BOARD_HOST).")   # TODO: 环境变量名
parser.add_argument("--port", type=int, default=8080)                # TODO: 端口
parser.add_argument("--rounds", type=int, default=2, help="Playback rounds to run.")
parser.add_argument("--timeout", type=float, default=45.0, help="Seconds per round.")
parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "raw_reports")
args = parser.parse_args()
client = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 绕过系统代理，否则会连到代理
base = f"http://{args.host}:{args.port}"
EXPECTED = {"smooth", "edge", "sharpen", "original"}   # TODO: 期望生效的模式集合

def get(route="/api/status"):
    with client.open(base + route, timeout=10) as response:
        return json.load(response)

def post(route, payload=None):
    request = urllib.request.Request(base + route, json.dumps(payload or {}).encode(),
                                     {"Content-Type": "application/json"})
    try:
        with client.open(request, timeout=args.timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:             # 保留板端错误正文，便于定位
        raise RuntimeError(error.read().decode("utf-8", errors="replace")) from error

state = get()                                           # 1. 前置条件：状态自洽
assert (state["backend"]["status"], state["pipeline"]["status"]) == ("idle", "idle"), state
validation = post("/api/benchmark/effects")             # 2. 正确性：TODO: 换成你的基准接口
assert validation["passed"], validation
for mode in validation["modes"]:
    assert mode["max_error"] == 0, mode                 # 核心断言：不允许"接近 0"
    assert mode["reference_ms"] > 0 and mode["hardware_ms"] > 0, mode
post("/api/pipeline/backend", {"backend": "hardware"})  # 3. 整链路播放，多轮
post("/api/pipeline/mode", {"mode": "edge"})
rounds, seen = [], set()
for index in range(args.rounds):
    post("/api/pipeline/start"); began = time.monotonic(); samples = []
    plan = [(8, "/api/pipeline/mode", {"mode": "sharpen"}),          # TODO: 轮内切换时间表
            (16, "/api/pipeline/mode", {"mode": "smooth"})]
    while time.monotonic() - began < args.timeout:
        sample = get(); samples.append(sample); elapsed = time.monotonic() - began
        assert sample["pipeline"]["status"] != "error", sample       # 任一环节报错立即失败
        for step in list(plan):
            if elapsed >= step[0]:
                post(step[1], step[2]); plan.remove(step)
        if sample["pipeline"]["frame"] > 10:
            seen.add(sample["pipeline"]["mode"])
        if elapsed > 2 and sample["pipeline"]["status"] == "ended":
            break
        time.sleep(0.5)
    clock = sample["clock"]
    assert clock["underruns"] == 0, clock                            # 欠载必须为 0
    assert clock["played"] == clock["expected"], clock               # 用已播数对账，不用提交数
    rounds.append({"final": sample, "samples": samples})
    print(f"ROUND {index} {clock['last_log'].strip()} seen={sorted(seen)}", flush=True)
assert seen == EXPECTED, seen                            # 轮内切换确实生效
args.out.mkdir(parents=True, exist_ok=True)              # 4. 落原始 JSON，脱敏交给下一个脚本
(args.out / "board_check_raw.json").write_text(
    json.dumps({"validation": validation, "rounds": rounds}, ensure_ascii=False, indent=2),
    encoding="utf-8")
print(f"PASS: max_error=0 in all modes; played==expected; underruns=0 -> {args.out}")
```

**必须改哪里**：①环境变量名、默认端口、轮数与超时；②`/api/benchmark/effects` 等**全部路由与请求体字段名**（必须换成板端真实接口，否则一跑就 404）；③`EXPECTED` 与通过阈值：误差 0、欠载 0、播放样本数与期望值的具体数字或字段名；④轮内切换时间表；⑤原始报告输出目录与文件名；⑥若板端返回多层级字段，把断言路径改到实际层级。

**通过条件**：退出码 0；每个模式 `max_error == 0`；每轮 `underruns == 0` 且已播样本数与素材期望一致；轮内切换过的模式集合完整；原始 JSON 生成成功。**不把"耗时毫秒数与上次完全相等"作为通过条件**——跨机不要求一致，通过条件以误差、计数与约束裕量为主。

---

## （c）测量脱敏汇总器

读原始板端 JSON，递归删除隐私字段（本机/板端绝对路径、主机名、进程号、媒体文件名与标题、日志路径），把浮点统一到 6 位小数，输出可提交的摘要 JSON。

```python
"""Distill raw board reports into publishable, privacy-scrubbed summaries."""
import argparse, json, re
from pathlib import Path
DROP_KEYS = {"project", "pid", "build_id", "log", "report", "path", "directory", "source_file",
             "media", "media_file", "media_title", "hostname", "events", "error", "progress", "note"}
RENAME_KEYS = {"requested_mode": "mode", "requested_backend": "backend"}  # TODO: 逐项目重审两张表
PATH_PATTERN = re.compile(r"(/home/[^\s\"']*|[A-Za-z]:\\\\?[^\s\"']*|\\\\[^\s\"']*"   # 绝对路径/UNC
                          r"|https?://\d+\.\d+\.\d+\.\d+[^\s\"']*"                   # 板卡 IP
                          r"|/var/log/[^\s\"']*|[^\s\"']*\.(?:log|mp4|mkv|wav|mp3|jpg|png))")
KEEP_FLOAT = 6
LONG_FRACTION = re.compile("\\." + "\\d{%d,}" % (KEEP_FLOAT + 1))    # 小数位超过 6 位即为失败

def scrub(value):
    """Recursively drop private keys, redact paths/IPs/media names, round floats."""
    if isinstance(value, dict):
        return {RENAME_KEYS.get(k, k): scrub(v) for k, v in value.items() if k not in DROP_KEYS}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, float):
        return round(value, KEEP_FLOAT)
    if isinstance(value, str):
        return PATH_PATTERN.sub("<path>", value)
    return value

def summarize(document):
    """TODO: 按你自己的报告形状取块，只留支撑结论的数值，长数组/base64 先裁剪。"""
    final = document.get("final", document)
    return {"clock": scrub(final.get("clock")), "pipeline": scrub(final.get("pipeline")),
            "rounds": [{"round": i, "summary": scrub(item.get("final", item))}
                       for i, item in enumerate(document.get("rounds", []))]}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", action="append", required=True, type=Path,
                        help="Directory holding the raw board report JSON files (repeatable).")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "measurements")
    arguments = parser.parse_args(); arguments.out.mkdir(parents=True, exist_ok=True); written = []
    for directory in arguments.source:
        for raw in sorted(directory.glob("*.json")):
            text = json.dumps(scrub(summarize(json.loads(raw.read_text(encoding="utf-8")))),
                              ensure_ascii=False, indent=2)
            assert not PATH_PATTERN.search(text), raw     # 脱敏失败就不要写文件
            assert not LONG_FRACTION.search(text), raw    # 浮点统一到 6 位小数的断言
            target = arguments.out / (raw.stem + ".summary.json")
            target.write_text(text + "\n", encoding="utf-8"); written.append(target)
            print("wrote", target.name, target.stat().st_size, "bytes")
    assert written, "No raw board reports found; check --source"
```

**必须改哪里**：①`DROP_KEYS` 必须按本项目板端实际字段逐个核对——**漏一个字段就是一次隐私泄露**；②`RENAME_KEYS`：名字带"请求"语义但内容可留的字段；③`PATH_PATTERN`：补上本项目可能出现的路径前缀、媒体扩展名与内网地址形式；④`summarize()`：单文档与多轮列表两种形状要分别取块；⑤`--out` 目标目录；⑥原始报告里若有 base64 图像或长波形数组，在 `summarize()` 里先行裁剪，不要指望脱敏器顺手瘦身。

**通过条件**：退出码 0；每份摘要都写入成功；摘要中**不出现**绝对路径、用户名、主机名、板卡 IP、进程号、媒体文件名与标题（脚本内断言 + 人工抽查双重确认）；所有浮点最多 6 位小数；摘要体积远小于原始报告（典型为原始的百分之一量级），可直接进版本库。

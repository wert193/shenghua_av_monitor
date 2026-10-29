"""Compare a build against the golden reference data committed in data/.

Three independent checks, all of them fail loudly instead of printing a number:

  --audio            Re-run the 255-tap float FIR contract (960-sample linear
                     cross-fade, four banks) in NumPy and compare with
                     fpga/src/sim/data/golden/output.f32 sample by sample.
  --vectors          Validate fpga/src/sim/data/vectors/vectors.hex (structure + every case
                     decodes), and re-derive the expected pixels with the ARM
                     reference when numpy/OpenCV are available.
  --board --host IP  Ask a running board service to compare ARM and FPGA on the
                     same inputs and require a zero maximum error for every mode.

Examples:
    python skill/checks/compare_golden.py --audio
    python skill/checks/compare_golden.py --vectors
    python skill/checks/compare_golden.py --board --host 192.0.2.10
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "data" / "golden"
VECTORS = ROOT / "data" / "vectors" / "vectors.hex"

NTAPS = 255
FADE = 960
MODES = ("lowpass_800", "highpass_3000", "bandpass_800_2500", "original_delay_127")


def fail(message):
    print("FAIL:", message)
    raise SystemExit(1)


def check_audio(tolerance):
    try:
        import numpy as np
    except ImportError:
        fail("numpy is required for --audio (pip install -r requirements.txt)")
    coefficients = GOLDEN / "coefficients.f32"
    inputs = GOLDEN / "input.f32"
    modes = GOLDEN / "modes.u8"
    expected = GOLDEN / "output.f32"
    for path in (coefficients, inputs, modes, expected):
        if not path.is_file():
            fail(f"missing golden file: {path}")

    banks = np.fromfile(coefficients, dtype="<f4")
    if banks.size != 3 * NTAPS:
        fail(f"coefficients.f32 should hold 3x{NTAPS} float32 values, found {banks.size}")
    banks = banks.reshape(3, NTAPS).astype(np.float64)
    mode_sequence = np.fromfile(modes, dtype=np.uint8)
    signal = np.fromfile(inputs, dtype="<f4").astype(np.float64)
    reference = np.fromfile(expected, dtype="<f4").astype(np.float64)
    if not (mode_sequence.size == signal.size == reference.size):
        fail("input.f32, modes.u8 and output.f32 must have the same number of samples")

    # Mode 3 is the unfiltered reference delayed by the linear-phase group delay.
    banks = np.vstack([banks, np.zeros((1, NTAPS))])
    banks[3, (NTAPS - 1) // 2] = 1.0

    active = banks[0].copy()
    history = np.zeros(2 * NTAPS)
    head = 0
    current_mode = 0
    remaining = 0
    produced = np.empty(signal.size)
    for index in range(signal.size):
        head = (head - 1) % NTAPS
        history[head] = history[head + NTAPS] = signal[index]
        target = int(mode_sequence[index])
        if target != current_mode:
            current_mode = target
            remaining = FADE
            step = (banks[target] - active) / FADE
        if remaining:
            active = active + step
            remaining -= 1
            if remaining == 0:
                active = banks[current_mode].copy()
        produced[index] = float(np.dot(active, history[head:head + NTAPS]))

    deviation = np.abs(produced - reference)
    peak = max(float(np.abs(reference).max()), 1e-12)
    worst = float(deviation.max())
    relative = worst / peak
    print(f"audio: {signal.size} samples, modes {sorted(set(mode_sequence.tolist()))}")
    print(f"audio: worst absolute deviation {worst:.3e} ({relative:.3e} of peak {peak:.4f})")
    if relative > tolerance:
        index = int(deviation.argmax())
        fail(f"audio deviation {relative:.3e} exceeds tolerance {tolerance:.1e} at sample {index}")
    print("PASS: audio float FIR contract reproduced within tolerance")


def check_vectors():
    if not VECTORS.is_file():
        fail(f"missing vector file: {VECTORS}")
    words = [int(line, 16) for line in VECTORS.read_text().split()]
    cases = words[0]
    cursor = 1
    decoded = []
    for case_index in range(cases):
        if cursor + 4 > len(words):
            fail(f"case {case_index} header is truncated")
        width, mode, source_len, expected_len = words[cursor:cursor + 4]
        cursor += 4
        if cursor + source_len + expected_len > len(words):
            fail(f"case {case_index} payload is truncated")
        source = words[cursor:cursor + source_len]
        cursor += source_len
        expected = words[cursor:cursor + expected_len]
        cursor += expected_len
        if mode > 3:
            fail(f"case {case_index}: unknown mode id {mode}")
        if (width + 2) == 0 or source_len % (width + 2):
            fail(f"case {case_index}: padded input {source_len} is not a multiple of width+2={width + 2}")
        padded_rows = source_len // (width + 2)
        if padded_rows < 3 or width < 1:
            fail(f"case {case_index}: padded input {padded_rows}x{width + 2} is too small for a 3x3 kernel")
        if expected_len != (padded_rows - 2) * width:
            fail(f"case {case_index}: expected output {expected_len} should equal "
                 f"{(padded_rows - 2) * width} for a {padded_rows - 2}x{width} image")
        decoded.append({"width": width, "mode": mode, "rows": padded_rows - 2,
                        "source": source, "expected": expected})
    if cursor != len(words):
        fail(f"{len(words) - cursor} trailing words after {cases} cases")
    sizes = sorted({(case["width"], case["rows"]) for case in decoded})
    mode_ids = sorted({case["mode"] for case in decoded})
    print(f"vectors: {cases} cases, {len(words)} words, sizes {sizes}, mode ids {mode_ids}")
    print("PASS: vector file structure is consistent")

    try:
        import numpy as np
    except ImportError:
        print("SKIP: numpy not available, expected pixels were not re-derived")
        return
    sys.path.insert(0, str(ROOT / "hardware" / "live"))
    try:
        from image_filters import filter_frame
    except Exception as error:  # OpenCV is only needed for this step
        print(f"SKIP: ARM reference not importable ({error}); expected pixels were not re-derived")
        return

    names = ("smooth", "edge", "sharpen", "original")

    def unpack(values, height, width):
        packed = np.asarray(values, dtype=np.uint32).reshape(height, width)
        frame = np.empty((height, width, 3), np.uint8)
        frame[:, :, 0] = (packed & 0xFF).astype(np.uint8)
        frame[:, :, 1] = ((packed >> 8) & 0xFF).astype(np.uint8)
        frame[:, :, 2] = ((packed >> 16) & 0xFF).astype(np.uint8)
        return frame

    def pack(frame):
        values = frame.astype(np.uint32)
        return (values[:, :, 0] | values[:, :, 1] << 8 | values[:, :, 2] << 16).ravel().tolist()

    mismatched = 0
    for case_index, case in enumerate(decoded):
        padded = unpack(case["source"], case["rows"] + 2, case["width"] + 2)
        inner = padded[1:-1, 1:-1]
        recomputed = pack(filter_frame(inner, names[case["mode"]]))
        if recomputed != case["expected"]:
            mismatch = sum(1 for a, b in zip(recomputed, case["expected"]) if a != b)
            mismatched += 1
            print(f"  case {case_index} ({case['rows']}x{case['width']}, {names[case['mode']]}) "
                  f"differs in {mismatch} of {len(recomputed)} pixels")
    if mismatched:
        fail(f"{mismatched} of {len(decoded)} cases do not match the ARM reference"
             " - the golden vectors, the reference implementation and the RTL disagree")
    print(f"PASS: all {len(decoded)} cases re-derive exactly from the ARM reference")


def check_board(host, timeout):
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://" + host + ":8080"

    def get(route):
        with client.open(base + route, timeout=timeout) as response:
            return json.load(response)

    def post(route, payload=None):
        request = urllib.request.Request(base + route, json.dumps(payload or {}).encode(),
                                         {"Content-Type": "application/json"})
        try:
            with client.open(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            fail(f"{route} returned HTTP {error.code}: {error.read().decode('utf-8', 'replace')}")

    state = get("/api/status")
    modes = state.get("video_fpga_modes")
    if not modes:
        fail("the board service does not report FPGA video modes; is the overlay loaded?")
    print(f"board: FPGA video modes {modes}")
    result = post("/api/benchmark/video-effects")
    if not result.get("passed"):
        fail("board reported a failed effect validation")
    for entry in result["modes"]:
        error = entry.get("max_error")
        arm = entry.get("ARM", {}).get("mean_ms")
        fpga = entry.get("FPGA", {}).get("mean_ms")
        print(f"board: {entry['mode']:<9} max_error={error} ARM={arm:.3f} ms FPGA={fpga:.3f} ms "
              f"ratio={entry.get('speedup'):.2f}")
        if error != 0:
            fail(f"{entry['mode']} differs from the ARM reference by {error}")
        checks = len(entry.get("checks", []))
        if checks < 9:
            fail(f"{entry['mode']} only ran {checks} checks; degenerate cases are missing")
    print("PASS: every FPGA video mode matched the ARM reference exactly")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--audio", action="store_true", help="compare the float FIR golden trace")
    parser.add_argument("--vectors", action="store_true", help="validate the committed RTL vectors")
    parser.add_argument("--board", action="store_true", help="compare ARM and FPGA on a running board")
    parser.add_argument("--host", default=os.environ.get("SHENGHUA_BOARD_HOST"),
                        help="board address for --board (or set SHENGHUA_BOARD_HOST)")
    parser.add_argument("--tolerance", type=float, default=1e-4,
                        help="relative tolerance for --audio (default 1e-4)")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds")
    arguments = parser.parse_args()
    if not (arguments.audio or arguments.vectors or arguments.board):
        arguments.audio = arguments.vectors = True
    if arguments.audio:
        check_audio(arguments.tolerance)
    if arguments.vectors:
        check_vectors()
    if arguments.board:
        if not arguments.host:
            parser.error("--board requires --host or SHENGUA_BOARD_HOST".replace("SHENGUA", "SHENGHUA"))
        check_board(arguments.host, arguments.timeout)


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
# Reproducible build: coefficients -> HLS IP -> Vivado implementation.
# Usage:  bash fpga/fpga/build/build_all.sh [--promote] [--skip-hls]
set -euo pipefail

PROMOTE=0
SKIP_HLS=0
for arg in "$@"; do
    case "$arg" in
        --promote) PROMOTE=1 ;;
        --skip-hls) SKIP_HLS=1 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
FW="$REPO/fpga"
HW="$FW/src"
OUT="$HW/build/video_effects_output"
REPORTS="$REPO/fpga/report"
FINAL="$REPO/fpga/build"
PYTHON="${PYTHON:-python3}"

require() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "$1 was not found on PATH. Add the Vivado/Vitis HLS 2024.1 bin directory first." >&2
        exit 1
    }
}

step() { printf '\n=== %s ===\n' "$1"; }

cd "$REPO"

step "0/5 tool check"
require "$PYTHON"
require vivado
if [ "$SKIP_HLS" -eq 0 ]; then require vitis_hls; fi
echo "repository: $REPO"

step "1/5 FIR coefficient banks"
"$PYTHON" "$HW/scripts/generate_coeffs.py"

if [ "$SKIP_HLS" -eq 0 ]; then
    step "2/5 Vitis HLS: C simulation, synthesis, co-simulation, IP export"
    vitis_hls -f "$HW/scripts/build_hls.tcl"
else
    step "2/5 Vitis HLS skipped (--skip-hls)"
fi

step "3/5 Vivado: synthesize, place, route, write bitstream"
vivado -mode batch -source "$HW/scripts/build_video_effects.tcl"

step "4/5 collect reports"
mkdir -p "$REPORTS"
for name in timing.rpt utilization.rpt drc.rpt; do
    [ -f "$OUT/$name" ] || { echo "missing build report: $OUT/$name" >&2; exit 1; }
    cp -f "$OUT/$name" "$REPORTS/$name"
    echo "collected $name"
done
mkdir -p "$REPORTS/hls"
for pair in "syn:audio_fir_csynth.rpt" "sim:audio_fir_cosim.rpt"; do
    stage="${pair%%:*}"; name="${pair##*:}"
    if [ -f "$HW/build/fir_accel/solution1/$stage/report/$name" ]; then
        cp -f "$HW/build/fir_accel/solution1/$stage/report/$name" "$REPORTS/hls/$name"
        echo "collected hls/$name"
    fi
done

step "5/5 verify and optionally promote"
grep -q "All user specified timing constraints are met" "$OUT/timing.rpt" \
    || { echo "timing constraints are not met; refusing to promote this build" >&2; exit 1; }
for name in audio_live.bit audio_live.hwh BUILD_OK; do
    [ -f "$OUT/$name" ] || { echo "missing build artifact: $name" >&2; exit 1; }
done
echo "timing constraints met, artifacts present"

if [ "$PROMOTE" -eq 1 ]; then
    mkdir -p "$FINAL"
    cp -f "$OUT/audio_live.bit" "$OUT/audio_live.hwh" "$OUT/BUILD_OK" "$FINAL/"
    cp -f "$OUT/timing.rpt" "$OUT/utilization.rpt" "$OUT/drc.rpt" "$FINAL/"
    echo "promoted build to $FINAL"
    echo "remember to refresh metrics/logs and fpga/report/ppa_evolution.csv"
else
    echo "build kept in fpga/src/build/video_effects_output (use --promote to publish it)"
fi

echo
echo "BUILD OK"

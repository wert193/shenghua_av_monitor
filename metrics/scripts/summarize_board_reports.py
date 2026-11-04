"""Distill raw PYNQ board reports into publishable, privacy-scrubbed summaries.

Raw reports written by the live application contain board-local filesystem paths,
process ids, the media file name and the media title. This script keeps the
measurement content, drops those fields, and writes small JSON files into
metrics/logs/ that can be committed.

Usage:
    python host/deploy/summarize_board_reports.py --source <raw-report-dir> [--source ...]

The raw reports themselves are not versioned: they are produced on the board and
collected by hand. See board/README.md for the collection procedure.
"""
import argparse
import json
import re
from pathlib import Path

DROP_KEYS = {
    "project", "pid", "build_id", "log", "report", "path", "directory",
    "source", "media", "events", "error", "progress", "requested_mode",
    "requested_backend", "note",
}
PATH_PATTERN = re.compile(r"(/home/[^\s\"']*|[A-Za-z]:\\\\?[^\s\"']*|\\\\[^\s\"']*|http://\d+\.\d+\.\d+\.\d+[^\s\"']*)")
KEEP_FLOAT = 6


def scrub(value):
    """Recursively drop private keys and board-local paths."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in DROP_KEYS:
                continue
            out[key] = scrub(item)
        return out
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, float):
        return round(value, KEEP_FLOAT)
    if isinstance(value, str):
        return PATH_PATTERN.sub("<path>", value)
    return value


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def measurement_block(document):
    """Return the single-filter-call measurement block of a report."""
    block = document.get("measurement") or document.get("video_correctness") or document.get("validation")
    if block is None:
        for round_item in document.get("rounds", []):
            if isinstance(round_item, dict) and "video_correctness" in round_item:
                block = round_item["video_correctness"]
                break
    return block


def mode_stats(block):
    """Reduce a measurement block to per-mode statistics without raw samples."""
    if block is None:
        return None
    modes = block.get("modes")
    if modes is None:
        modes = [block]
    stats = []
    for mode in modes:
        if not isinstance(mode, dict):
            continue
        entry = {"mode": mode.get("mode"), "max_error": mode.get("max_error"),
                 "passed": mode.get("passed"), "repeats": len(mode.get("times_ms", {}).get("ARM", [])) or block.get("repeats")}
        for side in ("ARM", "FPGA"):
            if isinstance(mode.get(side), dict):
                entry[side] = mode[side]
        if "speedup" in mode:
            entry["arm_over_fpga"] = mode["speedup"]
        checks = mode.get("checks")
        if isinstance(checks, list):
            entry["checks"] = [{"shape": c.get("shape"), "max_error": c.get("max_error")} for c in checks]
        stats.append(entry)
    return {"scope": scrub(block.get("scope")), "warmup": block.get("warmup"),
            "modes": stats, "passed": block.get("passed")}


def round_summaries(document):
    """Reduce playback rounds to their summary dictionaries."""
    rounds = document.get("rounds")
    if not isinstance(rounds, list):
        return None
    out = []
    for index, item in enumerate(rounds):
        if not isinstance(item, dict):
            continue
        summary = item.get("summary") or item.get("final", {}).get("video", {})
        if "final" in item:
            final = item["final"]
            summary = {"audio_clock": final.get("audio", {}).get("clock"),
                       "audio_compute_ms": final.get("audio", {}).get("compute_ms"),
                       "video": {k: final.get("video", {}).get(k) for k in
                                 ("mode", "backend", "fps", "filter_ms", "display_ms",
                                  "frame", "frames_total", "dropped", "synchronized", "sync_error_ms")},
                       "hdmi_frames": final.get("hdmi", {}).get("frames")}
        out.append({"round": index, "summary": scrub(summary)})
    return out


def first_or_self(document):
    return document[0] if isinstance(document, list) else document


def build(source_dir, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    final = source_dir / "video_effects_board_check.json"
    if final.is_file():
        document = load(final)
        payload = {
            "title": "Final board validation of the four video effects (PYNQ-Z2, 2026-10-03)",
            "validation": mode_stats(document.get("validation")),
            "playback_rounds": round_summaries(document),
        }
        target = out_dir / "video_effects_board_check.summary.json"
        target.write_text(json.dumps(scrub(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(target)

    stages = [
        ("video_fpga_before_copy_optimization.json", "before_buffer_copy_optimization"),
        ("video_fpga_board_check.json", "after_buffer_copy_optimization"),
        ("video_effects_board_check.json", "four_effect_build"),
    ]
    evolution = []
    for name, label in stages:
        path = source_dir / name
        if not path.is_file():
            continue
        document = load(path)
        block = measurement_block(document)
        stats = mode_stats(block)
        if not stats:
            continue
        smooth = next((m for m in stats["modes"] if m.get("mode") == "smooth"), stats["modes"][0])
        evolution.append({
            "stage": label,
            "source_report": name,
            "warmup": stats.get("warmup"),
            "repeats": smooth.get("repeats"),
            "max_error": smooth.get("max_error"),
            "ARM": smooth.get("ARM"),
            "FPGA": smooth.get("FPGA"),
            "arm_over_fpga": smooth.get("arm_over_fpga"),
            "scope": stats.get("scope"),
        })
    if evolution:
        target = out_dir / "fpga_video_path_evolution.json"
        target.write_text(json.dumps(scrub({
            "title": "Smooth 320x180 filter call on the FPGA path, before and after the copy/packing rework",
            "stages": evolution,
        }), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(target)

    playback = source_dir / "round_benchmark_board.json"
    three_mode = source_dir / "final_three_mode_rounds.json"
    if playback.is_file() or three_mode.is_file():
        document = first_or_self(load(three_mode if three_mode.is_file() else playback))
        payload = {
            "title": "Whole-playback rounds: ARM first, then FPGA, 30 s each",
            "settings": scrub(document.get("settings")),
            "scope": scrub(document.get("scope")),
            "video_correctness": mode_stats(document.get("video_correctness")),
            "audio_correctness": scrub(document.get("audio_correctness")),
            "rounds": round_summaries(document),
        }
        target = out_dir / "full_playback_rounds.json"
        target.write_text(json.dumps(scrub(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(target)

    avsync = source_dir / "avsync_board_check.json"
    if avsync.is_file():
        document = load(avsync)
        final_state = document.get("final", {})
        payload = {
            "title": "Synchronized 30 s playback driven by the hardware audio clock",
            "wall_seconds": document.get("wall_seconds"),
            "audio_clock": final_state.get("audio", {}).get("clock"),
            "audio_mode": final_state.get("audio", {}).get("mode"),
            "audio_backend": final_state.get("audio", {}).get("backend"),
            "audio_last_log": final_state.get("audio", {}).get("last_log"),
            "video": {k: final_state.get("video", {}).get(k) for k in
                      ("mode", "backend", "fps", "filter_ms", "display_ms", "frame",
                       "frames_total", "dropped", "synchronized", "sync_error_ms")},
            "hdmi": final_state.get("hdmi"),
        }
        target = out_dir / "avsync_30s_playback.json"
        target.write_text(json.dumps(scrub(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(target)

    for path in written:
        print("wrote", path, path.stat().st_size, "bytes")
    if not written:
        raise SystemExit("No raw board reports found in " + str(source_dir))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", action="append", required=True, type=Path,
                        help="Directory holding the raw board report JSON files (repeatable).")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "measurements",
                        help="Output directory for the scrubbed summaries.")
    arguments = parser.parse_args()
    for source in arguments.source:
        build(source, arguments.out)

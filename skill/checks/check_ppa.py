"""Check resource usage, clock frequency and timing margins from Vivado reports.

Reads the routed reports of one build directory and fails when the timing
constraints are not met, when any margin is negative, when a critical DRC
violation exists, or when the numbers disagree with the recorded baseline.

Examples:
    python skill/checks/check_ppa.py
    python skill/checks/check_ppa.py --build-dir fpga/src/build/video_effects_output
    python skill/checks/check_ppa.py --baseline fpga/report/ppa_evolution.csv --stage video_effects
"""
import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESOURCE_NAMES = {
    "Slice LUTs": "lut",
    "Slice Registers": "registers",
    "Block RAM Tile": "bram_tiles",
    "DSPs": "dsp",
}


def fail(message):
    print("FAIL:", message)
    raise SystemExit(1)


def read(path):
    if not path.is_file():
        fail(f"missing report: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def parse_utilization(text):
    resources = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        fields = [field.strip() for field in line.split("|")]
        if len(fields) < 8 or fields[1] not in RESOURCE_NAMES:
            continue
        key = RESOURCE_NAMES[fields[1]]
        if key in resources:
            continue
        try:
            resources[key] = {
                "used": int(fields[2].replace(",", "")),
                "available": int(fields[5].replace(",", "")),
                "percent": float(fields[6]),
            }
        except ValueError:
            continue
    if not resources:
        fail("no resource rows found; is this a Vivado utilization report?")
    return resources


def parse_timing(text):
    constraints_met = "All user specified timing constraints are met." in text
    summary = None
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "WNS(ns)" in line and "WHS(ns)" in line:
            for candidate in lines[index + 1:index + 6]:
                # The row mixes floats and integers: WNS TNS TNSfail TNStotal WHS THS THSfail THStotal ...
                numbers = re.findall(r"-?\d+(?:\.\d+)?", candidate)
                if len(numbers) >= 8:
                    summary = {
                        "wns_ns": float(numbers[0]),
                        "tns_ns": float(numbers[1]),
                        "tns_failing": int(float(numbers[2])),
                        "whs_ns": float(numbers[4]),
                        "ths_ns": float(numbers[5]),
                        "ths_failing": int(float(numbers[6])),
                    }
                    break
            break
    if summary is None:
        fail("could not find the WNS/WHS summary table in the timing report")
    summary["constraints_met"] = constraints_met
    return summary


def parse_drc(text):
    found = re.search(r"Violations found:\s*(\d+)", text)
    violations = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        fields = [field.strip() for field in line.split("|")]
        if len(fields) < 6:
            continue
        if not re.fullmatch(r"[A-Z]+-\d+", fields[1]):
            continue
        violations.append({"rule": fields[1], "severity": fields[2],
                           "description": fields[3], "count": fields[4]})
    return {"reported": int(found.group(1)) if found else len(violations),
            "violations": violations}


def read_baseline(path, stage):
    if not path.is_file():
        fail(f"missing baseline csv: {path}")
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("build") == stage:
                return row
    fail(f"stage '{stage}' not found in {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build" / "final",
                        help="directory holding timing.rpt, utilization.rpt and drc.rpt")
    parser.add_argument("--baseline", type=Path,
                        help="optional ppa_evolution.csv to compare against")
    parser.add_argument("--stage", help="build name inside the baseline csv")
    parser.add_argument("--bram-warn", type=float, default=90.0,
                        help="warn when BRAM usage exceeds this percentage")
    arguments = parser.parse_args()

    directory = arguments.build_dir
    resources = parse_utilization(read(directory / "utilization.rpt"))
    timing = parse_timing(read(directory / "timing.rpt"))
    drc = parse_drc(read(directory / "drc.rpt"))

    print(f"build directory : {directory}")
    print(f"timing          : WNS {timing['wns_ns']:+.3f} ns  WHS {timing['whs_ns']:+.3f} ns  "
          f"TNS {timing['tns_ns']:.3f} ns  THS {timing['ths_ns']:.3f} ns")
    print(f"timing          : constraints met = {timing['constraints_met']}")
    for key in ("lut", "registers", "bram_tiles", "dsp"):
        entry = resources[key]
        print(f"{key:<15}: {entry['used']:>6} / {entry['available']:<6} = {entry['percent']:5.2f}%")
    print(f"drc             : {drc['reported']} violation(s) "
          f"{[v['rule'] + ' ' + v['severity'] for v in drc['violations']]}")

    problems = []
    if not timing["constraints_met"]:
        problems.append("timing constraints are not met")
    if timing["wns_ns"] < 0 or timing["whs_ns"] < 0:
        problems.append("negative setup or hold margin")
    if timing["tns_ns"] < 0 or timing["ths_ns"] < 0:
        problems.append("negative total slack (TNS/THS)")
    if timing["tns_failing"] or timing["ths_failing"]:
        problems.append("failing endpoints remain")
    for violation in drc["violations"]:
        severity = violation["severity"].lower()
        if "critical" in severity or "error" in severity:
            problems.append(f"{violation['rule']} is a {violation['severity']} violation")
    if resources["bram_tiles"]["percent"] > arguments.bram_warn:
        print(f"WARN: BRAM usage {resources['bram_tiles']['percent']:.2f}% leaves only "
              f"{resources['bram_tiles']['available'] - resources['bram_tiles']['used']} tile(s) of headroom")

    if arguments.baseline or arguments.stage:
        if not (arguments.baseline and arguments.stage):
            parser.error("--baseline and --stage must be used together")
        row = read_baseline(arguments.baseline, arguments.stage)
        checks = {
            "lut": resources["lut"]["used"],
            "registers": resources["registers"]["used"],
            "bram_tiles": resources["bram_tiles"]["used"],
            "wns_ns": round(timing["wns_ns"], 3),
            "whs_ns": round(timing["whs_ns"], 3),
        }
        for key, actual in checks.items():
            recorded = float(row[key])
            match = abs(recorded - float(actual)) < (0.0005 if key.endswith("_ns") else 0.5)
            print(f"baseline {key:<12}: recorded {recorded:>10} actual {float(actual):>10} "
                  f"{'ok' if match else 'MISMATCH'}")
            if not match:
                problems.append(f"{key} differs from the recorded baseline")

    if problems:
        for problem in problems:
            print("problem:", problem)
        fail("build does not meet the delivery criteria")
    print("PASS: timing, resources and DRC meet the delivery criteria")


if __name__ == "__main__":
    main()

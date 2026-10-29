"""Self-check the delivery package before publishing it.

Verifies that the repository is complete enough to be reproduced, small enough
to publish, free of machine-specific or personal strings, free of user media,
and that every path name is portable ASCII.

    python skill/checks/verify_repo.py
    python skill/checks/verify_repo.py --root . --max-file-mb 20 --max-total-mb 60
"""
import argparse
import re
import sys
from pathlib import Path

REQUIRED = [
    "README.md",
    "LICENSE",
    "third_party_notices.md",
    "requirements.txt",
    ".gitignore",
    "docs/architecture.md",
    "docs/interface.md",
    "docs/hardware_setup.md",
    "host/model/MODEL.md",
    "host/app/video_app.py",
    "host/deploy/package_live.py",
    "fpga/src/rtl/video_smooth_router.v",
    "fpga/src/rtl/tb_video_effects.v",
    "fpga/src/hls/fir_kernel.cpp",
    "fpga/src/board/reference.c",
    "fpga/src/scripts/build_hls.tcl",
    "fpga/src/scripts/build_video_effects.tcl",
    "fpga/build/build_all.ps1",
    "fpga/build/build_all.sh",
    "fpga/build/audio_live.bit",
    "fpga/build/audio_live.hwh",
    "fpga/build/scripts/video_effects_vectors.py",
    "fpga/report/timing.rpt",
    "fpga/report/utilization.rpt",
    "fpga/report/drc.rpt",
    "fpga/report/ppa_evolution.csv",
    "fpga/report/hls/audio_fir_csynth.rpt",
    "fpga/report/hls/audio_fir_cosim.rpt",
    "metrics/metrics.csv",
    "metrics/logs/video_filter_microbenchmark.csv",
    "metrics/scripts/compare_golden.py",
    "report/design_report.md",
    "skill/README.md",
    "skill/prompt-workflows.md",
    "skill/pitfalls.md",
    "skill/pynq-generic.md",
    "skill/checks/compare_golden.py",
    "skill/checks/check_ppa.py",
]

TEXT_SUFFIXES = {".md", ".py", ".c", ".h", ".cpp", ".tcl", ".v", ".vhd", ".sv",
                 ".js", ".html", ".json", ".csv", ".txt", ".ps1", ".sh", ".template",
                 ".yaml", ".yml", ".xdc", ".gitignore", ".gitattributes"}
FORBIDDEN_PATTERNS = [
    (r"[A-Za-z]:[\\/](?:Users|Documents|FPGA|Xilinx|AMD)[\\/]", "absolute Windows path"),
    (r"/home/xilinx", "board-local filesystem path"),
    (r"\bLAPTOP-[A-Z0-9]+", "build host name"),
    (r"\b192\.168\.\d+\.\d+", "private network address"),
    (r"\bcuit\.edu\.cn", "school identifier"),
    (r"\bkenan\b", "local user name"),
]
MEDIA_SUFFIXES = {".mp4", ".mkv", ".mov", ".mpg", ".mpeg", ".avi", ".mp3",
                  ".wav", ".flac", ".aac", ".m4a", ".webm"}
GENERATED_DIRS = {"__pycache__", ".Xil", "dist", ".pytest_cache", ".venv"}
SKIP_DIRS = {".git"}


def collect(root):
    files = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        files.append(path)
    return files


def tracked_files(root):
    """Return the set of git-tracked relative paths, or None when git is unavailable."""
    try:
        import subprocess
        result = subprocess.run(["git", "-C", str(root), "ls-files"],
                                capture_output=True, text=True, check=True)
    except Exception:
        return None
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--max-file-mb", type=float, default=20.0)
    parser.add_argument("--max-total-mb", type=float, default=60.0)
    arguments = parser.parse_args()
    root = arguments.root.resolve()

    failures = []
    warnings = []

    print(f"repository: {root}")
    missing = [name for name in REQUIRED if not (root / name).is_file()]
    if missing:
        failures.append(f"{len(missing)} required file(s) missing")
        for name in missing:
            print("  missing:", name)
    else:
        print(f"completeness: all {len(REQUIRED)} required files present")

    files = [path for path in collect(root) if path.is_file()]
    total = sum(path.stat().st_size for path in files)
    tracked = tracked_files(root)
    print(f"size: {len(files)} files, {total / 1048576:.1f} MiB total"
          + ("" if tracked is None else f", {len(tracked)} tracked by git"))

    def classify(relative, message):
        """Tracked content is a failure; local-only generated content is a warning."""
        if tracked is None or relative in tracked:
            failures.append(message)
        else:
            warnings.append(message + " (untracked, ignored by .gitignore)")

    if total > arguments.max_total_mb * 1048576:
        failures.append(f"total size {total / 1048576:.1f} MiB exceeds {arguments.max_total_mb} MiB")
    for path in files:
        size = path.stat().st_size
        if size > arguments.max_file_mb * 1048576:
            failures.append(f"{path.relative_to(root)} is {size / 1048576:.1f} MiB "
                            f"(limit {arguments.max_file_mb} MiB)")

    non_ascii = [str(path.relative_to(root)) for path in collect(root)
                 if any(ord(character) > 127 for character in str(path.relative_to(root)))]
    if non_ascii:
        failures.append(f"{len(non_ascii)} path(s) contain non-ASCII characters")
        for name in non_ascii[:10]:
            print("  non-ascii:", name)
    else:
        print("naming: every path is portable ASCII")

    hits = []
    for path in files:
        if path.name == Path(__file__).name:  # this scanner contains the patterns themselves
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in (".gitignore", ".gitattributes"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern, label in FORBIDDEN_PATTERNS:
                if re.search(pattern, line):
                    hits.append(f"{path.relative_to(root)}:{line_number}: {label}")
    if hits:
        failures.append(f"{len(hits)} privacy finding(s)")
        for hit in hits[:20]:
            print("  privacy:", hit)
    else:
        print("privacy: no machine-specific or personal strings found")

    media = [str(path.relative_to(root)).replace("\\", "/") for path in files
             if path.suffix.lower() in MEDIA_SUFFIXES]
    if media:
        for name in media[:10]:
            classify(name, f"media file present: {name}")
    else:
        print("media: no audio/video files are versioned")

    heavy_pcm = [str(path.relative_to(root)).replace("\\", "/") for path in files
                 if path.suffix.lower() in {".s16le", ".pcm"} and path.stat().st_size > 65536]
    for name in heavy_pcm:
        classify(name, f"PCM fixture larger than 64 KiB looks like user media: {name}")

    generated = [str(path.relative_to(root)).replace("\\", "/") for path in collect(root)
                 if path.is_dir() and path.name in GENERATED_DIRS]
    for name in generated:
        warnings.append(f"generated directory present: {name}")
    caches = [str(path.relative_to(root)).replace("\\", "/") for path in files
              if path.suffix in {".pyc", ".pyo"}]
    for name in caches[:10]:
        classify(name, f"compiled artifact present: {name}")

    for name in ("report/design_report.md",):
        text = (root / name).read_text(encoding="utf-8", errors="ignore") if (root / name).is_file() else ""
        if "未验证" not in text and "不宣称" not in text:
            warnings.append(f"{name} does not state its unverified boundaries")

    print(f"summary: {total / 1048576:.1f} MiB, {len(warnings)} warning(s)")
    for warning in warnings:
        print("  warning:", warning)
    if failures:
        print()
        for problem in failures:
            print("problem:", problem)
        print("FAIL: the package is not ready to publish")
        return 1
    print("PASS: the package is complete, portable and publishable")
    return 0


if __name__ == "__main__":
    sys.exit(main())

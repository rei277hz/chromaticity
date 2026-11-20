"""Compare actual playback and drag pixels for the same installed Per-Node Grade."""

import argparse
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import zipfile

from .shader_display_timing import _run_session
from .stack_lut_timing import blender_binary


def run(surface, output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    resources = files(__package__)
    extension = resources / "extension.zip"
    runner = resources / f"{surface}_display_timing_runner.py"
    binary = blender_binary(resources / "blender")
    profile = SimpleNamespace(samples=0, drag_duration=4., interval_ms=50.,
                              capture_interval_ms=5., warmup=.2, timeout=240., playback=True)
    with tempfile.TemporaryDirectory(prefix="pg-playback-") as temporary:
        root = Path(temporary)
        repository = root / "repository"
        package = repository / "perceptual_grade"
        package.mkdir(parents=True)
        with zipfile.ZipFile(extension) as archive:
            archive.extractall(package)
        result = _run_session(profile, binary, runner, resources / "xvfb", repository,
                              output / "session", 0)
    report = {
        "surface": surface, "completed": result["completed"],
        "environment": result.get("environment"), "profile": vars(profile),
        "fixture": result.get("profile"), "controls": result.get("playback_comparison", {}),
        "blender_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "extension_sha256": hashlib.sha256(extension.read_bytes()).hexdigest(),
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    if not result["completed"]:
        log = output / "session" / "native.log"
        native_log = log.read_text(encoding="utf8", errors="replace")[-4000:] if log.exists() else ""
        raise RuntimeError(f"{surface} session failed: {result.get('error')} "
                           f"{result.get('orchestrator_errors')}\n{native_log}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", required=True, choices=("shader", "compositor"))
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    run(args.surface, args.output_dir)


if __name__ == "__main__":
    main()

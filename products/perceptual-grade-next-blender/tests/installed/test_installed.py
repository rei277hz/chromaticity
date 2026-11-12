from importlib.resources import files
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

from .gui_support import configure_software_graphics


_TIMING_SECTIONS = (
    "extension startup",
    "node and ownership setup",
    "parameter and save/load recovery",
    "Stack builds and gestures",
    "concurrency and failure recovery",
    "undo and teardown",
)


def _read_timing_report(path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _add_harness_timings(data, *, setup_seconds, process_seconds, total_seconds):
    timings = data.get("timings")
    if not isinstance(timings, dict):
        return None
    runner_seconds = timings.get("runner_seconds", 0.0)
    timings.update({
        "harness_setup_seconds": round(setup_seconds, 6),
        "blender_process_seconds": round(process_seconds, 6),
        "blender_startup_shutdown_seconds": round(
            max(0.0, process_seconds - runner_seconds), 6,
        ),
        "test_total_seconds": round(total_seconds, 6),
    })
    return timings


def _format_timing_report(timings):
    if timings is None:
        return "No timing report was produced by Blender."
    lines = ["Installed test timings (seconds):"]
    for section in timings.get("sections", ()):
        lines.append(f"  {section['name']}: {section['seconds']:.3f}")
    for name in (
        "runner_seconds", "blender_startup_shutdown_seconds",
        "blender_process_seconds", "harness_setup_seconds", "test_total_seconds",
    ):
        if name in timings:
            lines.append(f"  {name}: {timings[name]:.3f}")
    return "\n".join(lines)


class InstalledExtensionTests(unittest.TestCase):
    def test_extension_hooks_in_blender_background(self):
        test_started = time.perf_counter()
        resources = files("tests.perceptual_grade_blender")
        blender_name = ("Blender.app/Contents/MacOS/Blender" if sys.platform == "darwin"
                        else "blender")
        blender = Path(str(resources / "blender" / blender_name)).resolve()
        runner = Path(str(resources / "runner.py")).resolve()
        with tempfile.TemporaryDirectory(prefix="perceptual-grade-") as temp:
            root = Path(temp)
            repository = root / "repository"
            extension_dir = repository / "perceptual_grade"
            extension_dir.mkdir(parents=True)
            with zipfile.ZipFile(resources / "extension.zip") as archive:
                archive.extractall(extension_dir)

            env = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                                  "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON"}}
            env.update(BLENDER_USER_CONFIG=str(root / "config"),
                       BLENDER_USER_EXTENSIONS=str(root / "extensions"),
                       PYTHONDONTWRITEBYTECODE="1")
            configure_software_graphics(resources, root, env)
            report = root / "report.json"
            setup_seconds = time.perf_counter() - test_started
            process_started = time.perf_counter()
            command = [
                str(blender), "--background", "--factory-startup", "--disable-autoexec",
                "--python-exit-code", "1", "--python", str(runner), "--",
                str(repository), str(report),
            ]
            try:
                result = subprocess.run(
                    command,
                    # Exercise fixed-graph parameter updates, resource ownership,
                    # save/load recovery, and failures in one Blender lifecycle.
                    cwd=root, env=env, capture_output=True, text=True, timeout=600,
                )
            except subprocess.TimeoutExpired as error:
                process_seconds = time.perf_counter() - process_started
                data = _read_timing_report(report)
                timings = (_add_harness_timings(
                    data,
                    setup_seconds=setup_seconds,
                    process_seconds=process_seconds,
                    total_seconds=time.perf_counter() - test_started,
                ) if data is not None else None)
                output = "\n".join(
                    part.decode(errors="replace") if isinstance(part, bytes) else part or ""
                    for part in (error.stdout, error.stderr)
                )
                self.fail(
                    "Blender installed-extension test timed out after 600 seconds\n"
                    + output + "\n" + _format_timing_report(timings)
                )

            process_seconds = time.perf_counter() - process_started
            data = _read_timing_report(report)
            timings = (_add_harness_timings(
                data,
                setup_seconds=setup_seconds,
                process_seconds=process_seconds,
                total_seconds=time.perf_counter() - test_started,
            ) if data is not None else None)
            if data is not None:
                report.write_text(json.dumps(data))
            timing_summary = _format_timing_report(timings)
            print(timing_summary, flush=True)
            output = result.stdout + "\n" + result.stderr
            self.assertEqual(
                result.returncode, 0, output + "\n" + timing_summary,
            )
            self.assertTrue(report.is_file(), output)
            data = json.loads(report.read_text())
            self.assertFalse(data["registered"])
            self.assertEqual(data["blender"], [5, 2, 2])
            self.assertEqual(data["timings"]["unit"], "seconds")
            self.assertTrue(data["timings"]["complete"])
            sections = data["timings"]["sections"]
            self.assertEqual(tuple(item["name"] for item in sections), _TIMING_SECTIONS)
            section_seconds = tuple(item["seconds"] for item in sections)
            self.assertTrue(all(
                isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
                for value in section_seconds
            ), section_seconds)
            self.assertAlmostEqual(
                sum(section_seconds), data["timings"]["runner_seconds"], delta=0.05,
            )
            self.assertGreaterEqual(
                data["timings"]["blender_process_seconds"],
                data["timings"]["runner_seconds"],
            )
            self.assertGreaterEqual(
                data["timings"]["test_total_seconds"],
                data["timings"]["harness_setup_seconds"]
                + data["timings"]["blender_process_seconds"],
            )


if __name__ == "__main__":
    unittest.main()

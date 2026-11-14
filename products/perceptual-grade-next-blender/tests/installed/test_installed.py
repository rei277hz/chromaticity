from importlib.resources import files
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
from .timing import (
    TIMING_SECTIONS,
    add_harness_timings,
    format_timing_report,
    read_report,
    write_report,
)


_BLENDER_TIMEOUT_SECONDS = 540


class InstalledExtensionTests(unittest.TestCase):
    def test_extension_hooks_in_blender_background(self):
        test_started = time.monotonic()
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
            setup_seconds = time.monotonic() - test_started
            process_started = time.monotonic()
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
                    # Leave time for timeout diagnostics within Buck's 600s limit.
                    cwd=root, env=env, capture_output=True, text=True,
                    timeout=_BLENDER_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as error:
                observed = time.monotonic()
                process_seconds = observed - process_started
                data = read_report(report)
                timings = add_harness_timings(
                    data,
                    setup_seconds=setup_seconds,
                    process_seconds=process_seconds,
                    total_seconds=observed - test_started,
                    observed_monotonic=observed,
                    interrupted=True,
                )
                if data is not None:
                    write_report(report, data)
                output = "\n".join(
                    part.decode(errors="replace") if isinstance(part, bytes) else part or ""
                    for part in (error.stdout, error.stderr)
                )
                self.fail(
                    f"Blender installed-extension test timed out after {_BLENDER_TIMEOUT_SECONDS} seconds\n"
                    + output + "\n" + format_timing_report(timings)
                )

            observed = time.monotonic()
            process_seconds = observed - process_started
            data = read_report(report)
            timings = add_harness_timings(
                data,
                setup_seconds=setup_seconds,
                process_seconds=process_seconds,
                total_seconds=observed - test_started,
                observed_monotonic=observed,
                interrupted=True,
            )
            if data is not None:
                write_report(report, data)
            timing_summary = format_timing_report(timings)
            print(timing_summary, flush=True)
            output = result.stdout + "\n" + result.stderr
            self.assertEqual(
                result.returncode, 0, output + "\n" + timing_summary,
            )
            self.assertTrue(report.is_file(), output)
            data = read_report(report)
            self.assertIsNotNone(data, output + "\n" + timing_summary)
            self.assertFalse(data["registered"])
            self.assertIn(data["blender"], ([5, 2, 4], [5, 3, 0]))
            self.assertEqual(data["timings"]["unit"], "seconds")
            self.assertTrue(data["timings"]["complete"])
            sections = data["timings"]["sections"]
            self.assertEqual(tuple(item["name"] for item in sections), TIMING_SECTIONS)
            self.assertTrue(all(item["status"] == "complete" for item in sections))
            section_seconds = tuple(item["seconds"] for item in sections)
            self.assertTrue(all(
                isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
                for value in section_seconds
            ), section_seconds)
            self.assertAlmostEqual(
                sum(section_seconds), data["timings"]["runner_seconds"], delta=0.05,
            )
            self.assertAlmostEqual(
                data["timings"]["blender_pre_runner_seconds"]
                + data["timings"]["runner_seconds"]
                + data["timings"]["blender_post_runner_seconds"],
                data["timings"]["blender_process_seconds"], delta=0.05,
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
            operations = data["timings"]["operations"]
            self.assertTrue(operations)
            self.assertTrue(all(
                item["status"] in {"complete", "error"}
                and item["seconds"] >= 0 and item["callsite"]
                and item["finished_monotonic"] is not None
                for item in operations
            ), operations)


if __name__ == "__main__":
    unittest.main()

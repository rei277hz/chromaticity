"""Exercise the installed Linear and Tone Gizmo through its node-editor toggle."""

import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
import zipfile

from importlib.resources import files

from .gui_support import virtual_display


def log_tail(path, limit=16_000):
    with path.open("rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        stream.seek(max(0, size - limit))
        return stream.read().decode(errors="replace")


class VectorscopeNativeTests(unittest.TestCase):
    def run_installed_case(self, runner_name):
        resources = files("tests.perceptual_grade_blender")
        blender_root = Path(str(resources / "blender")).resolve()
        blender = next((path for path in (
            blender_root / "Blender.app/Contents/MacOS/Blender",
            blender_root / "blender",
        ) if path.is_file()), None)
        self.assertIsNotNone(blender, "Pinned native Blender artifact missing")
        runner = Path(str(resources / runner_name)).resolve()
        with tempfile.TemporaryDirectory(prefix="pg-vectorscope-") as directory:
            root = Path(directory)
            repository = root / "repository"
            package = repository / "perceptual_grade"
            package.mkdir(parents=True)
            with zipfile.ZipFile(str(resources / "extension.zip")) as archive:
                archive.extractall(package)
            environment = {key: value for key, value in os.environ.items() if key not in {
                "PYTHONPATH", "PYTHONHOME", "BLENDER_USER_SCRIPTS",
                "BLENDER_SYSTEM_SCRIPTS", "BLENDER_SYSTEM_PYTHON",
            }}
            environment.update(
                BLENDER_USER_CONFIG=str(root / "config"),
                BLENDER_USER_EXTENSIONS=str(root / "extensions"),
                OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
                PYTHONDONTWRITEBYTECODE="1",
                TMPDIR=str(root),
            )
            with virtual_display(resources, root, environment):
                report = root / "report.json"
                log = root / "blender.log"
                with log.open("w") as output_file:
                    process = subprocess.Popen([
                        str(blender), "--factory-startup", "--disable-autoexec",
                        "--enable-event-simulate",
                        "--window-geometry", "0", "0", "1280", "960",
                        "--python-exit-code", "1", "--python", str(runner), "--",
                        str(repository), str(report),
                    ], cwd=root, env=environment, stdout=output_file,
                        stderr=subprocess.STDOUT, text=True, start_new_session=True)
                    try:
                        process.wait(timeout=300)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=10)
                        data = json.loads(report.read_text()) if report.exists() else {}
                        helper_output = "\n".join(
                            log_tail(path) for path in sorted(
                                root.glob("perceptual-grade-helper-*/helper.log")
                            )
                        )
                        self.fail("Installed vectorscope acceptance timed out\n"
                                  + log_tail(log)
                                  + "\n" + helper_output
                                  + "\n" + json.dumps(data, indent=2))
                output = log_tail(log)
            data = json.loads(report.read_text()) if report.exists() else {}
            details = output + "\n" + json.dumps(data, indent=2)
            self.assertEqual(process.returncode, 0, details)
            self.assertTrue(data.get("passed"), details)
            self.assertEqual(data.get("initial_shape"), [144, 144], details)
            self.assertTrue(data.get("mixed_trace_rgb"), details)
            self.assertTrue(data.get("per_node_drag"), details)
            self.assertTrue(data.get("shared_drag"), details)
            return data, details

    def test_compositor_grade_scope_tracks_edits_and_playback(self):
        data, details = self.run_installed_case("vectorscope_runner.py")
        self.assertTrue(data.get("additive_trace_pixels"), details)
        self.assertTrue(data.get("direct_image_visible"), details)
        self.assertTrue(data.get("linear_edit_refreshed"), details)
        self.assertTrue(data.get("linear_gizmo_controls"), details)
        self.assertTrue(data.get("gizmo_hover_and_resize"), details)
        self.assertTrue(data.get("hover_exhaustion_before_press"), details)
        self.assertTrue(data.get("hover_retry_acknowledged"), details)
        self.assertTrue(data.get("tone_gizmo_controls"), details)
        self.assertTrue(data.get("saturation_crossover_sidebar_sync"), details)
        self.assertTrue(data.get("saturation_crossover_reset_and_cancel"), details)
        self.assertTrue(data.get("saturation_crossover_autokey_undo"), details)
        self.assertTrue(data.get("tone_crossover_reset_and_cancel"), details)
        self.assertTrue(data.get("tone_crossover_pinned_handle"), details)
        self.assertTrue(data.get("tone_crossover_autokey_undo"), details)
        self.assertTrue(data.get("tone_gizmo_drawn"), details)
        self.assertTrue(data.get("fit_reset_before_motion"), details)
        self.assertTrue(data.get("fit_reset_continues_and_cancels"), details)
        self.assertTrue(data.get("highlight_reset_to_peak"), details)
        self.assertTrue(data.get("appearance_tone_warp_and_endpoints"), details)
        self.assertGreater(data.get("appearance_jobs", 0), 0, details)
        self.assertTrue(data.get("image_pixels_refreshed"), details)
        self.assertTrue(data.get("processed_input_visible"), details)
        self.assertGreaterEqual(len(set(data.get("playback_frames", []))), 2, details)
        self.assertTrue(data.get("retained_complete_during_updates"), details)
        self.assertTrue(data.get("latest_frame_published"), details)
        self.assertTrue(data.get("shared_consumer_input"), details)
        self.assertTrue(data.get("source_keys_undone"), details)
        self.assertTrue(data.get("undo_preserved_gizmo"), details)
        self.assertTrue(data.get("click_unchanged"), details)
        self.assertTrue(data.get("empty_plot_inert"), details)
        self.assertTrue(data.get("selection_cancelled"), details)
        self.assertTrue(data.get("escape_cancelled"), details)
        self.assertTrue(data.get("frame_change_cancelled"), details)
        self.assertTrue(data.get("capture_change_cancelled"), details)
        self.assertTrue(data.get("animated_destination_preserved"), details)
        self.assertTrue(data.get("autokey_at_press_frame"), details)

    def test_shader_grade_scope_captures_active_viewport_input(self):
        data, details = self.run_installed_case("vectorscope_shader_runner.py")
        self.assertTrue(data.get("shader_aov_visible"), details)
        self.assertTrue(data.get("linear_edit_refreshed"), details)
        self.assertTrue(data.get("uv_edit_refreshed"), details)
        self.assertTrue(data.get("right_click_cancelled"), details)
        self.assertTrue(data.get("shared_tone_gizmo"), details)
        self.assertTrue(data.get("appearance_tone_and_warp"), details)
        self.assertTrue(data.get("appearance_preview_reused_inputs_and_roles"), details)
        self.assertTrue(data.get("saturation_crossover_preview_and_capture"), details)
        self.assertTrue(data.get("tone_crossover_preview_and_capture"), details)
        timing = data.get("appearance_timing_seconds", {})
        self.assertEqual(set(timing), {
            "first_preview", "warm_preview", "release_to_exact", "panel_preview",
        }, details)
        self.assertTrue(all(value > 0 for value in timing.values()), details)
        print(
            f"Appearance Distribution timing — panel preview {timing['panel_preview'] * 1000:.0f} ms, "
            f"first drag preview {timing['first_preview'] * 1000:.0f} ms, "
            f"warm drag preview {timing['warm_preview'] * 1000:.0f} ms, "
            f"release to native appearance {timing['release_to_exact'] * 1000:.0f} ms"
        )


if __name__ == "__main__":
    unittest.main()

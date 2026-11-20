"""Installed Grade playback must show intermediate colors and converge when stopped."""

from importlib.resources import files
import json
import unittest


class PlaybackDisplayNativeTests(unittest.TestCase):
    def test_visible_intermediate_frames_and_full_stopped_grade(self):
        for surface in ("shader", "compositor"):
            report_path = files(__package__.removesuffix(".tools")) / f"{surface}.json"
            report = json.loads(report_path.read_text(encoding="utf8"))
            self.assertTrue(report["completed"])
            for control in ("exposure", "fit"):
                with self.subTest(surface=surface, control=control):
                    playback = report["controls"][control]["playback"]
                    values = {frame["value"] for frame in playback["evaluated_frames"]}
                    self.assertGreater(len(values), 1)
                    displayed = {change["endpoint"] for change in playback["transitions"]}
                    self.assertGreater(len(displayed), 1, playback)
                    self.assertIn(playback["stopped_value"], values)
                    self.assertGreaterEqual(playback["stopped_capture"]["start_ns"],
                                            playback["ended_ns"])

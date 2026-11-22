"""Verify the vectorscope's installed analysis and receipt decisions."""

import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

import numpy as np


class VectorscopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix="pg-vectorscope-unit-")
        cls.addClassCleanup(directory.cleanup)
        package_name = "vectorscope_test_extension"
        package = Path(directory.name) / package_name
        with zipfile.ZipFile(files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, directory.name)
        cls.addClassCleanup(sys.path.remove, directory.name)
        cls.policy = importlib.import_module(package_name + ".runtime.vectorscope_policy")
        cls.analysis = importlib.import_module(package_name + ".vectorscope")

    def request(self, state, capture, *, source="source", analysis=None, cached=False):
        return self.policy.step(state, self.policy.Event(
            "request", key=1, capture_signature=capture, source_signature=source,
            analysis_signature=capture if analysis is None else analysis, cache_available=cached,
        ))

    def capture(self, state, ticket, *, success=True):
        return self.policy.step(state, self.policy.Event(
            "capture_result", ticket=ticket, success=success, error="Capture failed",
        ))

    def test_playback_publishes_lagging_density_then_latest_demand(self):
        state, effects = self.request(self.policy.State(), "frame one")
        first = effects.start
        state, _ = self.request(state, "frame two")
        state, _ = self.request(state, "frame three")
        state, effects = self.capture(state, first)
        self.assertEqual(effects.publish.capture_signature, "frame three")
        self.assertEqual(effects.retain_samples, "frame one")
        self.assertEqual(self.policy.status(state, 1), ("updating", None))
        self.assertEqual(effects.start.capture_signature, "frame three")
        state, effects = self.capture(state, effects.start)
        self.assertIsNotNone(effects.publish)
        self.assertEqual(self.policy.status(state, 1), ("current", None))

    def test_newer_cached_plot_survives_superseded_capture(self):
        state, effects = self.request(self.policy.State(), "frame one")
        first = effects.start
        state, _ = self.request(state, "frame two", cached=True)
        state, _ = self.request(state, "frame three")
        state, effects = self.capture(state, first)
        self.assertIsNone(effects.publish)
        self.assertEqual(effects.start.capture_signature, "frame three")
        self.assertEqual(self.policy.status(state, 1), ("updating", None))

    def test_latest_linear_revision_reuses_matching_capture(self):
        state, effects = self.request(self.policy.State(), "frame one")
        first = effects.start
        state, effects = self.request(state, "frame one", analysis="new matrix")
        self.assertIsNone(effects.start)
        state, effects = self.capture(state, first)
        self.assertEqual(effects.publish.analysis_signature, "new matrix")
        self.assertEqual(self.policy.status(state, 1), ("current", None))

    def test_reopened_scope_rejects_prior_receipt_with_equal_signatures(self):
        state, effects = self.request(self.policy.State(), "frame one")
        first = effects.start
        state, effects = self.policy.step(state, self.policy.Event("release", key=1))
        self.assertEqual(effects.clear, (1,))
        state, _ = self.request(state, "frame one")
        state, effects = self.capture(state, first)
        self.assertIsNone(effects.publish)
        self.assertIsNone(effects.retain_samples)
        self.assertNotEqual(effects.start.generation, first.generation)
        self.assertEqual(self.policy.status(state, 1), ("updating", None))

    def test_superseded_failure_is_inert_and_exact_failure_is_visible(self):
        state, effects = self.request(self.policy.State(), "frame one")
        first = effects.start
        state, _ = self.request(state, "frame two")
        state, effects = self.capture(state, first, success=False)
        self.assertEqual(self.policy.status(state, 1), ("updating", None))
        state, _ = self.capture(state, effects.start, success=False)
        self.assertEqual(self.policy.status(state, 1), ("error", "Capture failed"))

    def test_linear_matrix_moves_density_to_rec709_target(self):
        rgba = np.array([[[1.0, 0.0, 0.0, 1.0]]])
        red_to_blue = np.array([[0, 0, 1], [0, 1, 0], [1, 0, 0]])
        density = self.analysis.density(rgba, red_to_blue, "Linear Rec.709")
        edges = np.linspace(-self.analysis.CHROMA_LIMIT, self.analysis.CHROMA_LIMIT,
                            self.analysis.SIZE + 1)
        blue_cr = -0.0722 / 1.5748
        expected = tuple(np.searchsorted(edges, coord) - 1 for coord in (blue_cr, 0.5))
        self.assertEqual(tuple(np.argwhere(density > 0)[0]), expected)
        self.assertEqual(density[expected], 1.0)
        self.assertFalse(density.flags.writeable)

    def test_density_weights_alpha_and_excludes_invalid_pixels(self):
        rgba = np.array([[[1, 0, 0, 1.0], [0, 1, 0, 0.25], [0, 0, 1, 0.0],
                          [0, np.nan, 1, 1.0], [1, 1, 0, np.inf]]])
        density = self.analysis.density(rgba, np.eye(3), "Linear Rec.709")
        levels = np.sort(density[density > 0])
        self.assertEqual(len(levels), 2)
        self.assertGreater(levels[1], levels[0])

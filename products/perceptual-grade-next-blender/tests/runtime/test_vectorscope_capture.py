"""Check area and alpha preservation in bounded vectorscope captures."""

import importlib
from importlib.resources import files
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np


class VectorscopeCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix="pg-vectorscope-capture-")
        cls.addClassCleanup(directory.cleanup)
        package_name = "vectorscope_capture_test_extension"
        package = Path(directory.name) / package_name
        with zipfile.ZipFile(files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, directory.name)
        cls.addClassCleanup(sys.path.remove, directory.name)
        cls.capture = importlib.import_module(package_name + ".runtime.vectorscope_capture")

    def test_fractional_cells_integrate_alpha_and_straight_rgb(self):
        pixels = np.zeros((3, 5, 4), dtype=np.float32)
        pixels[..., 1] = 1
        pixels[..., 3] = 1
        pixels[1, 1] = (1, 0, 0, 0.25)
        original = pixels.copy()
        overlap = np.array(((2 / 15, 1 / 15, 0), (2 / 15, 1 / 15, 0)))
        expected_alpha = 1 - overlap * 0.75
        expected_red = overlap * 0.25 / expected_alpha
        expected_green = (1 - overlap) / expected_alpha

        with patch.object(self.capture, "MAX_CAPTURE_EDGE", 3):
            reduced = self.capture._sample_pixels(pixels)
            rotated = self.capture._sample_pixels(pixels.swapaxes(0, 1))

        self.assertEqual(reduced.shape, (2, 3, 4))
        self.assertEqual(reduced.dtype, np.float32)
        self.assertTrue(reduced.flags.c_contiguous)
        np.testing.assert_allclose(reduced[..., 0], expected_red)
        np.testing.assert_allclose(reduced[..., 1], expected_green)
        np.testing.assert_array_equal(reduced[..., 2], 0)
        np.testing.assert_allclose(reduced[..., 3], expected_alpha)
        np.testing.assert_allclose(rotated, reduced.swapaxes(0, 1))
        np.testing.assert_array_equal(pixels, original)

    def test_thin_translucent_stripe_survives_the_capture_cap(self):
        width, height = 1025, 513
        pixels = np.zeros((height, width, 4), dtype=np.float32)
        pixels[..., 2] = 1
        pixels[:, 2] = (1, 0, 0, 0.25)
        pixels[:, 3, 0] = np.nan
        pixels[:, 3, 3] = 1

        reduced = self.capture._sample_pixels(pixels)

        self.assertEqual(reduced.shape, (256, 512, 4))
        np.testing.assert_array_equal(reduced[:, :2, 0], 1)
        np.testing.assert_array_equal(reduced[:, :2, 1:3], 0)
        np.testing.assert_array_equal(reduced[:, 2:, :], 0)
        np.testing.assert_allclose(reduced[:, 0, 3], 0.25 / width)
        np.testing.assert_allclose(reduced[:, 1, 3], 0.25 * 511 / width)
        self.assertAlmostEqual(float(reduced[..., 3].mean()), 0.25 / width)

    def test_small_rgb_input_preserves_pixels_and_adds_opaque_alpha(self):
        pixels = np.array([[[1, 2, -1], [0, 0.5, 0.75]]], dtype=np.float32)

        reduced = self.capture._sample_pixels(pixels)

        self.assertEqual(reduced.shape, (1, 2, 4))
        np.testing.assert_array_equal(reduced[..., :3], pixels)
        np.testing.assert_array_equal(reduced[..., 3], 1)

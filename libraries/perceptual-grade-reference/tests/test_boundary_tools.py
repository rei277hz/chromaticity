"""Exercise both format-15 CLI paths and their original compact-spline contract."""
from importlib.resources import files
import json
from pathlib import Path
import unittest

import numpy as np

from color_tools.perceptual_grade_core.model.boundary_polynomial import PolynomialTable
from color_tools.perceptual_grade_reference import spindle
from color_tools.perceptual_grade_reference.boundary_compact import CompactTable
from color_tools.perceptual_grade_reference.model import Model
from tools.build.boundary_oracle import capacity_unit, intersection
from tools.build.boundary_table import decode_unit


class BoundaryTools(unittest.TestCase):
    def report(self, name):
        return json.loads((files('tests.reference') / name).read_text())

    def test_candidate_audit_retains_compact_containment_contract(self):
        # This report is produced by the actual --candidate CLI during the build.
        report = self.report('candidate_report.json')
        self.assertTrue(report['accepted'])
        self.assertEqual(report['sampled_rays'], 730000)
        self.assertEqual(report['escaped_rays'], 0)
        self.assertLessEqual(report['rgb_relative_error'][-1], .001)
        self.assertFalse(report['certified'])

        model = Model()
        ctx = spindle.context(model.fl, model.aw, model.native_matrix)
        with np.load(Path(spindle.__file__).with_name('d65_boundary.npz'), allow_pickle=False) as source:
            data = dict(source)
        # A real ray distinguishes the original fitted surface from the runtime
        # uint16 approximation. Auditing that approximation must fail this gate.
        t = np.array([.8443682361886579])
        hue = np.array([2.763989686574603])
        exact = capacity_unit(t, hue, ctx.fl, ctx.aw, ctx.matrix)
        expected = decode_unit(ctx, t, hue, exact)
        errors = []
        for table in (CompactTable(data, np.float64), PolynomialTable(data)):
            rgb = decode_unit(ctx, t, hue, table.capacity(t, hue).astype(float))
            errors.append(float(np.max(abs(rgb-expected)) / np.max(expected)))
        self.assertLess(errors[0], .001)
        self.assertGreater(errors[1], .001)

    def test_regeneration_preserves_usable_spindle_profile_and_guard(self):
        # The full generator must use the historical context even while the
        # active Model exposes a cube context without a profile or guard.
        report = self.report('rebuilt_report.json')
        self.assertTrue(report['accepted'])
        self.assertEqual(report['escaped_rays'], 0)
        model = Model()
        self.assertNotIsInstance(model.boundary, spindle.Context)
        path = Path(str(files('tests.reference') / 'rebuilt_boundary.npz'))
        ctx = spindle.Context.load(path, model.fl, model.aw, model.native_matrix)
        self.assertTrue(np.all(ctx.coefficient(np.linspace(0, 1, 101)) > 0))
        heights = np.array([.02, .3, .7, .99]) * ctx.white
        expected_chroma, expected_energy = intersection(ctx, heights)
        chroma, energy, response = CompactTable(ctx.cache, np.float64).intersection(
            heights, ctx.white, spindle.GAMMA, return_response=True)
        # The guard is fitted in response coordinates; near white, relative
        # error in the vanishing chroma is not the approximation's contract.
        expected_response = (np.sqrt(expected_energy) / ctx.white)**(1 / spindle.GAMMA)
        np.testing.assert_allclose(response, expected_response, rtol=1e-6)
        np.testing.assert_allclose(66 * chroma + energy, heights**2, rtol=4e-16)
        self.assertTrue(np.all(chroma <= expected_chroma))
        self.assertTrue(np.all(energy >= expected_energy))

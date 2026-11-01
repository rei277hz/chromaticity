"""Shared color algebra contracts, independent of any consuming product."""
import os
import subprocess
import sys
import unittest

from color_tools.color_core import linear


class LinearTests(unittest.TestCase):
    def assertVectorClose(self, actual, expected, delta=2e-12):
        for a, b in zip(actual, expected, strict=True):
            self.assertAlmostEqual(a, b, delta=delta)

    def test_cat16_maps_whites_without_product_control_projection(self):
        # This additional xy lies outside Grade's source-white control range.
        whites = (*linear.WHITES.values(), (.01, .95))
        for source in whites:
            self.assertEqual(linear.cat16(source, source), linear.I3)
            for destination in whites:
                with self.subTest(source=source, destination=destination):
                    adapted = linear.mv(linear.cat16(source, destination), linear.xyz(source))
                    self.assertVectorClose(adapted, linear.xyz(destination))

    def test_cat16_rejects_invalid_whites_and_nonpositive_cones(self):
        for invalid in ((.3, 0.), (float('nan'), .3), (.3, float('inf')), (.9, .01)):
            for source, destination in ((invalid, linear.D65), (linear.D65, invalid)):
                with self.subTest(source=source, destination=destination):
                    with self.assertRaises(ValueError):
                        linear.cat16(source, destination)

    def test_rebase_preserves_action_in_the_adapted_context(self):
        source, destination = linear.D65, linear.WHITES['D50']
        matrix = ((1.1, .2, -.1), (.1, .8, .2), (0., -.3, 1.4))
        adaptation = linear.bradford(source, destination)
        rebased = linear.rebase(matrix, source, destination)
        for value in ((1., 1., 1.), (-.5, 4., .25), (0., 0., 0.)):
            self.assertVectorClose(linear.mv(rebased, linear.mv(adaptation, value)),
                                   linear.mv(adaptation, linear.mv(matrix, value)))

    def test_rebase_returns_the_original_for_identity_changes(self):
        matrix = ((1., .2, 0.), (0., .8, 0.), (0., 0., 1.))
        self.assertIs(linear.rebase(matrix, linear.D65, linear.D65), matrix)
        for gain in (0., -2., 1., 4.):
            isotropic = tuple(tuple(gain if i == j else 0. for j in range(3)) for i in range(3))
            self.assertIs(linear.rebase(isotropic, linear.D65, linear.WHITES['D50']), isotropic)

    def test_rgb_conversion_preserves_signed_hdr_values(self):
        for source in linear.SPACES:
            for destination in linear.SPACES:
                for value in ((-.5, 4., .25), (-2., -2., -2.), (8., 8., 8.)):
                    with self.subTest(source=source, destination=destination, value=value):
                        converted = linear.convert_rgb(value, source, destination)
                        restored = linear.convert_rgb(converted, destination, source)
                        self.assertVectorClose(restored, value)
                        if source == destination:
                            self.assertEqual(converted, value)
                        if value[0] == value[1] == value[2] and \
                                linear.SPACES[source][1] == linear.SPACES[destination][1]:
                            self.assertVectorClose(converted, value)

    def test_linear_import_does_not_load_numpy_or_model_data(self):
        code = '''
import importlib.abc
import sys

class RejectModelImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'numpy' or fullname.startswith('numpy.') or fullname in {
            'color_tools.color_core.aces2', 'color_tools.color_core._aces2_tables',
            'color_tools.color_core.modcam16', 'color_tools.color_core.scaled',
        }:
            raise AssertionError('Unexpected model import: ' + fullname)

sys.meta_path.insert(0, RejectModelImports())
from color_tools.color_core.linear import D65, cat16
assert cat16(D65, D65)[0][0] == 1.
'''
        result = subprocess.run([sys.executable, '-B', '-c', code],
                                env=dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path)),
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

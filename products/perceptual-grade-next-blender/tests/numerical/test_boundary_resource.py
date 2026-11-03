"""Build-time geometry, portable loading, and immutable resource ownership."""
from dataclasses import fields
import hashlib
from importlib import resources
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import numpy as np

from color_tools.kernel import prepare_tone
from color_tools.kernel import boundary
from tools.build_boundary import generate_boundary, resource_payload, write_resource


class BoundaryResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        context = prepare_tone()
        cls.context = (context.fl, context.aw, context.gamma)
        cls.asset = resources.files(boundary.__package__).joinpath(boundary.RESOURCE_NAME).read_bytes()
        cls.prepared = boundary.prepare_boundary(*cls.context)

    def test_packaged_resource_and_build_report(self):
        report = json.loads((Path(__file__).parent/'boundary_build_report.json').read_text())
        self.assertTrue(report['passed'])
        self.assertTrue(report['sources_stable_during_run'])
        self.assertEqual(report['asset_sha256'], hashlib.sha256(self.asset).hexdigest())
        self.assertEqual(report['pixel_bytes'], 2634768)
        self.assertEqual(report['probe_count'], self.prepared.probe_count)
        self.assertLessEqual(self.prepared.max_error, 2e-5)
        self.assertEqual(self.prepared.pixels.shape, (321, 513, 4))
        for value in (self.prepared.matrix, self.prepared.inverse, self.prepared.pixels):
            self.assertFalse(value.flags.writeable)
            with self.assertRaises(ValueError):
                value.flat[0] = 0

    def test_generation_matches_packaged_geometry_and_deterministic_archive(self):
        generated = generate_boundary(*self.context)
        for field in fields(boundary.PreparedBoundary):
            np.testing.assert_array_equal(getattr(generated, field.name), getattr(self.prepared, field.name))
        with tempfile.TemporaryDirectory() as directory:
            first, second = (Path(directory)/name for name in ('first.npz', 'second.npz'))
            payload = resource_payload(generated)
            write_resource(first, payload)
            write_resource(second, dict(reversed(tuple(payload.items()))))
            self.assertEqual(first.read_bytes(), self.asset)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_diagnostic_seed_sizes_keep_grid_metadata_and_report_failed_accuracy(self):
        candidates = ((64, 96, 256, (161, 257, 4)),
                      (32, 48, 128, (81, 129, 4)),
                      (16, 24, 64, (41, 65, 4)))
        for low, high, hue, shape in candidates:
            with self.subTest(low=low, high=high, hue=hue):
                candidate = generate_boundary(*self.context, low_cells=low,
                                              high_cells=high, hue_cells=hue,
                                              enforce_accuracy=False)
                self.assertEqual(candidate.pixels.shape, shape)
                self.assertEqual((candidate.seed_low_cells, candidate.seed_high_cells,
                                  candidate.seed_hue_cells), (low, high, hue))
                self.assertEqual(candidate.correction_steps, boundary.CORRECTION_STEPS)
                self.assertTrue(np.isfinite(candidate.pixels).all())
                self.assertTrue(np.isfinite(candidate.max_error))
                self.assertFalse(candidate.pixels.flags.writeable)
                if candidate.max_error > 2e-5:
                    with self.assertRaisesRegex(ValueError, 'cannot be packaged'):
                        resource_payload(candidate)
        # The regular generator retains the canonical admission gate.
        with self.assertRaisesRegex(ValueError, 'root internal gate failed'):
            generate_boundary(*self.context, low_cells=16, high_cells=24,
                              hue_cells=64)

    def test_loading_never_generates_or_densely_validates_geometry(self):
        with mock.patch.object(boundary.PreparedBoundary, 'exact', side_effect=AssertionError('runtime solve')), \
             mock.patch.object(boundary.PreparedBoundary, 'corrected', side_effect=AssertionError('runtime validation')):
            first = boundary.prepare_boundary(*self.context)
            second = boundary.prepare_boundary(*self.context)
        np.testing.assert_array_equal(first.pixels, second.pixels)
        self.assertFalse(np.shares_memory(first.pixels, second.pixels))

    def test_invalid_resource_contract_is_rejected(self):
        mutations = {
            'schema': lambda data: data.update(schema=np.array(99, dtype=np.int64)),
            'field_inventory': lambda data: data.update(unexpected=np.array(0)),
            'scalar_dtype': lambda data: data.update(fl=np.array(data['fl'], dtype=np.float32)),
            'matrix_shape': lambda data: data.update(matrix=np.zeros((2, 3), dtype=np.float64)),
            'matrix_values': lambda data: data['matrix'].__setitem__((0, 0), 0.),
            'inverse_values': lambda data: data['inverse'].__setitem__((0, 0), 0.),
            'white': lambda data: data.update(white=np.array(1., dtype=np.float64)),
            'pixels_shape': lambda data: data.update(pixels=data['pixels'][:-1]),
            'pixels_dtype': lambda data: data.update(pixels=data['pixels'].astype(np.float64)),
            'pixels_nonfinite': lambda data: data['pixels'].__setitem__((0, 0, 0), np.nan),
            'sampling': lambda data: data.update(seed_split=np.array(.8, dtype=np.float64)),
            'accuracy': lambda data: data.update(max_error=np.array(2.01e-5, dtype=np.float64)),
            'probes': lambda data: data.update(probe_count=np.array(0, dtype=np.int64)),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                data = {key: value.copy() for key, value in resource_payload(self.prepared).items()}
                mutate(data)
                archive = io.BytesIO()
                np.savez(archive, **data)
                archive.seek(0)
                with self.assertRaises(ValueError):
                    boundary._load_boundary(archive, *self.context)
        with self.assertRaisesRegex(ValueError, 'context mismatch'):
            boundary.prepare_boundary(self.context[0]*1.01, *self.context[1:])

    def test_missing_or_corrupt_resource_never_falls_back(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(boundary.resources, 'files', return_value=Path(directory)), \
             mock.patch.object(boundary.PreparedBoundary, 'exact', side_effect=AssertionError('runtime solve')):
            with self.assertRaisesRegex(FileNotFoundError, 'boundary_resource'):
                boundary.prepare_boundary(*self.context)
            (Path(directory)/boundary.RESOURCE_NAME).write_bytes(b'not an NPZ archive')
            with self.assertRaises(ValueError):
                boundary.prepare_boundary(*self.context)


if __name__ == '__main__':
    unittest.main()

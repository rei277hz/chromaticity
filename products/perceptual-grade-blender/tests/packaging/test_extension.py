"""Installation ZIP payload and deterministic archive metadata."""
from importlib.resources import files
import hashlib
import json
import tomllib
import unittest
import zipfile


class ExtensionTests(unittest.TestCase):
    def test_release_license_and_corresponding_source_grant(self):
        with zipfile.ZipFile(files('tests.packaging') / 'perceptual_grade.zip') as archive:
            legal_files = [name for name in archive.namelist()
                           if name.rsplit('/', 1)[-1].lower().startswith(('license', 'copying', 'notice'))]
            self.assertEqual(legal_files, ['LICENSE'])
            license_bytes = archive.read('LICENSE')
            explanation, gpl = license_bytes.split(b'                    GNU GENERAL PUBLIC LICENSE', 1)
            self.assertEqual(hashlib.sha256(b'                    GNU GENERAL PUBLIC LICENSE' + gpl).hexdigest(),
                             '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986')
            explanation_text = ' '.join(explanation.decode().split())
            for grant in ('GPL-3.0-or-later', 'Corresponding Source', 'MIT OR Apache-2.0', 'CC0-1.0'):
                self.assertIn(grant, explanation_text)
            for asset in (b'assets/ab_background.png', b'assets/cie_1931_xy_locus.png', b'model/d65_boundary.npz'):
                self.assertIn(asset, explanation)
            self.assertEqual(tomllib.loads(archive.read('blender_manifest.toml').decode())['license'],
                             ['SPDX:GPL-3.0-or-later'])

    def test_payload_matches_declared_runtime_tree(self):
        resources = files('tests.packaging')
        tree = resources / 'extension_tree'
        expected = {path.relative_to(tree).as_posix(): path.read_bytes() for path in tree.rglob('*') if path.is_file()}
        with zipfile.ZipFile(resources / 'perceptual_grade.zip') as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual([name for name in archive.namelist() if not name.startswith('assurance/')], sorted(expected))
            for name in archive.namelist():
                if name in expected:
                    self.assertEqual(archive.read(name), expected[name])
                self.assertFalse(name.startswith(('tests/', 'tools/', 'buck-out/')))
                self.assertFalse(name.endswith(('.pyc', '.so', '.whl')))
            self.assertTrue({'LICENSE', 'blender_manifest.toml', '__init__.py', 'perceptual_grade_blender/assets/cie_1931_xy_locus.png', 'perceptual_grade_blender/assets/ab_background.png', 'perceptual_grade_core/model/d65_boundary.npz'} <= set(expected))
            self.assertTrue({'perceptual_grade_core/model/bake_inverse.py','perceptual_grade_blender/model/bake_inverse_gpu.py',
                             'perceptual_grade_core/model/tone_table.py','perceptual_grade_core/model/stack_kernel.py','perceptual_grade_blender/model/stack_baking.py'} <= set(expected))
            self.assertNotIn('model/inverse.py',expected)
            self.assertIn('perceptual_grade_blender/graph/bake.py', expected)
            self.assertIn('perceptual_grade_blender/jobs/handlers/native_capture.py', expected)
            self.assertIn('perceptual_grade_core/model/raster.py', expected)
            for locale in ('en', 'zh_HANS'):
                catalog = json.loads(archive.read(f'perceptual_grade_core/locales/{locale}.json'))
                for key in ('bake.label', 'bake.tooltip', 'bake.add.label', 'bake.add.tooltip',
                            'bake.node.label', 'bake.node.tooltip', 'bake.status',
                            'bake.empty', 'bake.output.label', 'bake.destination.label',
                            'bake.destination.tooltip', 'bake.interrupted'):
                    self.assertTrue(catalog[key])
            self.assertFalse(any('perceptual_grade.reference' in p or p.startswith('colour/') for p in expected))

    def test_stable_metadata_and_generated_resources(self):
        with zipfile.ZipFile(files('tests.packaging') / 'perceptual_grade.zip') as archive:
            for entry in archive.infolist():
                self.assertEqual(entry.date_time, (2026, 1, 1, 0, 0, 0))
                self.assertEqual(entry.external_attr >> 16, 0o100644)
                self.assertEqual(entry.compress_type, zipfile.ZIP_DEFLATED)
                self.assertFalse(entry.extra)
                self.assertFalse(entry.comment)
            for locale in ('en', 'zh_HANS'):
                self.assertIn(f'perceptual_grade_core/locales/{locale}/LC_MESSAGES/perceptual_grade.mo', archive.namelist())
            for name in ('perceptual_grade_blender/assets/cie_1931_xy_locus.png', 'perceptual_grade_blender/assets/ab_background.png'):
                self.assertTrue(archive.read(name).startswith(b'\x89PNG\r\n\x1a\n'))


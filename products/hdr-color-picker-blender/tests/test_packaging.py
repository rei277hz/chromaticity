"""Exact shipped-source integrity checks and independently installable packages."""
import ast
import copy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
import zipfile



class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.resources = files('tests.hdr_picker')

    def test_release_license_and_corresponding_source_grant(self):
        with zipfile.ZipFile(self.resources / 'hdr_color_picker.zip') as archive:
            legal_files = [name for name in archive.namelist()
                           if name.rsplit('/', 1)[-1].lower().startswith(('license', 'copying', 'notice'))]
            self.assertEqual(legal_files, ['LICENSE'])
            explanation, gpl = archive.read('LICENSE').split(b'                    GNU GENERAL PUBLIC LICENSE', 1)
            self.assertEqual(hashlib.sha256(b'                    GNU GENERAL PUBLIC LICENSE' + gpl).hexdigest(),
                             '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986')
            explanation_text = ' '.join(explanation.decode().split())
            for grant in ('GPL-3.0-or-later', 'Corresponding Source', 'MIT OR Apache-2.0'):
                self.assertIn(grant, explanation_text)
            self.assertEqual(tomllib.loads(archive.read('blender_manifest.toml').decode())['license'],
                             ['SPDX:GPL-3.0-or-later'])

    def test_shared_sources_are_private_copies_with_no_sibling_imports(self):
        components = ('color_core',)
        with zipfile.ZipFile(self.resources / 'hdr_color_picker.zip') as picker, zipfile.ZipFile(
                self.resources / 'perceptual_grade.zip') as grade:
            for component in components:
                sources = self.resources / component
                expected = {component + '/' + path.relative_to(sources).as_posix(): path.read_bytes()
                            for path in sources.rglob('*') if path.is_file()}
                for archive in (picker, grade):
                    actual = {name: archive.read(name) for name in archive.namelist()
                              if name.startswith(component + '/')}
                    self.assertEqual(actual, expected, component)
            for archive, sibling in ((picker, 'perceptual_grade'), (grade, 'hdr_color_picker')):
                self.assertFalse(any(name.startswith(sibling) for name in archive.namelist()))
                for name in archive.namelist():
                    if not name.endswith('.py'):
                        continue
                    for node in ast.walk(ast.parse(archive.read(name), filename=name)):
                        modules = ([node.module] if isinstance(node, ast.ImportFrom)
                                   else [row.name for row in node.names] if isinstance(node, ast.Import) else [])
                        self.assertFalse(any(module and any(part.startswith(sibling) or part in ('blender_shared', 'color_tools')
                                                           for part in module.split('.'))
                                             for module in modules), name)
            self.assertIn('id = "hdr_color_picker"', picker.read('blender_manifest.toml').decode())
            self.assertIn('id = "perceptual_grade"', grade.read('blender_manifest.toml').decode())

    def test_framework_is_private_and_shared_bytes_match(self):
        with zipfile.ZipFile(self.resources / 'hdr_color_picker.zip') as picker, zipfile.ZipFile(
                self.resources / 'perceptual_grade.zip') as grade:
            shared = {name: picker.read(name) for name in picker.namelist()
                      if name.startswith('invariant/')}
            self.assertTrue(shared)
            self.assertEqual(shared, {name: grade.read(name) for name in shared})
            adapter = {name: picker.read(name) for name in picker.namelist()
                       if name.startswith('blender_runtime/')}
            self.assertTrue(adapter)
            self.assertEqual(adapter, {name: grade.read(name) for name in adapter})
            for archive, product in ((picker, 'hdr_color_picker'), (grade, 'perceptual_grade')):
                self.assertIn('invariant/actors.py', archive.namelist())
                self.assertIn('invariant/machine.py', archive.namelist())
                self.assertIn('invariant/verification/runtime_contracts.py', archive.namelist())
                self.assertIn('blender_runtime/coordinators/_execution_contracts.py', archive.namelist())
                self.assertNotIn(b'bind_policy', archive.read('blender_runtime/machine.py'))
                self.assertFalse(any(name.endswith('/policy_fixture.py') for name in archive.namelist()))
                self.assertFalse(any(name.startswith(('invariant/execution/',
                    'invariant/ownership/', 'invariant/blender/', 'z3/'))
                    for name in archive.namelist()))
                self.assertEqual({name for name in archive.namelist()
                    if name.startswith('invariant/verification/')}, {
                        'invariant/verification/__init__.py',
                        'invariant/verification/runtime_contracts.py'})
                roots = {name.split('/')[0] for name in archive.namelist() if '/' in name}
                self.assertEqual(roots, {'invariant', 'blender_runtime', 'color_core',
                                         product + '_core', product + '_blender'})
                self.assertFalse(any('_vendor' in name.split('/') for name in archive.namelist()))
                self.assertFalse(roots & {'execution_core', 'execution_blender', 'ownership_core',
                                          'ownership_blender', 'integration_blender'})
                self.assertFalse(any('assurance' in name.split('/') or name.endswith(('.manifest.json', '.receipt.json'))
                                     for name in archive.namelist()))
                self.assertFalse(any(name.endswith(('.pyc', '.whl')) for name in archive.namelist()))


if __name__ == '__main__':
    unittest.main()

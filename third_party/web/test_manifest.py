"""Lockfile and declaration consistency checks; no registry access is permitted."""
from contextlib import redirect_stdout
from importlib.resources import files
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from . import update


class ManifestTests(unittest.TestCase):
    def setUp(self):
        resources = Path(str(files(__package__)))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.here = Path(temporary.name)
        for name in ('dependencies.json', 'dependencies.bzl'):
            shutil.copyfile(resources / name, self.here / name)
        self.product = resources / 'product'
        self.addCleanup(patch.stopall)
        patch.object(update, 'HERE', self.here).start()
        patch.object(update.urllib.request, 'urlopen', side_effect=AssertionError('Network access in offline check')).start()

    def check(self):
        with redirect_stdout(io.StringIO()):
            update.check(self.product)

    def test_checked_in_declarations_match_npm_lockfile_offline(self):
        self.check()

    def test_starlark_manifest_drift_is_rejected(self):
        path = self.here / 'dependencies.bzl'
        path.write_text(path.read_text().replace('npm_vite', 'npm_vite_changed'))
        with self.assertRaisesRegex(ValueError, 'Starlark declarations differ'):
            self.check()

    def test_registry_record_drift_is_rejected(self):
        path = self.here / 'dependencies.json'
        manifest = json.loads(path.read_text())
        manifest['npm'][0]['url'] += '?undeclared-change'
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'npm record differs'):
            self.check()

    def test_changed_lockfile_requires_refresh(self):
        product = self.here / 'product'
        product.mkdir()
        shutil.copyfile(self.product / 'package-lock.json', product / 'package-lock.json')
        with (product / 'package-lock.json').open('a') as stream:
            stream.write('\n')
        with self.assertRaisesRegex(ValueError, 'npm lockfile changed'):
            update.check(product)


if __name__ == '__main__':
    unittest.main()

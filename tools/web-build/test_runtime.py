"""Run declared Node, oracle, and browser workloads inside Buck tests."""
from importlib.resources import files
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from web_build.build import stage_product


class RuntimeTests(unittest.TestCase):
    def test_workload(self):
        resources = Path(str(files(__package__)))
        mode = os.environ['WEB_TEST_MODE']
        with tempfile.TemporaryDirectory(prefix='web-check-') as directory:
            root = Path(directory)
            node = str((resources / 'node/bin/node').resolve())
            if mode == 'acceptance':
                with zipfile.ZipFile(resources / 'site.zip') as archive:
                    archive.extractall(root / 'site')
                subprocess.run([node, str(resources / 'acceptance.mjs'), '--site', str(root / 'site'),
                    '--chromium', str(resources / 'browser/chrome'), '--node-modules', str(resources / 'npm/node_modules')], check=True)
                return
            stage_product(root, resources / 'sources', resources / 'npm', resources / 'core_wasm',
                          resources / 'decomposition_wasm', resources / 'references')
            # Oracle subprocesses must use the same declared interpreter and wheel
            # import closure as this test, rather than system Python packages.
            launcher = root / 'oracle-python'
            import_paths = [str(Path(path).resolve()) for path in sys.path]
            launcher.write_text('#!' + sys.executable + '\nimport sys, runpy\nfrom pathlib import Path\nsys.path[:0] = ' + repr(import_paths) +
                                '\nsys.argv = sys.argv[1:]\nsys.path.insert(0, str(Path(sys.argv[0]).resolve().parent))\n'
                                'runpy.run_path(sys.argv[0], run_name="__main__")\n')
            launcher.chmod(0o755)
            env = dict(os.environ, PYTHON=str(launcher),
                       ESBUILD_BINARY_PATH=str(root / 'node_modules/@esbuild/linux-x64/bin/esbuild'))
            if mode == 'browser':
                env['CHROMIUM'] = str((resources / 'browser/chrome').resolve())
            name = {'math': 'picker_math', 'png': 'preview_png', 'ocio': 'ocio_oracle', 'browser': 'picker_browser'}[mode]
            subprocess.run([node, '--experimental-strip-types', '--test', 'tests/' + name + '.test.mjs'],
                           cwd=root, env=env, check=True)


if __name__ == '__main__':
    unittest.main()

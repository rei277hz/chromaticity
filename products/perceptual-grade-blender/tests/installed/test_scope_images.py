"""Pinned GUI Image decoding with the installed extension and generated AVI."""
from contextlib import ExitStack
from importlib.resources import files
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
import zipfile


class InstalledScopeImageTests(unittest.TestCase):
    def test_movie_frame_order_is_exact_and_source_image_unchanged(self):
        resources=files('tests.installed')
        binary=Path(str(resources/'blender')).resolve()
        blender=next(path for path in (binary/'blender',binary/'Blender.app/Contents/MacOS/Blender') if path.is_file())
        spec=importlib.util.spec_from_file_location('scope_display',str(resources/'gui_display.py'))
        display=importlib.util.module_from_spec(spec);spec.loader.exec_module(display)
        with tempfile.TemporaryDirectory(prefix='pg-installed-scope-images-') as directory,ExitStack() as services:
            root=Path(directory);package=root/'repository/perceptual_grade';package.mkdir(parents=True)
            with zipfile.ZipFile(str(resources/'extension.zip')) as archive:archive.extractall(package)
            env={key:value for key,value in os.environ.items() if key not in {
                'PYTHONPATH','PYTHONHOME','BLENDER_USER_SCRIPTS','BLENDER_SYSTEM_SCRIPTS','BLENDER_SYSTEM_PYTHON'}}
            env.update(BLENDER_USER_CONFIG=str(root/'config'),BLENDER_USER_EXTENSIONS=str(root/'extensions'),
                       OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
            services.enter_context(display.virtual_display(resources,root,env))
            report=root/'report.json'
            process=subprocess.Popen([str(blender),'--factory-startup','--disable-autoexec','--threads','1',
                '--python-exit-code','1','--python',str(resources/'scope_images_runner.py'),'--',str(package.parent),str(report)],
                cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True)
            try:stdout,_=process.communicate(timeout=150)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);stdout,_=process.communicate(timeout=10)
                self.fail('Scope Image native acceptance timed out\n'+stdout[-12000:])
            finally:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            data=json.loads(report.read_text()) if report.exists() else {}
            details=stdout[-12000:]+'\n'+json.dumps(data,indent=2)
            self.assertEqual(process.returncode,0,details)
            self.assertTrue(data.get('passed'),details)
            self.assertTrue(data['source_unchanged'],details)
            self.assertEqual(len(data['stereo_cases']),36,details)
            self.assertEqual(len(data['individual_cases']),4,details)
            self.assertEqual(len(data['float_stereo_cases']),18,details)
            self.assertEqual([item['frame'] for item in data['frames']],[1,3,2,1,3],details)

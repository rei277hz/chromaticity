"""Install independent ZIPs into a disposable repository in native Blender."""
import importlib
import json
from pathlib import Path
import sys
import traceback
import unittest

import bpy

args = sys.argv[sys.argv.index('--')+1:]
repository, tests, report = map(Path, args)
bpy.context.preferences.extensions.repos.new(
    name='Component package acceptance', module='picker_tests', custom_directory=str(repository))
sys.path.insert(0, str(tests))
try:
    picker = importlib.import_module('bl_ext.picker_tests.hdr_color_picker')
    picker.register()
    # Real installed import and registration; no test-only import aliasing.
    suite = unittest.defaultTestLoader.discover(str(tests), pattern='test_*_blender.py')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    picker.unregister()
    if not result.wasSuccessful():
        raise RuntimeError('Native picker suite failed')
    report.write_text(json.dumps({'tests': result.testsRun, 'passed': True}))
except BaseException:
    report.write_text(json.dumps({'passed': False, 'traceback': traceback.format_exc()}))
    traceback.print_exc()
    raise

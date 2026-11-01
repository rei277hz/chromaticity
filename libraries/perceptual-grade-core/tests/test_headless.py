"""Exercise complete domain packages without any Blender integration import."""
import importlib
import pkgutil
import sys
import unittest
from unittest.mock import patch


class HeadlessDomainTests(unittest.TestCase):
    def test_all_domain_modules_import_without_host_packages(self):
        original = __import__

        def headless(name, globals=None, locals=None, fromlist=(), level=0):
            if name.split('.')[0] in {'bpy', 'gpu', 'gpu_extras'} or any(
                part.endswith('_blender') for part in name.split('.')
            ):
                raise AssertionError('Domain attempted a host import: ' + name)
            return original(name, globals, locals, fromlist, level)

        with patch('builtins.__import__', headless):
            for name in ('color_tools.color_core', 'color_tools.perceptual_grade_core',
                         'color_tools.perceptual_grade_reference'):
                package = importlib.import_module(name)
                for module in pkgutil.walk_packages(package.__path__, package.__name__ + '.'):
                    importlib.import_module(module.name)
            from color_tools.perceptual_grade_core.localization.catalogs import tr
            from color_tools.perceptual_grade_reference.model import Model
            self.assertTrue(tr('product.name', locale='en'))
            self.assertEqual(Model().forward([[0., 0., 0.]]).tolist(), [[0., 0., 0.]])
        self.assertFalse(any(name == 'bpy' or name.startswith('bpy.') for name in sys.modules))

    def test_reference_preserves_its_explicit_appearance_semantics(self):
        from color_tools.perceptual_grade_reference import appearance, responses
        from color_tools.perceptual_grade_reference.model import Model
        model = Model()
        self.assertIs(model.color.web.encoder, appearance.encode_cones)
        self.assertIs(model.color.adaptation.response_math, responses)

    def test_reference_gpu_factory_is_explicit_and_cached(self):
        from color_tools.perceptual_grade_reference.model import Settings
        from color_tools.perceptual_grade_reference.stack_bake import BakeStack
        stack = BakeStack([Settings()])
        with self.assertRaisesRegex(RuntimeError, 'explicit host program factory'):
            stack.prepare_gpu()
        calls, program = [], object()
        stack = BakeStack([Settings()], program_factory=lambda solver: (calls.append(solver), program)[1])
        self.assertIs(stack.prepare_gpu(), program)
        self.assertIs(stack.prepare_gpu(), program)
        self.assertEqual(calls, [stack.solvers[0]])

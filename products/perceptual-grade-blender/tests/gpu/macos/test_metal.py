"""Native Metal runs the shared numerical/baking contracts on macOS only."""
import sys
import unittest
from tests.gpu import test_shader, test_baking, test_inverse_baking, test_stack_baking, test_scope_cloud
from tests.support.gpu import initialize


class MetalTests(unittest.TestCase):
    def test_native_backend(self):
        self.assertEqual(sys.platform, 'darwin')
        gpu = initialize()
        self.assertEqual(gpu.platform.backend_type_get(), 'METAL')


def load_tests(loader, suite, pattern):
    for case in (test_shader.ShaderTests, test_baking.BakingTests,
                 test_inverse_baking.InverseComputeTests,test_stack_baking.StackBakingTests,
                 test_scope_cloud.CloudGPUTests):
        suite.addTests(loader.loadTestsFromTestCase(case))
    return suite

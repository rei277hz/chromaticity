"""Strict photographic gates and isolated numerical study policies."""
from functools import wraps
from unittest.mock import patch
import unittest
import numpy as np
from color_tools.perceptual_grade_core.model import bake_inverse
from tests.reference import legacy_capacity
from color_tools.perceptual_grade_reference.model import Settings
from tools.analysis.inverse_bake_profile import study_policy
from tools.analysis.inverse_tuning import gate,LIMITS
from tools.analysis.photo_stack import cases


class InverseTuningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table=legacy_capacity.LegacyCapacityBakeStack([Settings()],['INVERSE']).table

    def test_render_gate_is_strict_and_rejects_invalid_measurements(self):
        self.assertEqual(LIMITS,{'SDR100':.1,'HDR1000':.4})
        for view,limit in LIMITS.items():
            with self.subTest(view=view):
                self.assertTrue(gate(0.,view))
                self.assertTrue(gate(np.nextafter(limit,0.),view))
                self.assertFalse(gate(limit,view))
                self.assertFalse(gate(np.nextafter(limit,np.inf),view))
                for invalid in (-1.,np.nan,np.inf,-np.inf):
                    with self.assertRaises(ValueError):gate(invalid,view)

    def test_policy_restores_nested_overrides_even_after_exception(self):
        names=('RGB_RELATIVE_TOLERANCE','RGB_ABSOLUTE_TOLERANCE','TOLERANCE',
               'SEARCH_TOLERANCE','ITERATIONS')
        original={name:getattr(bake_inverse,name) for name in names}
        factory=legacy_capacity.ToneTable
        with study_policy(rgb_relative=.002,rgb_absolute=.0002,raw_tolerance=.0003,
                          stage3_stopping=2e-5,stage3_iterations=16,
                          tone_table_tolerance=1e-5) as outer:
            self.assertEqual(outer,dict(rgb_relative=float(np.float32(.002)),
                rgb_absolute=float(np.float32(.0002)),raw_tolerance=float(np.float32(.0003)),
                stage3_stopping=float(np.float32(2e-5)),stage3_iterations=16,
                tone_table_tolerance=1e-5))
            self.assertEqual([getattr(bake_inverse,n) for n in names],
                [np.float32(.002),np.float32(.0002),np.float32(.0003),np.float32(2e-5),16])
            outer_factory=legacy_capacity.ToneTable
            with self.assertRaisesRegex(RuntimeError,'scope exit'):
                with study_policy(stage3_iterations=8,tone_table_tolerance=2e-5) as inner:
                    self.assertEqual(inner['stage3_iterations'],8)
                    self.assertEqual(inner['tone_table_tolerance'],2e-5)
                    self.assertEqual(inner['raw_tolerance'],outer['raw_tolerance'])
                    raise RuntimeError('scope exit')
            self.assertEqual(bake_inverse.ITERATIONS,16)
            self.assertIs(legacy_capacity.ToneTable,outer_factory)
            with study_policy() as inherited:self.assertEqual(inherited,outer)
        self.assertIs(legacy_capacity.ToneTable,factory)
        for name,value in original.items():self.assertIs(getattr(bake_inverse,name),value)

    def test_custom_tone_tolerance_reaches_preparation_and_is_not_retained(self):
        original=legacy_capacity.ToneTable;received=[]
        @wraps(original)
        def prepare(tone,**kwargs):
            received.append(kwargs.copy());return original(tone,**kwargs)
        setting=cases()['mixed_tone']
        with patch.object(legacy_capacity,'ToneTable',prepare):
            with study_policy(tone_table_tolerance=1e-5):
                tuned=legacy_capacity.LegacyCapacityBakeStack([setting],['INVERSE'],self.table)
            default=legacy_capacity.LegacyCapacityBakeStack([setting],['INVERSE'],self.table)
        self.assertEqual(received,[{'tolerance':1e-5},{}])
        self.assertIs(tuned.solvers[0].tone_table,tuned.tone_tables[0])
        self.assertIs(default.solvers[0].tone_table,default.tone_tables[0])
        self.assertIsNot(tuned.tone_tables[0],default.tone_tables[0])
        self.assertLessEqual(tuned.tone_tables[0].max_error,5e-6)

    def test_tuned_policy_keeps_exact_black_and_finite_near_neutrals(self):
        source=np.array([[0.,0.,0.],[1e-12,1e-12,1e-12],
                         [.08,.08,.08],[.08,.08001,.07999]],dtype='f4')
        with study_policy(stage3_stopping=2e-6,stage3_iterations=32,
                          raw_tolerance=1e-4,tone_table_tolerance=1e-5):
            stack=legacy_capacity.LegacyCapacityBakeStack([cases()['mixed_tone']],['INVERSE'],self.table)
            inverse=stack.solvers[0];kernel=inverse.kernel
            target=kernel.grade(kernel.tone_state(kernel.enter(source)))
            recovered=inverse.evaluate(target,True)
            np.testing.assert_array_equal(target[0],0.)
            np.testing.assert_array_equal(recovered[0],0.)
            self.assertTrue(np.isfinite(recovered).all())
            self.assertTrue(np.all((recovered[:,:3]>=0)&(recovered[:,:3]<=1024)))
            self.assertTrue(np.all(np.max(recovered[2:,:3],axis=-1)>0))


if __name__=='__main__':unittest.main()

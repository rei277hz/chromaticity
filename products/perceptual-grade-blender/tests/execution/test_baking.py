"""Detached baking preserves numerical results and owns atlas preparation."""
from tests.support.session import component as _component, SessionTest, patch
import os
from concurrent.futures import CancelledError
import unittest
from types import SimpleNamespace
pass

import numpy as np

pass
from color_tools.perceptual_grade_core.jobs.codec import freeze_model, thaw_cube
from color_tools.perceptual_grade_blender.jobs.handlers import bake
from color_tools.perceptual_grade_blender.model import baking
from color_tools.perceptual_grade_core.model import color, linear, lut, tone, transforms
from tests.support.blender import BlenderTest


def model():
    settings=transforms.Settings(linear.I3,tone.Parameters(input_midtones=45),
        color.Parameters(global_gain=.2),linear.GradeSpace('D65'))
    return transforms.Stack((settings,))


class BakerCancellationTests(SessionTest):
    def test_finished_shared_handle_after_close_is_cancelled_not_failed(self):
        adapter = _component('jobs.baker')
        for during_result in (False, True):
            with self.subTest(during_result=during_result):
                baker = adapter.RemoteBaker(model())
                baker._admit()
                def result(timeout=None):
                    if during_result:baker.cancel()
                    return object()  # Obsolete data must never reach decoding.
                baker.handle = SimpleNamespace(cancel=lambda: False, cancelled=lambda: False,
                    retired=lambda: True, result=result, preview=object())
                try:
                    if not during_result:baker.cancel()
                    with patch.object(baker, '_failed', side_effect=AssertionError('Cancellation became failure')):
                        with self.assertRaises(CancelledError):baker.result()
                    self.assertEqual(baker.protocol.state.phase, 'closed')
                    self.assertIsNone(baker.preview)
                    self.assertIsNone(baker.cube)
                    with self.assertRaises(CancelledError):baker._accept_preview(object())
                finally:
                    baker.cancel()
                    baker.protocol.close()


class ProgramAdoptionTests(SessionTest):
    def test_failed_conformance_never_enters_either_program_cache(self):
        for stack in (False,True):
            with self.subTest(stack=stack):
                module=bake.stack_baking if stack else bake.gpu
                cache='_stack_program' if stack else '_program'
                execution=SimpleNamespace(solvers=[object()])
                value=SimpleNamespace(prepare=lambda _checkpoint:execution)
                candidates=[object(),object()]
                with patch.object(bake,cache,None),patch.object(bake,'_device',return_value='Test GPU'), \
                     patch.object(bake.baking,'kernel',return_value=object()), \
                     patch.object(module,'Program',side_effect=candidates) as constructor, \
                     patch.object(module,'validate_program',side_effect=[ArithmeticError('Rejected'),None]) as validate, \
                     patch.object(module,'GPU' if stack else 'Baker'):
                    with self.assertRaisesRegex(ArithmeticError,'Rejected'):
                        bake._gpu_baker(value,False,False,stack,lambda:None)
                    self.assertIsNone(getattr(bake,cache))
                    bake._gpu_baker(value,False,False,stack,lambda:None)
                    self.assertIs(getattr(bake,cache),candidates[1])
                    bake._gpu_baker(value,False,False,stack,lambda:None)
                    self.assertEqual(constructor.call_count,2)
                    self.assertEqual(validate.call_count,2)

    def test_probe_rejects_cpu_and_invalidates_programs_after_arithmetic_failure(self):
        context=SimpleNamespace(role='bulk',checkpoint=lambda:None)
        with patch.object(bake,'_gpu_baker') as create:
            with self.assertRaisesRegex(RuntimeError,'GPU helper'):bake.handle_probe({},context)
            create.assert_not_called()
        context.role='gpu'
        program=SimpleNamespace(parameters=object())
        with patch.object(bake,'_program',program),patch.object(bake,'_stack_program',object()), \
             patch.object(bake,'_gpu_baker',return_value=SimpleNamespace(kernel=object(),device='Test GPU')), \
             patch.object(bake,'_validate_math',side_effect=ArithmeticError('Power probe failed')):
            with self.assertRaisesRegex(ArithmeticError,'Power probe failed'):bake.handle_probe({},context)
            self.assertIsNone(bake._program)
            self.assertIsNone(bake._stack_program)


class DetachedBakingTests(BlenderTest):
    def test_handler_preserves_progressive_values_and_prepared_atlas(self):
        value=model();previews=[];progress=[]
        context=SimpleNamespace(role='bulk',checkpoint=lambda:None,
            preview=previews.append,progress=progress.append)
        result=thaw_cube(bake.handle(dict(model=freeze_model(value),
            progressive=True,encoded=True,stack=False),context))
        expected=baking.CPU(value,True,True).finish()
        np.testing.assert_array_equal(result.values,expected.values)
        np.testing.assert_array_equal(result.prepared_pixels,expected.prepared_pixels)
        self.assertEqual(result.signature,lut.signature(value))
        self.assertEqual(len(previews),1)
        preview=thaw_cube(previews[0])
        self.assertEqual(preview.signature,lut.signature(value,lut.PREVIEW_SIZE))
        np.testing.assert_array_equal(result.values[::2,::2,::2],preview.values)
        self.assertEqual(progress[-1],1.)
        self.assertEqual(progress,sorted(progress))
        diagnostics=result.diagnostics
        self.assertLessEqual(diagnostics['worker_started_at'],diagnostics['worker_calculated_at'])
        self.assertLessEqual(diagnostics['worker_calculated_at'],diagnostics['worker_packed_at'])
        self.assertGreaterEqual(diagnostics['worker_preparation_s'],0.)

    def test_helper_owns_baking_and_cross_encoding_repack(self):
        remote=_component('jobs.baker').RemoteBaker(model(),True,False)
        with patch.object(baking.CPU,'evaluate_rows',side_effect=AssertionError('Foreground baking')), \
             patch.object(lut.Cube,'packed_pixels',side_effect=AssertionError('Foreground packing')):
            preview=remote.finish_preview()
            result=remote.finish()
            pixels=_component('jobs.baker').prepared_pixels(result,True,wait=True)
        self.assertNotEqual(result.diagnostics['worker_pid'],os.getpid())
        self.assertEqual(preview.size,33)
        self.assertEqual(result.size,65)
        self.assertEqual(pixels.shape,(lut.atlas_height(65,4),lut.ATLAS_WIDTH,4))
        np.testing.assert_array_equal(result.values[::2,::2,::2],preview.values)
        np.testing.assert_array_equal(pixels,result.packed_pixels())

    def test_scope_final_and_progressive_native_requests_share_computation(self):
        value=model()
        final=_component('jobs.baker').RemoteBaker(value,False,False)
        progressive=_component('jobs.baker').RemoteBaker(value,True,False)
        final.start();progressive.start()
        self.assertIs(final.handle._job,progressive.handle._job)
        one=final.finish();two=progressive.finish()
        np.testing.assert_array_equal(one.values,two.values)
        self.assertEqual(one.diagnostics['worker_pid'],two.diagnostics['worker_pid'])
        # A final-only cache hit still supports the legacy explicit preview
        # interface without packing a nested atlas on the foreground thread.
        with patch.object(lut.Cube,'packed_pixels',side_effect=AssertionError('Foreground packing')):
            preview=progressive.finish_preview()
        self.assertEqual(preview.signature,lut.signature(value,33))
        np.testing.assert_array_equal(one.values[::2,::2,::2],preview.values)

    def test_different_atlas_encodings_share_the_same_numerical_job(self):
        value=model()
        shader=_component('jobs.baker').RemoteBaker(value,True,False)
        compositor=_component('jobs.baker').RemoteBaker(value,True,True)
        shader.start();compositor.start()
        self.assertIs(shader.handle._job,compositor.handle._job)
        plain=shader.finish();encoded=compositor.finish()
        with patch.object(lut.Cube,'packed_pixels',side_effect=AssertionError('Foreground packing')):
            atlas=_component('jobs.baker').prepared_pixels(encoded,True,wait=True)
        np.testing.assert_array_equal(plain.values,encoded.values)
        np.testing.assert_array_equal(atlas,plain.packed_pixels())

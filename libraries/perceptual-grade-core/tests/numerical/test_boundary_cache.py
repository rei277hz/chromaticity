"""Adopted D65 contexts: portable matching, immutable constants and shared bytes."""
from importlib.resources import files
from concurrent.futures import CancelledError
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
import os
import subprocess
import sys
import numpy as np
from color_tools.perceptual_grade_reference import cube as reference
from color_tools.perceptual_grade_reference.cube_guard import guard
from color_tools.perceptual_grade_reference.model import Model, Settings
from color_tools.perceptual_grade_reference.grading import ToneSettings
from color_tools.perceptual_grade_core.model import cube_boundary as blender, forward, linear, tone

class BoundaryCacheTests(unittest.TestCase):
    def test_both_decoders_reuse_the_certified_context(self):
        models=(Model(),forward.Model(tone.model(tone.Parameters(),linear.GradeSpace('D65'))))
        for module,model in zip((reference,blender),models):
            context=module.context(model.fl,model.aw,model.native_matrix)
            self.assertIs(module.context(model.fl,model.aw,model.native_matrix),context)
            self.assertTrue(np.all(abs(context.matrix-model.native_matrix)<=64*np.finfo(float).eps*(1+abs(context.matrix))))
            for array in (context.matrix,*context.cache.values()):self.assertFalse(array.flags.writeable)
            q,e,_=guard(context,[0.,0.,0.],0.)
            np.testing.assert_array_equal(context.decode(q,e),0.)

    def test_rounding_selects_immutable_certified_constants(self):
        path=files(reference.__package__)/'d65_cube.npz'
        with np.load(path) as data:
            fl,aw=float(data['fl']),float(data['aw']);matrices=data['matrices'].copy()
        for module in (reference,blender):
            for matrix in matrices:
                for candidate in (matrix,np.nextafter(matrix,np.inf)):
                    context=module.Context.load(path,np.nextafter(fl,np.inf),np.nextafter(aw,-np.inf),candidate)
                    self.assertEqual((context.fl,context.aw),(fl,aw))
                    np.testing.assert_array_equal(context.matrix,matrix)
                    for array in (context.matrix,*context.cache.values()):self.assertFalse(array.flags.writeable)

    def test_substantive_mismatches_and_invalid_resources_are_rejected(self):
        model=Model();path=files(reference.__package__)/'d65_cube.npz'
        for module in (reference,blender):
            for field,fl,aw,matrix in (
                    ('fl',model.fl+1e-10,model.aw,model.native_matrix),
                    ('aw',model.fl,model.aw+1e-10,model.native_matrix),
                    ('matrix',model.fl,model.aw,model.native_matrix+1e-10),
                    ('fl',np.nan,model.aw,model.native_matrix),
                    ('matrix',model.fl,model.aw,np.full((3,3),np.inf))):
                with self.assertRaisesRegex(ValueError,field):module.Context.load(path,fl,aw,matrix)
            with TemporaryDirectory() as directory:
                with np.load(path) as data:payload=dict(data)
                invalid=Path(directory)/'invalid.npz'
                for patch,error in (({'profile':np.zeros(3)},'unexpected'),({'format':12},'format')):
                    np.savez_compressed(invalid,**(payload|patch))
                    with self.assertRaisesRegex(ValueError,error):module.Context.load(invalid,model.fl,model.aw,model.native_matrix)
                for name,value,error in (('sectors',np.full_like(payload['sectors'],np.nan),'sectors'),
                                         ('edge_faces',np.zeros_like(payload['edge_faces']),'faces'),
                                         ('edge_knots',payload['edge_knots'][::-1],'axis'),
                                         ('white',np.nan,'white')):
                    np.savez_compressed(invalid,**(payload|{name:value}))
                    with self.assertRaisesRegex(ValueError,error):module.Context.load(invalid,model.fl,model.aw,model.native_matrix)
                np.savez_compressed(invalid,**payload)
                invalid.write_bytes(invalid.read_bytes()+b'x'*(max(65537-invalid.stat().st_size,1)))
                self.assertGreater(invalid.stat().st_size,65536)
                with self.assertRaisesRegex(ValueError,'64 KiB'):module.Context.load(invalid,model.fl,model.aw,model.native_matrix)
        with self.assertRaisesRegex(ValueError,'D65 / 203'):Model(Settings(tone=ToneSettings(reference_nits=204)))
        with self.assertRaisesRegex(ValueError,'D65 / 203'):forward.Model(tone.model(tone.Parameters(reference_nits=204)))

    def test_scalar_metadata_rounding_preserves_white_tip_and_reset(self):
        rgb=np.array([[0.,0.,0.],[1024.,1024.,1024.],[0.,1024.,0.],
                      [2.,0.,128.],[.2,.3,1.],[1e-12,1e-8,1e-4]])
        for model in (Model(),forward.Model(tone.model(tone.Parameters(),linear.GradeSpace('D65')))):
            fl,aw=model.fl,model.aw
            evaluate=model.forward_native if hasattr(model,'forward_native') else model.apply_native
            for f in (np.nextafter(fl,-np.inf),fl,np.nextafter(fl,np.inf)):
                for a in (np.nextafter(aw,-np.inf),aw,np.nextafter(aw,np.inf)):
                    model.fl,model.aw=f,a
                    actual=evaluate(rgb)
                    self.assertTrue(np.all((actual>=0)&(actual<=1024)))
                    error=np.max(abs(actual-rgb),axis=-1)/np.maximum(np.max(rgb,axis=-1),1e-100)
                    self.assertLess(float(error.max()),2e-12)
            model.vector_controls=False
            np.testing.assert_allclose(evaluate(rgb),rgb,rtol=0,atol=2e-10)

    def test_default_and_nehalem_blas_processes_decode_the_cube(self):
        code='''
import numpy as np
from color_tools.perceptual_grade_reference.model import Model
from color_tools.perceptual_grade_core.model import forward,linear,tone
rgb=np.array([[0.,0.,0.],[1024.,1024.,1024.],[0.,1024.,0.],
              [2.,0.,128.],[.2,.3,1.],[1e-12,1e-8,1e-4]])
for model in (Model(),forward.Model(tone.model(tone.Parameters(),linear.GradeSpace('D65')))):
    actual=model.forward_native(rgb) if hasattr(model,'forward_native') else model.apply_native(rgb)
    assert np.all((actual>=0)&(actual<=1024)),actual
    error=np.max(abs(actual-rgb),axis=-1)/np.maximum(np.max(rgb,axis=-1),1e-100)
    assert error.max()<2e-12,error
    print(type(model).__module__,float(error.max()),float(np.max(abs(model.native_matrix-model.boundary.matrix))))
'''
        for kernel in ('default','NEHALEM'):
            env=dict(os.environ,PYTHONPATH=os.pathsep.join(sys.path))
            if kernel=='default':env.pop('OPENBLAS_CORETYPE',None)
            else:env['OPENBLAS_CORETYPE']=kernel
            result=subprocess.run([sys.executable,'-B','-c',code],env=env,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_one_identical_small_resource_is_shared(self):
        paths=[files(reference.__package__)/'d65_cube.npz',files(blender.__package__)/'d65_boundary.npz']
        self.assertEqual(paths[0].read_bytes(),paths[1].read_bytes())
        self.assertLessEqual(paths[0].stat().st_size,65536)
        with np.load(paths[0],allow_pickle=False) as data:
            self.assertEqual(int(data['format']),16)
            self.assertFalse(bool(data['certified']))
            self.assertTrue({'profile','guard_knots','guard_coefficients','knots'}.isdisjoint(data.files))
            self.assertEqual(data['matrices'].shape,(2,3,3))
            self.assertLessEqual(sum(v.nbytes for v in data.values()),65536)

    def test_cancellation_inside_boundary_search_keeps_context_reusable(self):
        model=forward.Model(tone.model(tone.Parameters(),linear.GradeSpace('D65')))
        context=model.boundary
        calls=[]
        def checkpoint():
            calls.append(1)
            raise CancelledError('Obsolete raw entry')
        with self.assertRaisesRegex(CancelledError,'Obsolete raw entry'):
            model.prepare_native([[.2,.3,1.],[0.,1.,0.]],checkpoint)
        self.assertEqual(len(calls),1)
        self.assertIs(model.boundary,context)
        np.testing.assert_allclose(model.apply_native([[.2,.3,1.]]),[[.2,.3,1.]],rtol=2e-12,atol=0)

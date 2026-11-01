"""Complete forward LUT vertices, nested reuse, transport and cancellation."""
from concurrent.futures import CancelledError
from dataclasses import replace
import unittest
import numpy as np
from color_tools.perceptual_grade_blender.model.baker import Baker
from color_tools.perceptual_grade_core.model import color, linear, lut, tone, transforms
from tests.support import cases, reference as oracle


class LUTTests(unittest.TestCase):
    def assertPortableParity(self,actual,expected):
        # The baked Stack now uses the shared float32 production kernel.
        error=np.max(abs(np.asarray(actual)-expected),axis=-1)
        limit=np.maximum(.001*np.max(abs(expected),axis=-1),1e-7)
        self.assertTrue(np.all(error<=limit),(error,limit))

    def test_rgbe_optimized_packing_preserves_transport_bytes(self):
        rng=np.random.default_rng(51933)
        values=np.ldexp(rng.uniform(-1,1,(33,33,33,3)).astype('f4'),
                        rng.integers(-149,11,(33,33,33,1)))
        values[0,0,0]=[0.,-0.,1024.]
        cube=lut.Cube(values,'packing',size=33);count=33**3
        expected=np.zeros((lut.atlas_height(33,4),lut.ATLAS_WIDTH,4),dtype='f4')
        fields=[values]
        for axis in range(3):
            difference=np.zeros_like(values);lo=[slice(None)]*3;hi=lo.copy()
            lo[axis]=slice(None,-1);hi[axis]=slice(1,None)
            difference[tuple(lo)]=(values[tuple(hi)].astype(float)-values[tuple(lo)].astype(float)).astype('f4')
            fields.append(difference)
        for plane,field in enumerate(fields):
            rgb=field.reshape(-1,3);_,exponent=np.frexp(np.max(abs(rgb),axis=-1))
            packed=np.concatenate((np.ldexp(rgb,-exponent[:,None]),exponent[:,None]),axis=-1).astype('f4')
            expected.reshape(-1,4)[plane*count:(plane+1)*count]=packed
        self.assertEqual(cube.packed_pixels().tobytes(),expected.tobytes())

    def test_empty_stack_preserves_native_cube_edges(self):
        baker=Baker(transforms.Stack([]),progressive=True)
        preview=baker.finish_preview();final=baker.finish()
        np.testing.assert_array_equal(preview.values.reshape(-1,3),lut.lattice(33).astype('f4'))
        np.testing.assert_array_equal(final.values.reshape(-1,3),lut.lattice().astype('f4'))
        self.assertTrue((final.values>=0).all());self.assertTrue((final.values<=1024).all())

    def test_extended_axes_and_shaper(self):
        for size in (33,65):
            axis=lut.axis(size)
            self.assertEqual((axis[0],axis[-1]),(0.,1024.))
            self.assertTrue((np.diff(axis)>0).all())
            np.testing.assert_allclose(lut.encode(axis),np.linspace(0,1,size),rtol=0,atol=3e-16)
        np.testing.assert_array_equal(lut.axis(33),lut.axis(65)[::2])
        probes=np.r_[0.,np.geomspace(1e-12,1024,257),128.,512.,743.19103667,1024.]
        np.testing.assert_allclose(lut.decode(lut.encode(probes)),probes,rtol=3e-15,atol=1e-24)
        cell,fraction=lut.cell_coordinates([[0,0,0],[1024,1024,1024]])
        np.testing.assert_array_equal(cell,[[0,0,0],[63,63,63]])
        np.testing.assert_array_equal(fraction,[[0,0,0],[1,1,1]])

    def test_complete_grade_vertices_and_guarded_stress_cases(self):
        ids=np.array([0,1,100,65**2,33000,65535,65**3-1])
        for exposure,gain in ((0,0),(-8,0),(8,0),(0,8),(8,8)):
            lp=replace(linear.Parameters(),exposure=exposure)
            cp=color.Parameters(global_gain=gain)
            value=transforms.Settings.from_parameters(lp,tone.Parameters(),cp,'Linear Rec.709')
            model=transforms.Stack([value]);baker=Baker(model);cube=baker.finish()
            rgb=lut.lattice()[ids]@baker.from_lut.T
            expected=oracle.settings(rgb,replace(value,matrix=linear.I3))@baker.to_lut.T
            self.assertPortableParity(cube.values.reshape(-1,3)[ids],expected)
            self.assertTrue(np.isfinite(cube.values).all())
            self.assertPortableParity(model.apply_cube(cube,rgb),oracle.lut(rgb,value,cube.size))

    def test_preview_refinement_visits_each_vertex_once(self):
        model=cases.stack();baker=Baker(model,progressive=True)
        shared,remaining=lut.refinement_indices()
        self.assertEqual(len(shared),33**3)
        self.assertEqual(len(remaining),65**3-33**3)
        np.testing.assert_array_equal(np.sort(np.r_[shared,remaining]),np.arange(65**3))
        np.testing.assert_array_equal(lut.lattice(33),lut.lattice()[shared])
        preview=baker.finish_preview();snapshot=preview.values.copy();final=baker.finish()
        np.testing.assert_array_equal(final.values[::2,::2,::2],snapshot)
        np.testing.assert_array_equal(preview.values,snapshot)
        self.assertEqual(baker.progress,1)
        rgb=lut.lattice()[shared[::2048]]@baker.from_lut.T
        self.assertPortableParity(final.apply(rgb),oracle.settings(rgb,model.entries[0]))
        levels=np.array([128-1e-4,128,128+1e-4,512,743.19103667,1024-1e-4,1024,1024+1e-4])
        native=(levels[:,None,None]*np.array([[1,1,1],[1,.4,.1]])).reshape(-1,3)
        native=np.r_[native,[[-.2,.3,.4],[2048,10,1]]]
        rgb=native@baker.from_lut.T
        for cube in (preview,final):
            expected=oracle.lut(rgb,model.entries[0],cube.size,linear_stage=False)
            self.assertPortableParity(cube.apply(rgb),expected)

    def test_cancelled_refinement_retains_preview(self):
        baker=Baker(cases.stack(),progressive=True);preview=baker.finish_preview();baker.cancel()
        with self.assertRaises(CancelledError):baker.finish()
        self.assertIs(baker.preview,preview);self.assertIsNone(baker.cube)

    def test_internal_matrix_and_controls_change_bake_key(self):
        original=cases.stack();value=original.entries[0];key=lut.signature(original)
        changed=replace(value,matrix=tuple(map(tuple,2*np.asarray(value.matrix))))
        self.assertEqual(key,lut.signature(transforms.Stack([changed])))
        self.assertNotEqual(lut.signature(transforms.Stack([value,value])),lut.signature(transforms.Stack([value,changed])))
        self.assertNotEqual(key,lut.signature(transforms.Stack([replace(value,color=replace(value.color,global_gain=.3))])))
        self.assertNotEqual(key,lut.signature(transforms.Stack([value,value])))

    def test_input_projection_then_convex_tetrahedral_transport(self):
        # A bounded affine fixture isolates input projection and interpolation.
        rgb=lut.lattice();matrix=np.array([[.7,.2,.1],[.1,.8,.1],[.1,.1,.8]])
        values=rgb@matrix.T
        cube=lut.Cube(values,'transport')
        probes=np.array([[-.2,.3,.4],[2048,10,1],[0,0,0],
                         [128,128,128],[512,200,1],[743.19103667,400,100],[1024,1024,1024]])
        before,after=lut.basis();canonical=probes@after.T
        expected=(oracle.input_repair(probes,oracle.model.rgb_matrix('ACEScg')[1])@matrix.T)@after.T
        self.assertLess(float(oracle.error(cube.apply(canonical),expected).max()),2e-6)
        packed=lut.pack_rgbe(values.astype('f4'))
        np.testing.assert_array_equal(lut.unpack_rgbe(packed),values.astype('f4'))

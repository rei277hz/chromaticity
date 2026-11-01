"""Structural and interpolation checks for the reference photographic study."""
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import numpy as np
from tests.reference.legacy_capacity import LegacyCapacityBakeStack
from tools.analysis.photo_stack import ForcedStack,cases,axis,lattice,tetrahedral,vertex_diagnostic,prepare,endpoint,eval_core


class PhotoStackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings=cases()['mixed']
        cls.stack=ForcedStack([settings,settings],['FORWARD','INVERSE'])
        cls.points=np.array([[.1,.2,.3],[.7,.2,.1],[.02,.08,.4],[0,0,0]],dtype='f4')

    def test_matching_pair_reaches_cpu_raw_inverse_and_reduced_solver(self):
        stack=self.stack;inverse=stack.solvers[1]
        self.assertTrue(LegacyCapacityBakeStack.matching(stack,0,1));self.assertFalse(stack.matching(0,1))
        with (patch.object(inverse,'evaluate',wraps=inverse.evaluate) as called,
              patch.object(inverse,'reduced',wraps=inverse.reduced) as reduced):
            result=stack.bake_native(self.points)
        self.assertEqual(called.call_count,1);self.assertTrue(called.call_args.args[1])
        self.assertEqual(called.call_args.args[0].shape[-1],4);self.assertGreater(reduced.call_count,0)
        self.assertTrue(np.isfinite(result).all())

    def test_matching_gpu_dispatch_uses_raw_forward_then_raw_inverse(self):
        stack=self.stack;seen=[];owners=[]
        raw=np.column_stack((self.points,np.arange(len(self.points),dtype='f4')))
        def evaluate(values,mode):
            seen.append(mode)
            if mode==3:
                np.testing.assert_array_equal(values,self.points);return raw
            self.assertEqual(mode,1);np.testing.assert_array_equal(values,raw)
            return np.column_stack((self.points,np.zeros(len(self.points),dtype='f4')))
        program=SimpleNamespace(evaluate=evaluate,set_inverse=owners.append)
        with patch.object(stack,'prepare_gpu',return_value=program):actual=stack.bake_native(self.points,'GPU')
        self.assertEqual(seen,[3,1]);self.assertEqual(owners,list(stack.solvers))
        np.testing.assert_array_equal(actual[:,:3],self.points)

    def test_preparation_keeps_endpoint_outside_cube_and_accounts_for_repair(self):
        setting=cases()['exposure'];stack=ForcedStack([setting,setting],['FORWARD','INVERSE'],self.stack.table)
        source=np.array([[.1,.2,.3],[300.,20.,10.],[-1.,2.,3.]])
        prepared=prepare(stack,source)
        np.testing.assert_allclose(prepared['linear'],source*4,rtol=0,atol=1e-12)
        self.assertEqual(prepared['repair_changed'].tolist(),[False,True,True])
        np.testing.assert_allclose(prepared['ideal'],prepared['repaired']/4,rtol=0,atol=1e-12)
        np.testing.assert_allclose(prepared['repair_delta'],prepared['ideal']-source,rtol=0,atol=0)
        np.testing.assert_allclose(prepared['prepared'][0],source[0],rtol=2e-7,atol=1e-8)
        # An identity core table keeps the single external ×4 / ÷4 pair.
        values=lattice();actual=endpoint(stack,tetrahedral(values,prepared['input']))
        np.testing.assert_allclose(actual,prepared['prepared'],rtol=2e-7,atol=2e-6)
        np.testing.assert_allclose(actual[0],source[0],rtol=2e-7,atol=1e-8)

    def test_endpoint_does_not_repair_negative_or_above_cube_results(self):
        endpoint_only=SimpleNamespace(output_matrix=np.array([[1,-2,0],[0,1,0],[0,0,2]],dtype='f4'),matrix=LegacyCapacityBakeStack.matrix)
        value=np.array([[1.,2.,800.]],dtype='f4')
        np.testing.assert_array_equal(endpoint(endpoint_only,value),[[-3.,2.,1600.]])

    def test_tetrahedra_use_linear_fractions_and_preserve_affine_data(self):
        size=5;grid=axis(size)
        nodes=np.stack(np.meshgrid(grid,grid,grid,indexing='ij'),-1)
        matrix=np.array([[1.,2.,-.5],[.1,-.3,.7],[0.,2.,1.]])
        values=nodes@matrix.T+np.array([.2,-.1,.4])
        low=grid[[1,2,0]];high=grid[[2,3,1]]
        fractions=np.array([[.8,.5,.1],[.8,.1,.5],[.5,.8,.1],[.1,.8,.5],
                            [.5,.1,.8],[.1,.5,.8],[.5,.5,.5],[1.,0.,1.]])
        points=low+fractions*(high-low)
        actual=tetrahedral(values,points)
        np.testing.assert_allclose(actual,points@matrix.T+[.2,-.1,.4],rtol=2e-15,atol=2e-13)
        np.testing.assert_allclose(tetrahedral(values,nodes),values,rtol=1e-15,atol=1e-12)
        np.testing.assert_array_equal(axis()[[0,-1]],[0.,1024.])
        np.testing.assert_array_equal(lattice()[:65,2],axis().astype('f4'))
        with self.assertRaises(ValueError):tetrahedral(values,[[-.1,0,0]])

    def test_chunking_retains_spatial_order_and_residual_channel(self):
        points=np.arange(30,dtype='f4').reshape(2,5,3)
        def bake(values,backend='CPU'):return np.column_stack((values,np.sum(values,axis=-1)))
        fake=SimpleNamespace(bake_native=bake)
        expected=np.concatenate((points,np.sum(points,axis=-1)[...,None]),-1)
        for backend in ('CPU','GPU'):
            np.testing.assert_array_equal(eval_core(fake,points,backend,chunk=4),expected)
        self.assertEqual(eval_core(fake,np.empty((0,3))).shape,(0,4))

    def test_vertex_audit_attributes_neutral_corner_errors_without_rebaking(self):
        size=3;source=lattice(size).reshape(size,size,size,3)
        cube=np.concatenate((source,np.zeros((size,size,size,1),dtype='f4')),-1)
        cube[0,0,0,:3]+=[2.,-1.,3.];cube[0,0,0,3]=.009
        cube[1,1,1,:3]+=[-1.,4.,2.];cube[1,1,1,3]=.0002
        point=axis(size)[1]*np.array([.8,.5,.2])
        audit=vertex_diagnostic(cube,point)
        self.assertEqual(audit['indices'],[[0,0,0],[1,0,0],[1,1,0],[1,1,1]])
        np.testing.assert_allclose(audit['weights'],[.2,.3,.3,.2],rtol=0,atol=1e-15)
        self.assertEqual(audit['neutral'],[True,False,False,True])
        self.assertAlmostEqual(audit['neutral_weight'],.4);self.assertEqual(audit['failed_vertices'],2)
        np.testing.assert_allclose(audit['weighted_error'],[.2,.6,1.],rtol=0,atol=2e-7)
        np.testing.assert_array_equal(audit['predicted_core'],tetrahedral(cube[...,:3],point))
        np.testing.assert_allclose(np.asarray(audit['predicted_core'])-point,
            np.asarray(audit['weighted_error'])+audit['grid_roundoff'],rtol=0,atol=1e-15)

    def test_vertex_audit_matches_nonlinear_cube_in_all_tetrahedra_and_ties(self):
        size=5;source=lattice(size).reshape(size,size,size,3)
        cube=np.concatenate(((source+1)**2/(1+np.max(source,axis=-1,keepdims=True)),
                             np.zeros((size,size,size,1),dtype='f4')),-1)
        low=axis(size)[[1,2,0]];high=axis(size)[[2,3,1]]
        fractions=np.array([[.8,.5,.1],[.8,.1,.5],[.5,.8,.1],[.1,.8,.5],
                            [.5,.1,.8],[.1,.5,.8],[.5,.5,.5],[1.,0.,1.]])
        for point in low+fractions*(high-low):
            audit=vertex_diagnostic(cube.reshape(-1,4),point)
            np.testing.assert_array_equal(audit['predicted_core'],tetrahedral(cube[...,:3],point))
            self.assertAlmostEqual(sum(audit['weights']),1.)
            self.assertGreaterEqual(min(audit['weights']),0.)
            np.testing.assert_allclose(np.asarray(audit['weights'])@np.asarray(audit['selected_rgb']),
                audit['predicted_core'],rtol=2e-15,atol=1e-14)
        with self.assertRaises(ValueError):vertex_diagnostic(cube,np.ones((2,3)))
        with self.assertRaises(ValueError):vertex_diagnostic(cube[...,:3],np.ones(3))


if __name__=='__main__':unittest.main()

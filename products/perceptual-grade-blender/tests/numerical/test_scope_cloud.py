"""Texture-only helper fallback preserves Warp point semantics."""
import unittest
from unittest.mock import Mock,patch
import numpy as np
from color_tools.perceptual_grade_blender.model import scope_cloud_gpu as cloud
from color_tools.perceptual_grade_core.model import scope_cloud as cpu_cloud


def view(width=65,height=65,scale=1.,rect=None):
    return dict(key=('test',),width=width,height=height,
        rect=(0.,0.,float(width),float(height)) if rect is None else rect,
        scale=scale,bounds=((-1.,-1.,1.,1.),)*4)


def result(points,weights=None,energy=None):
    points=np.asarray(points,float).reshape(-1,2)
    weights=np.ones(len(points)) if weights is None else np.asarray(weights,float)
    energy=np.ones(len(points)) if energy is None else np.asarray(energy,float)
    return {'_colors':tuple(dict(bounded_saturation=points,weights=weights*(tone+1)/4,
        after_energy=energy) for tone in range(4))}


class CloudRasterTests(unittest.TestCase):
    @staticmethod
    def scalar_coverage(points,weights,energy,descriptor):
        """Independent full-canvas point shader oracle, accumulated in order."""
        h,w=descriptor['height'],descriptor['width'];rx,ry,rw,rh=descriptor['rect']
        yy,xx=np.mgrid[:h,:w];xx=xx+.5;yy=yy+.5
        result=np.zeros((h,w),np.float32)
        for (a,b),weight,e in zip(np.asarray(points,np.float32),np.asarray(weights,np.float32),energy):
            if not np.isfinite([a,b,weight,e]).all() or weight<=0:continue
            sx=rx+(-float(b)+1)*rw/2;sy=ry+(float(a)+1)*rh/2
            radius=.75*descriptor['scale']*(2 if e<0 else 1)
            distance=((xx-sx)**2+(yy-sy)**2)/radius**2
            mask=(distance<=1)&(xx>=rx)&(xx<rx+rw)&(yy>=ry)&(yy<ry+rh)
            if e<0:mask&=distance>=.25
            alpha=np.float32(np.clip(weight,0,1)*.35)
            result[mask]=alpha+result[mask]*(1-alpha)
        return result

    def test_four_tone_byte_coverage_and_source_over(self):
        values=cloud.render(result([[0,0],[0,0]]),[view()],False)
        record=values[0];self.assertEqual(record['backend'],'cpu')
        pixels=record['pixels'];self.assertEqual(pixels.dtype,np.uint8)
        self.assertEqual(pixels.shape,(1,4,65,65))
        for tone in range(4):
            alpha=.35*(tone+1)/4
            self.assertEqual(pixels[0,tone,32,32],round(255*(1-(1-alpha)**2)))
        self.assertEqual(np.count_nonzero(pixels[0,3]),1)
        self.assertEqual(set(record),{'view','pixels','backend','timings'})

    def test_negative_branch_is_double_size_hollow_ring(self):
        solid=cloud.render(result([[0,0]],energy=[1]),[view(scale=2)],False)[0]['pixels'][0,3]
        ring=cloud.render(result([[0,0]],energy=[-1]),[view(scale=2)],False)[0]['pixels'][0,3]
        self.assertGreater(solid[32,32],0);self.assertEqual(ring[32,32],0)
        self.assertEqual(solid[32,34],0);self.assertGreater(ring[32,34],0)
        self.assertGreater(np.count_nonzero(ring),np.count_nonzero(solid))

    def test_fractional_rect_clips_point_disk(self):
        descriptor=view(11,11,2.,(.75,.75,9.,9.))
        pixels=cloud.render(result([[-1,1]]),[descriptor],False)[0]['pixels'][0,3]
        self.assertFalse(pixels[0].any());self.assertFalse(pixels[:,0].any())
        self.assertGreater(pixels[1,1],0)

    def test_nonfinite_and_zero_weights_are_excluded(self):
        ordinary=result([[0,0]])
        extended=result([[0,0],[np.nan,0],[.2,.4],[.4,.6]],weights=[1,1,0,np.nan])
        np.testing.assert_array_equal(cloud.render(ordinary,[view()],False)[0]['pixels'],
            cloud.render(extended,[view()],False)[0]['pixels'])

    def test_cpu_projection_is_helper_local_when_bounded_field_omitted(self):
        from color_tools.perceptual_grade_core.model.saturation import bounded_project
        q=np.array([[10.,2.,3.],[0.,0.,0.],[5.,-3.,1.]])
        energy=np.array([4.,0.,-2.])
        actual={'_colors':tuple(dict(after=q,after_energy=energy,weights=np.ones(3)) for _ in range(4))}
        expected={'_colors':tuple(dict(bounded_saturation=bounded_project(q,energy),
            after_energy=energy,weights=np.ones(3)) for _ in range(4))}
        np.testing.assert_array_equal(cloud.render(actual,[view()],False)[0]['pixels'],
            cloud.render(expected,[view()],False)[0]['pixels'])

    def test_views_are_independent_and_empty_views_do_no_work(self):
        checkpoint=Mock()
        self.assertEqual(cloud.render({},(),True,checkpoint),());checkpoint.assert_not_called()
        records=cloud.render(result([[.4,.2]]),[view(33,35),view(67,69,2.)],False,checkpoint)
        self.assertEqual([v['pixels'].shape for v in records],[(1,4,35,33),(1,4,69,67)])
        self.assertGreater(checkpoint.call_count,0)

    def test_different_tone_bounds_are_used(self):
        descriptor=view();descriptor['bounds']=tuple((-r,-r,r,r) for r in (1,2,3,4))
        pixels=cloud.render(result([[.4,0]]),[descriptor],False)[0]['pixels'][0]
        centers=[np.argwhere(tile).mean(axis=0)[0] for tile in pixels]
        self.assertTrue(all(a>b for a,b in zip(centers,centers[1:])))

    def test_batched_raster_matches_point_shader_with_partial_alpha_and_dense_overlap(self):
        rng=np.random.default_rng(322)
        points=rng.uniform(-1.4,1.4,(4200,2));points[:1200]=[.12,-.34]
        weights=rng.uniform(-.1,1.2,len(points));energy=rng.choice([-1.,1.],len(points))
        points[0]=[np.nan,0];weights[1]=np.inf;energy[2]=np.nan
        for scale in (.2,1.,2.,8.):
            with self.subTest(scale=scale):
                descriptor=view(31,33,scale,(.35,.75,29.1,31.3))
                actual=cloud._raster_layer(points,weights,energy,descriptor)
                expected=self.scalar_coverage(points,weights,energy,descriptor)
                np.testing.assert_allclose(actual,expected,rtol=0,atol=3e-7)
                byte_error=np.abs(np.rint(actual*255)-np.rint(expected*255))
                self.assertLessEqual(np.max(byte_error),1)

    def test_large_point_footprints_keep_allocations_bounded_and_check_cancellation(self):
        descriptor=view(31,33,80.)
        points=np.array([[0.,0.],[.2,.3],[-.4,.1]])
        weights=np.array([.3,.8,1.]);energy=np.array([1.,-1.,1.])
        broadcast=np.broadcast_to;sizes=[]
        def record(value,shape):
            sizes.append(np.prod(shape));return broadcast(value,shape)
        with (patch.object(cpu_cloud,'CPU_RASTER_CANDIDATES',64),
              patch.object(cpu_cloud.np,'broadcast_to',side_effect=record)):
            actual=cloud._raster_layer(points,weights,energy,descriptor)
        np.testing.assert_allclose(actual,self.scalar_coverage(points,weights,energy,descriptor),rtol=0,atol=1e-7)
        self.assertGreater(len(sizes),3);self.assertLessEqual(max(sizes),64)
        class Cancelled(Exception):pass
        checkpoint=Mock(side_effect=[None,None,Cancelled()])
        with patch.object(cpu_cloud,'CPU_RASTER_CANDIDATES',64):
            with self.assertRaises(Cancelled):cloud._raster_layer(points,weights,energy,descriptor,checkpoint=checkpoint)
        self.assertEqual(checkpoint.call_count,3)

    def test_population_scales_log_transmission_without_clipping_mass_into_alpha(self):
        descriptor=view();points=np.zeros((2,2));opacity=np.array([.5,.25]);mass=np.array([.25,4.])
        actual=cloud._raster_layer(points,opacity,np.ones(2),descriptor,mass=mass)
        expected=1.-(1.-.35*.5)**.25*(1.-.35*.25)**4.
        self.assertAlmostEqual(float(actual[32,32]),expected,places=7)
        self.assertEqual(np.count_nonzero(actual),1)
        value=result(points)
        value['_colors']=tuple(dict(s,weights=opacity*mass,opacity_weights=opacity,sample_mass=mass)
                               for s in value['_colors'])
        image=cloud.render(value,[descriptor],False)[0]['pixels']
        np.testing.assert_array_equal(image[0,:,32,32],np.full(4,round(255*expected)))


if __name__=='__main__':unittest.main()

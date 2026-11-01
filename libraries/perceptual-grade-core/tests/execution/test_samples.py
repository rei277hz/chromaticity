import unittest
import numpy as np
from color_tools.perceptual_grade_core.scopes.samples import (
    ordinary_layout,tile_allocations,tiled_layout,pixel_indices,sample_rgba)


class SamplingLayoutTests(unittest.TestCase):
    def test_ordinary_aspect_and_exact_nearest_centers(self):
        layout=ordinary_layout(1000,100)
        self.assertEqual(layout.shape,(26,256))
        pixels=np.arange(1000*100*4).reshape(100,1000,4)
        sampled=sample_rgba(pixels,layout)
        xs,ys=pixel_indices(layout,1000,100)
        np.testing.assert_array_equal(sampled,pixels[ys,xs])
        self.assertFalse(sampled.flags.writeable)
        for field in ('mass','x','uv','tiles','ids'):
            self.assertFalse(getattr(layout,field).flags.writeable)

    def test_reservation_exact_remainders_and_pixel_mass(self):
        tiles=((1003,10,10),(1001,1,1),(1002,10,10))
        _,counts,total,count=tile_allocations(tiles,10)
        self.assertEqual(counts,(1,5,4))
        layout=tiled_layout(tiles,10)
        self.assertAlmostEqual(layout.mass.sum(),10.)
        for tile,pixels in ((1001,1),(1002,100),(1003,100)):
            self.assertAlmostEqual(layout.mass[layout.tiles==tile].sum(),pixels/total*count)
        self.assertEqual(layout.count,10)
        self.assertEqual(layout.key,tiled_layout(tuple(reversed(tiles)),10).key)

    def test_ragged_rows_equal_area_and_atlas_gaps(self):
        layout=tiled_layout(((1001,5,2),(1003,5,2)),11)
        uv=layout.uv[layout.tiles==1001]
        # Six samples produce two equal rows, three equal-width cells each.
        np.testing.assert_allclose(uv,[(.1,1/4),(.5,1/4),(.9,1/4),
                                       (.1,3/4),(.5,3/4),(.9,3/4)])
        np.testing.assert_allclose(layout.x[layout.tiles==1001],uv[:,0]/3)
        self.assertGreater(layout.x[layout.tiles==1003].min(),2/3)

    def test_padding_is_zero_mass_and_ids_are_stable(self):
        layout=tiled_layout(((1001,300,1),(1002,1,1)))
        self.assertEqual(layout.shape,(2,256));self.assertEqual(layout.count,301)
        np.testing.assert_array_equal(layout.ids[layout.mass>0],np.arange(301))
        self.assertTrue(np.all(layout.ids[layout.mass==0]==-1))
        pixels=np.ones((1,1,4))
        self.assertTrue(np.all(sample_rgba(pixels,layout)[layout.mass==0]==0))

    def test_population_less_than_budget_covers_every_pixel_once(self):
        layout=tiled_layout(((1001,3,7),(1002,7,3)))
        for tile,w,h in ((1001,3,7),(1002,7,3)):
            xs,ys=pixel_indices(layout,w,h);mask=layout.tiles==tile
            self.assertEqual(len(set(zip(xs[mask],ys[mask]))),w*h)
        np.testing.assert_array_equal(layout.mass,1.)

"""Warp clouds support the baseline and a texture-only foreground contract."""
from tests.support.session import component as _component, SessionTest, patch
import sys
import unittest
pass
import bpy
import numpy as np
samples = _component('ui.warp_samples')
pass


class WarpSampleTests(SessionTest):
    def tearDown(self):samples.clear()

    def test_pad_background_caches_only_compact_sector_textures(self):
        pad_background = _component('ui.pad_background')
        sectors=np.ones(48,dtype=np.float32)
        pad_background.clear()
        try:
            with patch.object(pad_background,'_upload_sectors',side_effect=lambda values:object()) as upload:
                first=pad_background.sector_texture(sectors)
                self.assertIs(pad_background.sector_texture(sectors),first)
                self.assertIs(first[0],sectors)
                upload.assert_called_once()
                changed=pad_background.sector_texture(np.zeros(48,dtype=np.float32))
                self.assertIsNot(changed,first)
                for _ in range(20):pad_background.sector_texture(np.ones(48,dtype=np.float32))
                self.assertLessEqual(len(pad_background._sectors),12)
                for values in (np.zeros(47),np.full(48,np.nan),np.full(48,-1.)):
                    with self.assertRaises(ValueError):pad_background.sector_texture(values)
        finally:pad_background.clear()

    def test_native_gpu_pad_sector_orientation_radius_and_upload_reuse(self):
        import gpu
        from mathutils import Matrix
        pad_background = _component('ui.pad_background')
        bpy.context.preferences.system.gpu_backend='METAL' if sys.platform=='darwin' else 'OPENGL'
        gpu.init();surface=gpu.types.GPUOffScreen(96,96)
        dark=np.zeros((5,5,4),np.float32);dark[...,3]=1.
        asset=dict(dark=dark,bright=np.ones_like(dark))
        sectors=np.zeros(48,np.float32);sectors[35]=1.;sectors[11]=.25
        plot=_component('ui.color_geometry').ABPlot((16,16,64,64),-1,1,-1,1)
        pad_background.clear()
        try:
            with surface.bind(),gpu.matrix.push_pop(),gpu.matrix.push_pop_projection(), \
                    patch.object(pad_background,'asset',return_value=asset), \
                    patch.object(pad_background,'_upload_sectors',wraps=pad_background._upload_sectors) as upload:
                gpu.state.viewport_set(0,0,96,96)
                gpu.matrix.load_matrix(Matrix.Identity(4))
                gpu.matrix.load_projection_matrix(Matrix(((2/96,0,0,-1),(0,2/96,0,-1),(0,0,-1,0),(0,0,0,1))))
                frame=gpu.state.active_framebuffer_get();frame.clear(color=(0,0,0,1));gpu.state.blend_set('ALPHA')
                pad_background.draw(plot,dict(sectors=sectors))
                batch=pad_background._batch;background=pad_background._background
                pad_background.draw(plot,dict(sectors=sectors))
                upload.assert_called_once()
                self.assertIs(pad_background._batch,batch);self.assertIs(pad_background._background,background)
                values=np.array(frame.read_color(0,0,96,96,4,0,'FLOAT')).reshape(96,96,4)
                # +b is left, -b is right. Quarter count means half radius.
                self.assertGreater(values[49,32,0],.99)
                self.assertGreater(values[47,58,0],.99)
                self.assertLess(values[46,68,0],.01)
                self.assertLess(values[49,48,0],.01)
                # Moving/resizing the same pad never rebuilds its geometry.
                pad_background.draw(_component('ui.color_geometry').ABPlot((15.5,15.5,66,66),-2,2,-2,2),dict(sectors=sectors))
                upload.assert_called_once();self.assertIs(pad_background._batch,batch)
                frame.clear(color=(0,0,0,1))
                pad_background.draw(plot,dict(sectors=sectors),neutral=True)
                values=np.array(frame.read_color(0,0,96,96,4,0,'FLOAT')).reshape(96,96,4)
                self.assertEqual(float(values[...,0].max()),0.)
        finally:
            surface.free();pad_background.clear()

    def test_native_gpu_pad_preserves_png_colors_across_framebuffer_formats(self):
        import gpu
        from mathutils import Matrix
        pad_background = _component('ui.pad_background')
        bpy.context.preferences.system.gpu_backend='METAL' if sys.platform=='darwin' else 'OPENGL'
        gpu.init();pad_background.clear()
        try:
            asset=pad_background.asset();n=asset['dark'].shape[0];extent=n+2
            # Align pixel centers with PNG texel centers, including neutral and
            # colored samples inside the radial histogram's maximum radius.
            plot=_component('ui.color_geometry').ABPlot((.5,.5,n-1,n-1),-1,1,-1,1)
            positions=((n//2,n//2),(3*n//4,n//2),(n//2,3*n//4))
            result=dict(sectors=np.ones(48,np.float32));cached=None
            for format in ('RGBA8','SRGB8_A8','RGBA8'):
                texture=gpu.types.GPUTexture((extent,extent),format=format)
                frame=gpu.types.GPUFrameBuffer(color_slots=(texture,))
                with frame.bind(),gpu.matrix.push_pop(),gpu.matrix.push_pop_projection():
                    gpu.state.viewport_set(0,0,extent,extent)
                    gpu.matrix.load_matrix(Matrix.Identity(4))
                    gpu.matrix.load_projection_matrix(Matrix(((2/extent,0,0,-1),(0,2/extent,0,-1),(0,0,-1,0),(0,0,0,1))))
                    gpu.state.blend_set('ALPHA')
                    for name in ('dark','bright'):
                        frame.clear(color=(0,0,0,1))
                        pad_background.draw(plot,result,neutral=name=='dark')
                        if cached is None:cached=(pad_background._shader,pad_background._background)
                        self.assertIs(pad_background._shader,cached[0])
                        self.assertIs(pad_background._background,cached[1])
                        for x,y in positions:
                            with self.subTest(format=format,layer=name,pixel=(x,y)):
                                actual=np.asarray(frame.read_color(x,y,1,1,4,0,'UBYTE')).reshape(4)
                                expected=np.rint(asset[name][y,x]*255)
                                np.testing.assert_allclose(actual,expected,rtol=0,atol=1)
        finally:pad_background.clear()

    def test_native_gpu_histogram_colors_match_builtin_with_selected_opacity(self):
        import gpu
        from mathutils import Matrix
        diagram = _component('ui.diagram'); theme = _component('ui.theme')
        bpy.context.preferences.system.gpu_backend='METAL' if sys.platform=='darwin' else 'OPENGL'
        gpu.init()
        result=dict(histograms={'low':np.array([1.,0.],np.float32),
                                'high':np.array([0.,1.],np.float32)})
        plot=_component('ui.color_geometry').ABPlot((16,16,64,64),-1,1,-1,1)
        cached=None
        for format in ('RGBA8','SRGB8_A8','RGBA8'):
            texture=gpu.types.GPUTexture((96,96),format=format)
            frame=gpu.types.GPUFrameBuffer(color_slots=(texture,))
            with frame.bind(),gpu.matrix.push_pop(),gpu.matrix.push_pop_projection():
                gpu.state.viewport_set(0,0,96,96)
                gpu.matrix.load_matrix(Matrix.Identity(4))
                gpu.matrix.load_projection_matrix(Matrix(((2/96,0,0,-1),(0,2/96,0,-1),(0,0,-1,0),(0,0,0,1))))
                gpu.state.blend_set('ALPHA')
                for selected in ('low','high'):
                    diagram.rectangle((0,0,96,96),theme.PLOT)
                    samples.draw_histograms(plot,result,('low','high'),selected)
                    if cached is None:cached=(samples._histogram_shader,next(iter(samples._histogram_textures.values())))
                    self.assertIs(samples._histogram_shader,cached[0])
                    self.assertIs(next(iter(samples._histogram_textures.values())),cached[1])
                    actual=[np.array(frame.read_color(x,32,1,1,4,0,'UBYTE')).reshape(4) for x in (32,64)]
                    # The legacy built-in renderer is the oracle for both RGB
                    # framebuffer transfer and unchanged .26/.055 blending.
                    diagram.rectangle((0,0,96,96),theme.PLOT)
                    for index,(name,color) in enumerate((('low',theme.ADAPTED),('high',theme.ORANGE))):
                        diagram.rectangle((16+index*32,16,32,64*.78),(*color[:3],.26 if name==selected else .055))
                        expected=np.array(frame.read_color(32+index*32,32,1,1,4,0,'UBYTE')).reshape(4)
                        with self.subTest(format=format,selected=selected,driver=name):
                            np.testing.assert_allclose(actual[index],expected,rtol=0,atol=1)

    def test_layer_filters_invalid_samples_and_preserves_relative_opacity(self):
        q=np.array([[.2,.3],[.4,.5],[np.nan,1],[np.inf,0],[0,0],[.6,.7]])
        weights=np.array([.25,2,1,1,0,np.nan])
        item=samples.layer(q,weights)
        np.testing.assert_allclose(item.positions[::6],[[.2,.3],[.4,.5]])
        np.testing.assert_array_equal(item.opacity[::6],[.25,1])
        self.assertIs(item.appearance,q);self.assertIs(item.weights,weights)
        self.assertIs(samples.layer(q,weights),item)
        self.assertEqual(item.positions.shape,(12,2))

    def test_cache_is_bounded_and_keeps_input_references(self):
        first=np.array([[.1,.2]])
        weights=np.array([.5]);item=samples.layer(first,weights)
        for i in range(samples.CACHE_LIMIT):samples.layer(np.array([[i,i]]),np.array([1.]))
        self.assertEqual(len(samples._layers),samples.CACHE_LIMIT)
        self.assertNotIn((id(first),id(weights),id(None)),samples._layers)
        self.assertIs(item.appearance,first)
        samples.clear();self.assertFalse(samples._layers)

    def test_energy_branch_is_cached_without_moving_published_coordinates(self):
        positions=np.array([[.2,.3],[.4,.5],[0.,1.]])
        weights=np.array([.5,.7,.3]);energy=np.array([1.,-1.,0.])
        item=samples.layer(positions,weights,energy)
        np.testing.assert_allclose(item.positions[::6],positions)
        np.testing.assert_array_equal(item.negative[::6],[0.,1.,0.])
        self.assertIs(item.energy,energy)
        self.assertIs(samples.layer(positions,weights,energy),item)
        self.assertIsNot(samples.layer(positions,weights,-energy),item)

    def test_external_selection_exposes_primary_membership_times_reference_alpha(self):
        from color_tools.perceptual_grade_core.model import scope_reference as reference
        signal=dict(alpha=np.array([.2,.5]),appearance=np.array([[40,1,2],[40,2,1]]),rgb=np.ones((2,3)))
        from types import SimpleNamespace
        primary=np.array([.5,.8])
        selection=dict(weights=primary,model=SimpleNamespace(tone=SimpleNamespace(space='ACEScg')))
        with patch.object(reference.cs,'output_waveform',return_value={'density':None}),\
                patch.object(reference.cs,'vectorscope',return_value=None):
            selected=reference.select(signal,selection,1.)
        np.testing.assert_allclose(selected['weights'],[.1,.4])
        self.assertIs(selected['primary_weights'],primary)

    def test_descriptor_covers_fractional_native_extent_without_editor_position(self):
        plot=_component('ui.color_geometry').ABPlot((16.25,20.75,409,409),-1,1,-2,2)
        view=samples.descriptor(plot,1.5)
        self.assertEqual(view,dict(width=410,height=410,rect=(.25,.75,409.,409.),
            scale=1.5,bounds=(-1.,-2.,1.,2.)))
        self.assertEqual(view,samples.descriptor(_component('ui.color_geometry').ABPlot((216.25,120.75,409,409),-1,1,-2,2),1.5))

    def test_selects_native_view_and_reuses_closest_old_view(self):
        plot=_component('ui.color_geometry').ABPlot((0,0,100,100),-1,1,-1,1)
        first=samples.descriptor(plot,1.)
        first['bounds']=(first['bounds'],)*4
        second={**first,'width':201,'height':201,'rect':(.25,.75,200,200),'scale':2.}
        other={'view':second};exact={'view':first}
        self.assertIs(samples.choose_raster(plot,1.,(other,exact),2),exact)
        resized=_component('ui.color_geometry').ABPlot((0,0,102,102),-1,1,-1,1)
        self.assertIs(samples.choose_raster(resized,1.,(other,exact),2),exact)
        self.assertIsNone(samples.choose_raster(plot,1.,(),2))

    def test_uploads_only_active_tone_and_layers_once_per_publication(self):
        pixels=np.zeros((2,4,5,7),dtype=np.uint8);pixels[1,2]=128
        with patch.object(samples,'upload_coverage',side_effect=lambda value:object()) as upload:
            first=samples.texture_layer(pixels,2,1)
            np.testing.assert_array_equal(upload.call_args.args[0],np.full((5,7),128/255,dtype=np.float32))
            self.assertIs(samples.texture_layer(pixels,2,1),first)
            self.assertEqual(upload.call_count,1)
            self.assertIsNot(samples.texture_layer(pixels,1,1),first)
            self.assertIsNot(samples.texture_layer(pixels,2,0),first)
            self.assertEqual(upload.call_count,3)
        self.assertTrue(all(item.pixels is pixels for item in samples._textures.values()))
        samples.clear();self.assertFalse(samples._textures)

    def test_texture_cache_is_bounded_and_releases_old_publications(self):
        with patch.object(samples,'upload_coverage',return_value=object()):
            first=np.zeros((1,4,2,2),dtype=np.uint8)
            samples.texture_layer(first,0,0)
            for _ in range(samples.CACHE_LIMIT):
                samples.texture_layer(np.zeros_like(first),0,0)
        self.assertEqual(len(samples._textures),samples.CACHE_LIMIT)
        self.assertNotIn((id(first),0,0),samples._textures)

    def test_texture_contract_never_falls_back_to_points_while_waiting(self):
        import gpu
        plot=_component('ui.color_geometry').ABPlot((0,0,100,100),-1,1,-1,1)
        with (patch.object(samples,'draw_layer',side_effect=AssertionError('point handoff')),
                patch.object(gpu.state,'blend_get',return_value='NONE'),
                patch.object(gpu.state,'blend_set') as blend):
            samples.draw(plot,{'_warp_clouds':(),'_warp_tone':0},{},1.)
        self.assertEqual(blend.call_args.args,('NONE',))

    def test_experiment_ignores_retained_jc_points_until_first_texture_publication(self):
        import gpu
        clouds = _component('scopes.clouds')
        plot=_component('ui.color_geometry').ABPlot((0,0,100,100),-1,1,-1,1)
        previous=dict(bounded_saturation=np.ones((2,2)),weights=np.ones(2),after_energy=np.ones(2))
        external=dict(signal=dict(bounded_saturation=np.ones((2,2)),energy=np.ones(2)),weights=np.ones(2))
        with (patch.object(clouds,'enabled',return_value=True),
              patch.object(samples,'draw_layer',side_effect=AssertionError('stale point handoff')),
              patch.object(gpu.state,'blend_get',return_value='NONE'),
              patch.object(gpu.state,'blend_set') as blend):
            samples.draw(plot,previous,external,1.)
            samples.draw(plot,None,external,1.)
        self.assertEqual(blend.call_args.args,('NONE',))
        self.assertFalse(samples._layers)

    def test_native_gpu_texture_draw_preserves_orientation_layer_order_and_reprojection(self):
        import gpu
        from mathutils import Matrix
        bpy.context.preferences.system.gpu_backend='METAL' if sys.platform=='darwin' else 'OPENGL'
        gpu.init()
        width=height=96;surface=gpu.types.GPUOffScreen(width,height)
        plot=_component('ui.color_geometry').ABPlot((16,16,64,64),-1,1,-1,1)
        view=samples.descriptor(plot,1.);view['bounds']=(view['bounds'],)*4
        pixels=np.zeros((2,4,64,64),dtype=np.uint8)
        pixels[0,2,40:42,48:50]=128  # row0 is bottom; chart (+.5,+.25).
        pixels[0,2,24,16]=255;pixels[1,2,24,16]=128
        raster=dict(view=view,pixels=pixels,backend='gpu')
        result={'_warp_clouds':(raster,),'_warp_tone':2}
        try:
            with surface.bind(),gpu.matrix.push_pop(),gpu.matrix.push_pop_projection():
                gpu.state.viewport_set(0,0,width,height)
                frame=gpu.state.active_framebuffer_get()
                gpu.matrix.load_matrix(Matrix.Identity(4))
                gpu.matrix.load_projection_matrix(Matrix(((2/width,0,0,-1),(0,2/height,0,-1),(0,0,-1,0),(0,0,0,1))))
                gpu.state.blend_set('NONE');frame.clear(color=(0,0,0,1))
                with (patch.object(samples,'upload_coverage',wraps=samples.upload_coverage) as upload,
                        patch.object(samples,'draw_layer',side_effect=AssertionError('point handoff'))):
                    samples.draw(plot,result,{},1.)
                    self.assertEqual(upload.call_count,2)
                    values=frame.read_color(0,0,width,height,4,0,'FLOAT')
                    values.dimensions=width*height*4;values=np.asarray(values).reshape(height,width,4)
                    blue=np.asarray(samples.theme.ADAPTED[:3]);red=np.asarray(samples.theme.COMPARISON[:3])
                    opacity=128/255
                    np.testing.assert_allclose(values[56,64,:3],blue*opacity,atol=.006)
                    np.testing.assert_allclose(values[40,32,:3],red*opacity+blue*(1-opacity),atol=.006)
                    self.assertEqual(np.count_nonzero(values[:16,:,:3]),0)
                    # A larger bound reprojects the cached image about neutral.
                    frame.clear(color=(0,0,0,1))
                    samples.draw(_component('ui.color_geometry').ABPlot((16,16,64,64),-2,2,-2,2),result,{},1.)
                    self.assertEqual(upload.call_count,2)
                    values=frame.read_color(0,0,width,height,4,0,'FLOAT')
                    values.dimensions=width*height*4;values=np.asarray(values).reshape(height,width,4)
                    self.assertGreater(float(values[52,56,:3].max()),0.)
                    self.assertEqual(float(values[56,64,:3].max()),0.)
                self.assertEqual(gpu.state.blend_get(),'NONE')
        finally:surface.free()

    def test_native_gpu_texture_matches_fractional_and_scaled_pad_pixels(self):
        import gpu
        from mathutils import Matrix
        bpy.context.preferences.system.gpu_backend='METAL' if sys.platform=='darwin' else 'OPENGL'
        gpu.init()
        width=height=192;surface=gpu.types.GPUOffScreen(width,height)
        q=np.array([[.25,-.5],[0.,1.],[0.,-1.],[.015625,-.015625],[-.8,.5]])
        weights=np.array([.5,1.,1.,.7,.8]);energy=np.array([1.,1.,1.,-1.,1.])
        try:
            with surface.bind(),gpu.matrix.push_pop(),gpu.matrix.push_pop_projection():
                gpu.state.viewport_set(0,0,width,height)
                frame=gpu.state.active_framebuffer_get()
                gpu.matrix.load_matrix(Matrix.Identity(4))
                gpu.matrix.load_projection_matrix(Matrix(((2/width,0,0,-1),(0,2/height,0,-1),(0,0,-1,0),(0,0,0,1))))
                for scale in (1.,2.):
                    plot=_component('ui.color_geometry').ABPlot((16.25,16.75,64*scale,64*scale),-1,1,-1,1)
                    view=samples.descriptor(plot,scale);view['bounds']=(view['bounds'],)*4
                    frame.clear(color=(0,0,0,1));gpu.state.blend_set('ALPHA')
                    samples.draw_layer(plot,q,weights,(1,1,1,1),scale,energy)
                    coverage=frame.read_color(0,0,width,height,4,0,'UBYTE')
                    coverage.dimensions=width*height*4
                    coverage=np.array(coverage).reshape(height,width,4)[:,:,0]
                    pixels=np.zeros((1,4,view['height'],view['width']),dtype=np.uint8)
                    pixels[0,1]=coverage[16:16+view['height'],16:16+view['width']]
                    raster=dict(view=view,pixels=pixels,backend='gpu')
                    frame.clear(color=(0,0,0,1));gpu.state.blend_set('NONE')
                    samples.draw(plot,{'_warp_clouds':(raster,),'_warp_tone':1},None,scale)
                    values=frame.read_color(0,0,width,height,4,0,'FLOAT')
                    values.dimensions=width*height*4
                    values=np.asarray(values).reshape(height,width,4)
                    expected=coverage[:,:,None]/255.*np.asarray(samples.theme.ADAPTED[:3])
                    np.testing.assert_allclose(values[:,:,:3],expected,atol=.004)
        finally:surface.free()

    def test_native_gpu_draws_oriented_clipped_weighted_layers_and_reuses_batches(self):
        import gpu
        from mathutils import Matrix
        bpy.context.preferences.system.gpu_backend='METAL' if sys.platform=='darwin' else 'OPENGL'
        gpu.init()
        width=height=96;surface=gpu.types.GPUOffScreen(width,height)
        plot=_component('ui.color_geometry').ABPlot((16,16,64,64),-1,1,-1,1)
        # Primary: (-b,+a) = (+.5,+.25); external: (-.5,-.25).
        q=np.array([[.25,-.5],[0,-2],[0,1.],[.015625,-.015625]])
        result=dict(bounded_saturation=q,weights=np.array([.5,1,1,.7]),
                    after_energy=np.array([1.,1.,0.,-1.]))
        external=dict(signal={'bounded_saturation':np.array([[-.25,.5]]),'energy':np.array([1.])},weights=np.array([1.]))
        try:
            with surface.bind(),gpu.matrix.push_pop(),gpu.matrix.push_pop_projection():
                gpu.state.viewport_set(0,0,width,height)
                frame=gpu.state.active_framebuffer_get();frame.clear(color=(0,0,0,1))
                gpu.matrix.load_matrix(Matrix.Identity(4))
                gpu.matrix.load_projection_matrix(Matrix(((2/width,0,0,-1),(0,2/height,0,-1),(0,0,-1,0),(0,0,0,1))))
                gpu.state.blend_set('NONE')
                from gpu_extras.batch import batch_for_shader
                with patch('gpu_extras.batch.batch_for_shader',wraps=batch_for_shader) as batches:
                    samples.draw(plot,result,external,1.)
                    self.assertEqual(batches.call_count,2)
                    # Different view geometry is a uniform update only.
                    samples.draw(_component('ui.color_geometry').ABPlot((16,16,64,64),-2,2,-2,2),result,external,1.)
                    self.assertEqual(batches.call_count,2)
                self.assertEqual(gpu.state.blend_get(),'NONE')
                pixels=frame.read_color(0,0,width,height,4,0,'FLOAT');pixels.dimensions=width*height*4
                values=np.asarray(pixels).reshape(height,width,4)
                blue=values[55,63,:3];red=values[39,31,:3]
                np.testing.assert_allclose(blue,np.array(samples.theme.ADAPTED[:3])*.175,atol=.006)
                np.testing.assert_allclose(red,np.array(samples.theme.COMPARISON[:3])*.35,atol=.006)
                # Negative energy has the same data position but a hollow mark.
                np.testing.assert_array_equal(values[48,48,:3],[0.,0.,0.])
                self.assertGreater(np.max(values[48,49,:3]),0.)
                self.assertEqual(np.count_nonzero(values[:16,:,:3]),0)
                self.assertEqual(np.count_nonzero(values[:,:16,:3]),0)
                self.assertEqual(np.count_nonzero(values[80:,:,:3]),0)
                self.assertEqual(np.count_nonzero(values[:,80:,:3]),0)
        finally:surface.free()

    def test_native_gpu_active_density_and_instanced_histograms_reuse_uploads(self):
        import gpu
        from mathutils import Matrix
        bpy.context.preferences.system.gpu_backend='METAL' if sys.platform=='darwin' else 'OPENGL'
        gpu.init()
        surface=gpu.types.GPUOffScreen(96,96)
        levels=np.array([[0,7],[3,0]],dtype=np.uint8)
        result=dict(histograms={'low':np.array([0.,1.],dtype=np.float32),
                                'high':np.array([0.,0.],dtype=np.float32)})
        plot=_component('ui.color_geometry').ABPlot((16,16,64,64),-1,1,-1,1)
        try:
            with surface.bind(),gpu.matrix.push_pop(),gpu.matrix.push_pop_projection():
                gpu.state.viewport_set(0,0,96,96)
                gpu.matrix.load_matrix(Matrix.Identity(4))
                gpu.matrix.load_projection_matrix(Matrix(((2/96,0,0,-1),(0,2/96,0,-1),(0,0,-1,0),(0,0,0,1))))
                frame=gpu.state.active_framebuffer_get();frame.clear(color=(0,0,0,1));gpu.state.blend_set('ALPHA')
                with patch.object(samples,'upload_coverage',wraps=samples.upload_coverage) as upload:
                    samples.draw_density(plot.rect,levels,(1,1,1,1))
                    samples.draw_density(plot.rect,levels,(1,1,1,1))
                    self.assertEqual(upload.call_count,1)
                values=frame.read_color(0,0,96,96,4,0,'FLOAT');values.dimensions=96*96*4
                values=np.asarray(values).reshape(96,96,4)
                self.assertEqual(float(values[24,24,0]),0.)
                self.assertGreater(float(values[24,64,0]),.99)
                frame.clear(color=(0,0,0,1))
                samples.draw_histograms(plot,result,('low','high'),'low')
                cached=next(iter(samples._histogram_textures.values()))
                samples.draw_histograms(plot,result,('low','high'),'high')
                self.assertIs(next(iter(samples._histogram_textures.values())),cached)
                values=frame.read_color(0,0,96,96,4,0,'FLOAT');values.dimensions=96*96*4
                values=np.asarray(values).reshape(96,96,4)
                self.assertEqual(float(values[24,24,:3].max()),0.)
                self.assertGreater(float(values[24,64,:3].max()),0.)
                self.assertEqual(float(values[76,64,:3].max()),0.)
        finally:surface.free()


if __name__=='__main__':unittest.main()

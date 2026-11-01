"""Actual complete-LUT Shader/Compositor execution against the Colour oracle."""
from tests.support.session import component as _component, SessionTest, patch
from pathlib import Path
import sys
import tempfile
pass
import bpy
import numpy as np
gpu = _component('graph.gpu'); nodes = _component('graph.nodes'); lut = _component('graph.lut'); stacks = _component('graph.stacks'); grades = _component('graph.grades')
from color_tools.perceptual_grade_core.model import lut as cubes
from tests.support import reference as oracle
from tests.support.blender import BlenderTest, render, render_scene,sequence


class RenderTests(BlenderTest):
    def setUp(self):
        super().setUp()
        cpu=patch.object(gpu,'acquire',return_value=(None,None));cpu.start();self.addCleanup(cpu.stop)

    def test_paired_stack_compositor_preserves_signed_hdr_and_alpha(self):
        scene,_=render_scene();tree=bpy.data.node_groups.new('Inverse render','CompositorNodeTree')
        tree.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
        a=nodes.create_grade(tree);nodes.write_chromatic(a,{'global_gain':10.})
        b=nodes.create_grade(tree);b.pg_grade=a.pg_grade;grades.new(b)
        grades.write_matrix(b.pg_grade,((.001,.0008,0.),(0.,.001,0.),(0.,0.,.001)))
        stack=sequence(tree,[a.pg_grade,b.pg_grade]);stack.pg_stack_entries[1].direction='INVERSE'
        native=np.tile([[0.,10.,0.],[20.,0.,20.],[.1,.2,.3],[0,0,0]],(16,1))
        rgb=(native@cubes.FROM_LUT.T).astype('f4').reshape(8,8,3)
        image=bpy.data.images.new('Inverse probes',width=8,height=8,float_buffer=True,alpha=True)
        image.colorspace_settings.name='Non-Color';image.alpha_mode='PREMUL'
        image.pixels.foreach_set(np.concatenate((rgb,np.full((8,8,1),.4,dtype='f4')),-1).ravel());image.update()
        source=tree.nodes.new('CompositorNodeImage');source.image=image
        output=tree.nodes.new('NodeGroupOutput');output.is_active_output=True
        tree.links.new(source.outputs['Image'],stack.inputs['Color']);tree.links.new(stack.outputs['Color'],output.inputs['Image'])
        scene.compositing_node_group=tree;expected=stacks.model(stack).apply(rgb.astype(float))
        self.assertLess(expected.min(),0);self.assertGreater(expected.max(),1024)
        with tempfile.TemporaryDirectory() as directory:
            for device in ('CPU','GPU'):
                scene.render.compositor_device=device;actual=render(Path(directory)/(device+'.exr'))
                np.testing.assert_allclose(actual[...,:3],expected,rtol=3e-6,atol=2e-4)
                np.testing.assert_allclose(actual[...,3],.4,rtol=0,atol=1e-7)
        self.assertEqual(lut.installed_cube(stack).size,65)

    def test_white_chroma_plus_ten_exports_nonnegative_acescg_before_aces2(self):
        scene,_=render_scene()
        tree=bpy.data.node_groups.new('White chroma trial','CompositorNodeTree')
        tree.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
        grade=nodes.create_grade(tree)
        nodes.write_chromatic(grade,{'c_high_2':10.})
        native=np.array([[.2,0,0],[0,.2,0],[.15,.02,.01],[.01,.15,.02]])
        rgb=np.tile(native@cubes.FROM_LUT.T,(16,1)).astype('f4').reshape(8,8,3)
        image=bpy.data.images.new('Saturated trial',width=8,height=8,float_buffer=True,alpha=True)
        image.colorspace_settings.name='Non-Color';image.alpha_mode='PREMUL'
        image.pixels.foreach_set(np.concatenate((rgb,np.ones((8,8,1),dtype='f4')),-1).ravel());image.update()
        source=tree.nodes.new('CompositorNodeImage');source.image=image
        output=tree.nodes.new('NodeGroupOutput');output.is_active_output=True
        tree.links.new(source.outputs['Image'],grade.inputs['Color'])
        tree.links.new(grade.outputs['Color'],output.inputs['Image'])
        scene.compositing_node_group=tree;scene.render.compositor_device='CPU'
        expected=oracle.lut(rgb,nodes.settings(grade))
        with tempfile.TemporaryDirectory() as directory:actual=render(Path(directory)/'white-chroma.exr')[...,:3]
        self.assertLess(float(oracle.error(actual,expected).max()),.002)
        exported=actual@cubes.TO_LUT.T
        self.assertTrue((exported>=-2e-7).all())
        # Use the OCIO library/config already shipped in the pinned bpy wheel.
        resources=Path(bpy.utils.resource_path('LOCAL'))
        site=resources/'python/lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
        with patch.object(sys,'path',[str(site),*sys.path]):
            import PyOpenColorIO as ocio
        config=ocio.Config.CreateFromFile(str(resources/'datafiles/colormanagement/config.ocio'))
        processor=config.getProcessor(ocio.DisplayViewTransform(src='ACEScg',display='sRGB',view='ACES 2.0')).getDefaultCPUProcessor()
        viewed=np.array([processor.applyRGB(row.tolist()) for row in exported.reshape(-1,3)])
        clipped=np.array([processor.applyRGB(np.maximum(row,0).tolist()) for row in exported.reshape(-1,3)])
        self.assertTrue(np.isfinite(viewed).all())
        np.testing.assert_allclose(viewed,clipped,rtol=0,atol=2e-6)

    def test_compositor_complete_lut_preserves_alpha(self):
        scene,_=render_scene()
        tree=bpy.data.node_groups.new('Render compositor','CompositorNodeTree')
        tree.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
        grade=nodes.create_grade(tree)
        nodes.write_values(grade,{'exposure':.3,'cr_balance':.05})
        nodes.write_tone(grade,{'input_midtones':42,'input_white':230})
        nodes.write_chromatic(grade,{'global_gain':2.,'web_hue_1_0':8,'web_chroma_1_1':.1})
        source=tree.nodes.new('CompositorNodeImage')
        image=bpy.data.images.new('Render probes',width=8,height=8,float_buffer=True,alpha=True)
        image.colorspace_settings.name='Non-Color';image.alpha_mode='PREMUL'
        ids=np.arange(64)*3201+991
        rgb=(cubes.lattice()[ids]@cubes.FROM_LUT.T).astype('f4').reshape(8,8,3)
        levels=np.array([128,512,743.19103667,1024])
        native=np.concatenate((levels[:,None]*np.ones((1,3)),
                               levels[:,None]*np.array([[1,.4,.1]])))
        rgb[0]=(native@cubes.FROM_LUT.T).astype('f4')
        image.pixels.foreach_set(np.concatenate((rgb,np.full((8,8,1),.4,dtype='f4')),-1).ravel());image.update()
        source.image=image
        output=tree.nodes.new('NodeGroupOutput');output.is_active_output=True
        tree.links.new(source.outputs['Image'],grade.inputs['Color']);tree.links.new(grade.outputs['Color'],output.inputs['Image'])
        scene.compositing_node_group=tree;scene.render.compositor_device='CPU'
        expected=oracle.lut(rgb,nodes.settings(grade))
        # The adopted fitted boundary can escape the cube. Render its signed
        # samples faithfully; there is no additional final RGB clamp.
        self.assertTrue(np.isfinite(expected).all())
        self.assertLess(float((expected@cubes.TO_LUT.T).min()),0)
        with tempfile.TemporaryDirectory() as directory:actual=render(Path(directory)/'compositor.exr')
        self.assertLess(float(oracle.error(actual[...,:3],expected).max()),.002)
        np.testing.assert_allclose(actual[...,3],.4,atol=1e-7,rtol=0)
        self.assertEqual(grade['_pg_cube_backend'],'CPU')
        self.assertEqual(lut.installed_cube(grade).size,65)

    def test_shader_complete_lut_and_fresh_interface(self):
        _,world=render_scene();grade=nodes.create_grade(world.node_tree)
        nodes.write_values(grade,{'exposure':.2})
        nodes.write_tone(grade,{'input_midtones':42,'input_white':230})
        nodes.write_chromatic(grade,{'global_gain':.1,'web_hue_1_0':8,'web_chroma_1_1':.1})
        probe=cubes.lattice()[16*65**2+20*65+24]@cubes.FROM_LUT.T
        grade.inputs['Color'].default_value=(*probe,1)
        world.node_tree.links.new(grade.outputs['Color'],world.node_tree.nodes['Background'].inputs['Color'])
        stored=np.asarray(grade.inputs['Color'].default_value[:3])
        expected=oracle.settings(stored,nodes.settings(grade))
        with tempfile.TemporaryDirectory() as directory:actual=render(Path(directory)/'shader.exr')[0,0,:3]
        self.assertLess(float(oracle.error(actual,expected)),.002)
        self.assertIn('Color Reference',grade.inputs)
        self.assertNotIn('Matrix R',grade.inputs)
        self.assertFalse(hasattr(bpy.types.Node,'pg_render_quality'))
        self.assertEqual(grade['_pg_cube_backend'],'CPU')

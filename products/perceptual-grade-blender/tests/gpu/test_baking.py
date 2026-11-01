"""CPU worker publication plus actual GPU LUT compositor and image-scope sampling."""
from tests.support.session import component as _component, SessionTest, patch
from pathlib import Path
from collections import OrderedDict
import sys
import os
import tempfile
import time
from types import SimpleNamespace
pass
import bpy
import numpy as np
acceleration = _component('graph.gpu'); lut = _component('graph.lut'); nodes = _component('graph.nodes'); stacks = _component('graph.stacks')
from color_tools.perceptual_grade_blender.model import baking, gpu as compute
from color_tools.perceptual_grade_core.model import lut as cubes, scope_color
sampling = _component('scopes.sampling')
from tests.support import reference as oracle
from tests.support.blender import BlenderTest, render, render_scene, grade_data, sequence, wait_for_scopes
from tests.support.gpu import initialize


class BakingTests(BlenderTest):
    def setUp(self):
        super().setUp();self.gpu=initialize()

    def test_helper_gpu_probe_cannot_hide_cpu_fallback(self):
        pass
        handle=_component('services').get_runtime().retry_gpu()
        result=handle.result(timeout=120)
        self.assertEqual(handle.backend,'gpu')
        self.assertEqual(result['backend'],'GPU')
        self.assertTrue(result['conformance'])
        self.assertEqual(result['checks'],('forward','inverse','power','angle'))
        self.assertLessEqual(result['numerical']['power_max_ulp'],3)
        self.assertNotEqual(result['worker_pid'],os.getpid())
        self.assertTrue(result['device'].startswith(self.gpu.platform.backend_type_get()))

    def test_bounded_and_general_shader_hues_match_cpu(self):
        from color_tools.perceptual_grade_blender.model.boundary_gpu import Program,header
        def source(data,offsets,expanded):
            return header(data,offsets,expanded)+'''\nvoid main() {
                int id=int(gl_GlobalInvocationID.x);if(id>=sample_count)return;
                ivec2 address=ivec2(id%256,id/256);
                float h=texelFetch(input_pixels,address,0).x;int face;
                float capacity=pg_capacity(0.5,h,face);
                imageStore(output_pixels,address,vec4(pg_mod(h),float(face),capacity,1.0));
            }'''
        data,table=baking.resource();program=Program(data,source,expanded=table.expanded)
        rng=np.random.default_rng(5252);tau=np.float32(2*np.pi)
        bits=rng.integers(0,2**32,8192,dtype='u4').view('f4')
        seams=np.arange(-12,13,dtype='f4')*tau
        hue=np.r_[bits[np.isfinite(bits)],rng.uniform(-2*tau,2*tau,8192).astype('f4'),
            seams,np.nextafter(seams,np.float32(-np.inf)),np.nextafter(seams,np.float32(np.inf))]
        actual=program.evaluate(hue[:,None])
        np.testing.assert_array_equal(actual[:,0],np.remainder(hue,tau))
        np.testing.assert_array_equal(actual[:,1],table.selector.select(.5,hue)[0])
        np.testing.assert_allclose(actual[:,2],table.capacity(.5,hue),rtol=1e-6,atol=0)

    def test_native_stage_one_then_input_repair_preserves_extremes_and_alpha(self):
        scene,_=render_scene()
        tree=bpy.data.node_groups.new('Pending compositor','CompositorNodeTree')
        tree.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
        node=tree.nodes.new('CompositorNodeGroup');node.node_tree=lut.make_kernel('CompositorNodeTree','FORWARD')
        spaces = _component('graph.spaces')
        matrix=np.array([[64.,8.,0.],[0.,32.,4.],[0.,0.,64.]])
        spaces.uniforms(node,matrix@cubes.TO_LUT,cubes.FROM_LUT)
        native=np.array([[.2,.3,.4],[-.1,.4,.5],[-.8,.01,.01],[0,0,0],
                         [2048,400,1],[1e37,-.1,1],[1024,.1,.2],[-3000,4000,10]])
        rgb=np.tile(native@cubes.FROM_LUT.T,(8,1)).astype('f4').reshape(8,8,3)
        image=bpy.data.images.new('Pending probes',width=8,height=8,float_buffer=True,alpha=True)
        image.colorspace_settings.name='Non-Color';image.alpha_mode='PREMUL'
        image.pixels.foreach_set(np.concatenate((rgb,np.full((8,8,1),.4,dtype='f4')),-1).ravel());image.update()
        source=tree.nodes.new('CompositorNodeImage');source.image=image
        output=tree.nodes.new('NodeGroupOutput');output.is_active_output=True
        tree.links.new(source.outputs['Image'],node.inputs['Color'])
        tree.links.new(node.outputs['Color'],output.inputs['Image'])
        scene.compositing_node_group=tree
        from color_tools.perceptual_grade_reference.export import input_repair
        expected=input_repair(rgb.astype(float)@cubes.TO_LUT.T@matrix.T,cubes.AP1_Y)@cubes.FROM_LUT.T
        with tempfile.TemporaryDirectory() as directory:
            for device in ('CPU','GPU'):
                scene.render.compositor_device=device
                actual=render(Path(directory)/(device+'.exr'))
                np.testing.assert_allclose(actual[...,:3],expected,rtol=3e-6,atol=2e-7)
                np.testing.assert_allclose(actual[...,3],.4,atol=1e-7,rtol=0)
                np.testing.assert_array_equal(actual[0,2,:3],0.)
        self.assertIsNone(lut.image_for(node))

    def pump(self,condition,timeout=20):
        deadline=time.monotonic()+timeout
        while not condition() and time.monotonic()<deadline:
            lut.tick();time.sleep(.001)
        self.assertTrue(condition(),'Baking did not reach the required state')

    def test_shared_glsl_parity_and_adopted_oracle_error(self):
        from tests.reference.legacy_capacity import LegacyCapacityModel
        from color_tools.perceptual_grade_core.model.bake import Kernel
        from tools.analysis.bake_check import cases,metrics
        from tools.build.boundary_oracle import exact_geometry
        data,table=baking.resource();axis=cubes.axis()[::4].astype('f4')
        rgb=np.vstack((np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),-1).reshape(-1,3),
            [[1024,1024,714.0458374023438],[.0253184813856082,.0071734681614134,.0043407546657122],
             [800,64,256]])).astype('f4')
        program=None
        for name,settings in cases():
            with self.subTest(grade=name):
                # The Blender export now includes the reference H-K guard.
                oracle=LegacyCapacityModel(settings,space='ACEScg')
                kernel=Kernel(data,oracle.tone,oracle.color,table,hk_guard=True)
                if program is None:
                    program=compute.Program(kernel)
                    codes=np.rint(np.array(program.face_atlas.read(),dtype='f4')*np.float32(65535)).astype('u2')
                    np.testing.assert_array_equal(codes.ravel(),table.expanded['face_codes'].ravel())
                    self.assertLessEqual(program.lookup_bytes,1024**2)
                else:program.set_kernel(kernel)
                with exact_geometry():expected=oracle.forward_native(rgb.astype(float))
                actual=program.evaluate(rgb)[:,:3]
                for reference,limit in ((expected,7.),(kernel.evaluate(rgb).astype(float),1.)):
                    result=metrics(actual,reference)
                    self.assertTrue(result['finite']);self.assertEqual(result['black_mismatches'],0)
                    self.assertLessEqual(result['maximum_tolerance_fraction'],limit,result)

    def test_selective_adaptance_raw_shader_matches_cpu_and_reference(self):
        from color_tools.perceptual_grade_blender.model import bake_gpu
        from color_tools.perceptual_grade_core.model.bake import Kernel
        from color_tools.perceptual_grade_blender.model.boundary_gpu import Program
        from color_tools.perceptual_grade_reference.grading import ColorSettings
        from color_tools.perceptual_grade_reference.model import Settings
        from tests.reference.legacy_capacity import LegacyCapacityModel
        from color_tools.perceptual_grade_reference.responses import State,signed_hk
        from color_tools.perceptual_grade_core.model.tonal_web import WebSettings
        def source(data,offsets,expanded):
            shared=bake_gpu.source(data,offsets,expanded)
            return shared[:shared.rindex('void main()')]+'''\nvoid main() {
                int id=int(gl_GlobalInvocationID.x);if(id>=sample_count)return;
                ivec2 address=ivec2(id%256,id/256);
                vec4 q=texelFetch(input_pixels,address,0);
                imageStore(output_pixels,address,operation==0?pg_grade(q):q);
            }'''
        data,table=baking.resource();program=Program(data,source,True,table.expanded)
        targets=((1.,-2.),(-3.,2.),(2.,3.),(-1.,2.))
        web=WebSettings(log_chroma=((.15,-.1,.1,-.15,.2,-.1),)*4,
            hue_degrees=((8.,-4.,6.,-8.,4.,-6.),)*4,log_scale=((.15,-.1,.1,0.,-.15,.2),)*4)
        ja,c,angle=np.meshgrid([-600.,-100.,-1.,0.,1.,100.,600.,3000.],
            [0.,.001,10.,200.,1000.],[-2.,0.,1.],indexing='ij')
        signed=np.stack((signed_hk(ja,c),c*np.cos(angle),c*np.sin(angle),ja*abs(ja)),-1).reshape(-1,4).astype('f4')
        for reach in (.05,.25,1.):
            for mixed in (False,True):
                with self.subTest(reach=reach,mixed=mixed):
                    model=LegacyCapacityModel(Settings(color=ColorSettings(adaptance=targets,adaptance_half_saturation=reach,
                        web=web if mixed else WebSettings())))
                    kernel=Kernel(data,model.tone,model.color,table)
                    neutral=np.column_stack((kernel.anchors,np.zeros((4,2),dtype='f4'),kernel.anchors*kernel.anchors))
                    raw=np.concatenate((neutral,signed),axis=0)
                    bake_gpu.Program.set_kernel(program,kernel)
                    actual=program.evaluate(raw,operation=0);cpu=kernel.grade(raw)
                    expected=model.color.apply_state(State(raw[:,:3].astype(float),raw[:,3].astype(float)))
                    expected=np.column_stack((expected.q,expected.energy))
                    self.assertTrue(np.isfinite(actual).all())
                    for wanted in (cpu,expected):
                        scale=1+np.max(abs(wanted[:,:3]),axis=-1)
                        self.assertLess(float(np.max(np.max(abs(actual[:,:3]-wanted[:,:3]),axis=-1)/scale)),5e-5)
                        escale=1+abs(raw[:,3].astype(float))+66*np.hypot(raw[:,1].astype(float),raw[:,2].astype(float))
                        self.assertLess(float(np.max(abs(actual[:,3]-wanted[:,3])/escale)),1e-5)
                    if not mixed:
                        np.testing.assert_allclose(actual[:4,1:3],targets,rtol=3e-5,atol=6e-5)
                        np.testing.assert_array_equal(actual[:4,3],neutral[:,3])
                        np.testing.assert_array_equal(actual[np.all(raw==0,axis=-1)],0.)

    def test_gpu_helper_progressive_values_and_worker_packing(self):
        tree=bpy.data.node_groups.new('GPU scheduler','CompositorNodeTree');node=nodes.create_grade(tree)
        lut.ensure(node,nodes.bake_model(node));nodes.write_chromatic(node,{'global_gain':.2})
        state=lut._states[node.as_pointer()];state['due']=0
        with patch.object(compute.Baker,'evaluate_rows',side_effect=AssertionError('Foreground dispatch')), \
             patch.object(baking,'prepared',side_effect=AssertionError('Foreground packing')):
            self.pump(lambda:state['preview_published'])
            snapshot=lut.installed_cube(node).values.copy()
            self.pump(lambda:state['final_published'])
        self.assertEqual(node['_pg_cube_backend'],'GPU')
        np.testing.assert_array_equal(lut.installed_cube(node).values[::2,::2,::2],snapshot)
        self.assertNotEqual(lut.installed_cube(node).diagnostics['worker_pid'],os.getpid())

    def test_failed_gpu_job_restarts_on_cpu_and_retains_installed_image(self):
        pass
        tree=bpy.data.node_groups.new('GPU fallback','ShaderNodeTree');node=nodes.create_grade(tree)
        lut.ensure(node,nodes.bake_model(node));old=lut.image_for(node)
        nodes.write_chromatic(node,{'global_gain':.2});state=lut._states[node.as_pointer()];state['due']=0
        runtime=_component('services').get_runtime()
        self.pump(lambda:state['baker'].handle is not None and runtime.helpers.get('gpu') is not None
            and runtime.helpers['gpu'].active is state['baker'].handle._job)
        runtime.helpers['gpu'].kill()
        self.pump(lambda:state['baker'].backend=='CPU')
        self.assertEqual(lut.image_for(node),old)
        self.assertIsInstance(state['baker'].fallback_reason,str)
        self.assertTrue(state['baker'].fallback_reason)
        self.assertFalse(node.get('_pg_bake_error'))
        self.pump(lambda:state['final_published'])
        self.assertEqual(node['_pg_cube_backend'],'CPU')
        self.assertEqual(lut.installed_cube(node).signature,cubes.signature(nodes.bake_model(node)))

    @patch.object(acceleration,'acquire',return_value=(None,None))
    def test_cpu_workers_preview_refinement_preserves_nested_values(self,_acquire):
        tree=bpy.data.node_groups.new('CPU scheduler','ShaderNodeTree')
        node=nodes.create_grade(tree)
        nodes.write_tone(node,{'input_midtones':42})
        nodes.write_chromatic(node,{'global_gain':.1})
        state=lut._states[node.as_pointer()];state['due']=0
        self.pump(lambda:state['preview_published'])
        preview=lut.installed_cube(node);self.assertEqual(preview.size,33)
        snapshot=preview.values.copy()
        self.pump(lambda:lut.installed_cube(node).size==65)
        np.testing.assert_array_equal(lut.installed_cube(node).values[::2,::2,::2],snapshot)
        self.assertEqual(node['_pg_cube_backend'],'CPU')
        self.assertFalse(hasattr(bpy.types.Node,'pg_render_quality'))
        for name in ('analytic','curves'):
            self.assertNotIn('color_tools.perceptual_grade_blender.model.'+name,sys.modules)
        data=grade_data();stack=sequence(tree,[data])
        self.assertEqual(stack.pg_stack_entries[0].direction,'FORWARD')
        self.assertIsNone(bpy.types.Operator.bl_rna_get_subclass_py('PERCEPTUAL_GRADE_OT_stack_inverse',None))


    @patch.object(acceleration,'acquire',return_value=(None,None))
    def test_cpu_failure_retains_last_lut_and_propagates(self,_acquire):
        pass
        tree=bpy.data.node_groups.new('Bake failure','ShaderNodeTree');node=nodes.create_grade(tree)
        lut.ensure(node,nodes.bake_model(node));old=lut.image_for(node)
        nodes.write_chromatic(node,{'global_gain':.1})
        with patch.object(_component('jobs.baker').RemoteBaker,'result',side_effect=ArithmeticError('evaluation fixture')):
            with self.assertRaisesRegex(ArithmeticError,'evaluation fixture'):lut.ensure(node,nodes.bake_model(node))
        self.assertEqual(lut.image_for(node),old)
        self.assertNotEqual(lut.installed_cube(node).signature,cubes.signature(nodes.bake_model(node)))

    def test_gpu_compositor_projected_inputs_alpha_and_scopes(self):
        scene,_=render_scene()
        tree=bpy.data.node_groups.new('GPU compositor','CompositorNodeTree')
        tree.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
        node=nodes.create_grade(tree)
        nodes.write_values(node,{'exposure':.3,'cr_balance':.05})
        nodes.write_tone(node,{'input_midtones':42})
        nodes.write_chromatic(node,{'global_gain':2.,'j_high_1':-2})
        rng=np.random.default_rng(772)
        native=rng.uniform(.005,2,(8,8,3));native[0,:4]=[[-.01,.4,1],[1026,1,.4],[0,0,0],[-1,-1,-1]]
        levels=np.array([128,512,743.19103667,1024])
        native[1]=np.concatenate((levels[:,None]*np.ones((1,3)),
                                 levels[:,None]*np.array([[1,.4,.1]])))
        rgb=(native@cubes.FROM_LUT.T).astype('f4')
        image=bpy.data.images.new('GPU probes',width=8,height=8,float_buffer=True,alpha=True)
        image.colorspace_settings.name='Non-Color';image.alpha_mode='PREMUL'
        rgba=np.concatenate((rgb,np.full((8,8,1),.4,dtype='f4')),-1)
        image.pixels.foreach_set(rgba.ravel());image.update()
        source=tree.nodes.new('CompositorNodeImage');source.image=image
        output=tree.nodes.new('NodeGroupOutput');output.is_active_output=True
        tree.links.new(source.outputs['Image'],node.inputs['Color']);tree.links.new(node.outputs['Color'],output.inputs['Image'])
        scene.compositing_node_group=tree;scene.render.compositor_device='GPU'
        expected=oracle.lut(rgb,nodes.settings(node))
        self.assertTrue(np.isfinite(expected).all())
        with tempfile.TemporaryDirectory() as directory:actual=render(Path(directory)/'gpu-compositor.exr')
        self.assertLess(float(oracle.error(actual[...,:3],expected).max()),.002)
        native_actual=actual[...,:3]@cubes.TO_LUT.T
        # The adopted table's signed overshoot survives publication and RGBE.
        self.assertLess(float(native_actual.min()),0)
        np.testing.assert_allclose(actual[...,3],.4,atol=1e-7,rtol=0)
        self.assertEqual(node['_pg_cube_backend'],'GPU')
        base=wait_for_scopes(node)
        spec=sampling.describe(node,nodes.grading_space(node))
        try:snapshot=sampling.capture(spec)
        finally:sampling.release(spec)
        analysis=sampling.evaluate_snapshot(snapshot,OrderedDict())
        # Regular Grade scopes use the frozen analytical Stage-2 appearance;
        # the compositor's installed LUT remains independently verified above.
        self.assertNotIn('grade_output_rgb',analysis)
        self.assertEqual(base['_scope_evaluation'][0],'regular-grade-appearance')
        self.assertTrue(np.isfinite(analysis['stage2_appearance'].q).all())
        from color_tools.perceptual_grade_core.model.forward import Model
        from color_tools.perceptual_grade_core.model.saturation import bounded_project
        viewed=base['_colors'][1]
        engine=Model(base['model'],viewed['model'])
        q,energy,native=engine.guarded_appearance(analysis['stage2_appearance'])
        np.testing.assert_array_equal(viewed['after_energy'],energy)
        np.testing.assert_array_equal(viewed['bounded_saturation'],bounded_project(q,energy))
        for field in ('weights','waveform_selected'):
            np.testing.assert_array_equal(viewed[field],analysis['_colors'][1][field])
        np.testing.assert_array_equal(viewed['vectorscope']['density'],scope_color.vectorscope(
            engine.from_native(native),viewed['weights'],nodes.grading_space(node))['density'])
        self.assertTrue(np.isfinite(analysis['stage2_appearance'].ja).all())

    def test_rgbe_half_full_transport_has_no_output_repair(self):
        bpy.ops.wm.set_working_color_space(working_space='ACEScg')
        scene,_=render_scene();scene.render.compositor_precision='FULL'
        tree=bpy.data.node_groups.new('Transport boundary','CompositorNodeTree')
        tree.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
        node=tree.nodes.new('CompositorNodeGroup');node.node_tree=lut.make_kernel('CompositorNodeTree','FORWARD')
        spaces = _component('graph.spaces')
        spaces.uniforms(node,np.eye(3),np.eye(3))
        # Exercise the final-bank sampler directly, outside publication.
        lut.resources.select_payload(node,2)
        source=tree.nodes.new('CompositorNodeImage')
        probe=bpy.data.images.new('Boundary input',width=8,height=8,float_buffer=True,alpha=True)
        probe.colorspace_settings.name='Non-Color';probe.alpha_mode='PREMUL';source.image=probe
        fraction=1-2**-14
        rgb=np.tile([cubes.axis()[1]*fraction,0.,0.,.4],(64,1)).astype('f4')
        probe.pixels.foreach_set(rgb.ravel());probe.update()
        output=tree.nodes.new('NodeGroupOutput');output.is_active_output=True
        tree.links.new(source.outputs['Image'],node.inputs['Color']);tree.links.new(node.outputs['Color'],output.inputs['Image'])
        scene.compositing_node_group=tree
        atlas=bpy.data.images.new('Boundary coefficients',width=cubes.ATLAS_WIDTH,
                                  height=cubes.atlas_height(65,4),float_buffer=True,alpha=True)
        atlas.colorspace_settings.name='Non-Color';atlas.alpha_mode='CHANNEL_PACKED';atlas.use_half_precision=False
        for texture in node.node_tree.nodes:
            if texture.get('_pg_cube_image'):texture.image=atlas
        self.assertEqual(sum(n.bl_idname=='CompositorNodeMapUV'for n in node.node_tree.nodes),16)
        with tempfile.TemporaryDirectory() as directory:
            for lower,upper in ((.001,0.),(1023.75,1024.)):
                values=np.broadcast_to([lower,100.,100.],(65,65,65,3)).copy().astype('f4')
                values[1,0,0,0]=upper
                cube=cubes.Cube(values,'transport');packed=cube.packed_pixels()
                for half in (False,True):
                    stored=packed.astype('f2').astype('f4')if half else packed
                    atlas.pixels.foreach_set(stored.ravel());atlas.update();atlas.update_tag()
                    fields=stored.reshape(-1,4);count=65**3
                    expected=cubes.unpack_rgbe(fields[0])+fraction*cubes.unpack_rgbe(fields[count])
                    for device in ('CPU','GPU'):
                        scene.render.compositor_device=device
                        actual=render(Path(directory)/f'{lower}-{half}-{device}.exr')
                        np.testing.assert_allclose(actual[...,:3],np.broadcast_to(expected,(8,8,3)),rtol=0,atol=3e-5)
                        np.testing.assert_allclose(actual[...,3],.4,rtol=0,atol=1e-7)
                        if half:
                            if lower<1:self.assertLess(actual[0,0,0],0.)
                            else:self.assertGreater(actual[0,0,0],1024.)

    def test_actual_gpu_image_sampler_preserves_signed_values(self):
        image=bpy.data.images.new('Sampler probes',width=8,height=8,float_buffer=True,alpha=True)
        image.colorspace_settings.name='Non-Color';image.alpha_mode='CHANNEL_PACKED'
        rng=np.random.default_rng(17);expected=rng.uniform(-.2,3,(8,8,4)).astype('f4')
        image.pixels.foreach_set(expected.ravel());image.update()
        proxy=SimpleNamespace(app=SimpleNamespace(background=False),data=bpy.data,context=bpy.context)
        with patch.object(sampling,'bpy',proxy):actual=sampling.sample_image(image,'Linear Rec.709',(8,8))
        # Blender image textures may use half storage; the readback target is float32.
        np.testing.assert_allclose(actual,expected,rtol=5e-4,atol=3e-8)

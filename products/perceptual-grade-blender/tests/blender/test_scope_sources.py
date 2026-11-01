"""Automatic source routes through real Blender graphs and product Sessions."""
from contextlib import contextmanager
from types import SimpleNamespace
import sys
import tempfile
import struct
import zlib
from pathlib import Path
import unittest

import bpy
import numpy as np

from color_tools.perceptual_grade_core.model import scope_analysis, transforms
from color_tools.perceptual_grade_blender.integration.components import Component
from tests.support.blender import BlenderTest, grade_data
from tests.support.session import component, patch


nodes = component('graph.nodes')
grades = component('graph.grades')
bake = component('graph.bake')
lut = component('graph.lut')
spaces = component('graph.spaces')
sources = component('scopes.sources')
images = component('scopes.images')
sampling = component('scopes.sampling')
capture = component('scopes.capture')
contexts = component('scopes.context')
reference = component('scopes.reference')


def png_fixture(path,color,width=2,height=1):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    pixels=bytes(color)
    if len(pixels)==4:pixels*=width*height
    rows=b''.join(b'\0'+pixels[row*width*4:(row+1)*width*4] for row in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))


class ScopeSourceTests(BlenderTest):
    def test_adopted_upstream_output_uses_actual_native_graph_without_certification(self):
        tree = self.tree()
        source = self.image(tree)
        upstream, target = nodes.create_grade(tree), nodes.create_grade(tree)
        self.connect(tree, source, upstream)
        self.connect(tree, upstream, target)
        lut.adopt_native(upstream, nodes.output_intent(upstream))
        with patch.object(lut, 'validate_output', side_effect=AssertionError('Restored output certified')), \
                patch.object(lut, 'request', side_effect=AssertionError('Restored output regenerated')), \
                patch.object(lut, 'scope_signal', side_effect=AssertionError('Invented numerical provenance')):
            route = sources.resolve(target)
            self.assertEqual(route.kind, 'native')
            self.assertEqual(route.steps, ())
            dependencies = {}
            sampling.native_dependencies(target, 'Color', dependencies)
            self.assertNotIn(upstream.as_pointer(), dependencies)
        self.assertTrue(lut.is_adopted(upstream))

    def tree(self, kind='CompositorNodeTree'):
        if kind == 'ShaderNodeTree':
            material = bpy.data.materials.new('Automatic material')
            material.use_nodes = True
            return material.node_tree
        tree = bpy.data.node_groups.new('Automatic compositor', kind)
        bpy.context.scene.compositing_node_group = tree
        return tree

    def image(self, tree, color=(.2, .4, .6, 1.), *, float_buffer=True):
        image = bpy.data.images.new('Source pixels', 2, 1, float_buffer=float_buffer)
        image.pixels[:] = color * 2
        source = tree.nodes.new('ShaderNodeTexImage' if tree.bl_idname == 'ShaderNodeTree'
                                else 'CompositorNodeImage')
        source.image = image
        return source

    def connect(self, tree, source, target, target_socket='Color', source_socket=None):
        output = source.outputs.get(source_socket) if source_socket else (
            source.outputs.get('Color') or source.outputs.get('Image'))
        tree.links.new(output, target.inputs[target_socket])

    @contextmanager
    def automatic_only(self):
        """Observe immutable component exports without replacing production code."""
        forbidden = {getattr(target, name).__code__: name for target, name in (
            (capture, 'describe'), (capture, 'acquire'), (capture, 'sample'),
            (contexts, 'describe'), (sampling, 'native_dependencies'))}
        called = []
        previous = sys.getprofile()

        def observe(frame, event, arg):
            if event == 'call' and frame.f_code in forbidden:
                called.append(forbidden[frame.f_code])
            if (event=='call' and frame.f_code.co_name=='_native_ready' and
                    frame.f_globals.get('__name__','').endswith('.scopes.sampling')):
                called.append('_native_ready')
            if previous is not None:
                previous(frame, event, arg)

        sys.setprofile(observe)
        try:
            yield
        finally:
            sys.setprofile(previous)
            self.assertEqual(called, [], 'Automatic input called native capture')

    def snapshot(self, node, context=None, *, linear=False):
        space = nodes.grading_space(node)
        sampling.probe_sources(node,space,capture_context=context)
        spec = sampling.describe_linear(node, space, context) if linear else (
            sampling.describe(node, space, capture_context=context))
        try:
            snapshot = sampling.capture_linear(spec, {}) if linear else sampling.capture(spec)
            return spec, snapshot
        finally:
            sampling.release(spec)

    def group(self, tree):
        child = bpy.data.node_groups.new('Shared automatic group', tree.bl_idname)
        for direction in ('INPUT', 'OUTPUT'):
            child.interface.new_socket(name='Color', in_out=direction,
                                       socket_type='NodeSocketColor')
        incoming = child.nodes.new('NodeGroupInput')
        outgoing = child.nodes.new('NodeGroupOutput')
        grade = nodes.create_grade(child)
        self.connect(child, incoming, grade)
        self.connect(child, grade, outgoing)
        kind = 'ShaderNodeGroup' if tree.bl_idname == 'ShaderNodeTree' else 'CompositorNodeGroup'
        first = tree.nodes.new(kind); first.node_tree = child
        second = tree.nodes.new(kind); second.node_tree = child
        return child, grade, first, second

    def editor(self, root, *children):
        return SimpleNamespace(scene=bpy.context.scene, window=None, area=None, region=None,
            space_data=SimpleNamespace(type='NODE_EDITOR', node_tree=root,
                path=tuple(SimpleNamespace(node_tree=tree) for tree in (root, *children))))

    def test_scene_material_and_compositor_images_use_only_source_reads(self):
        for kind in ('ShaderNodeTree', 'CompositorNodeTree'):
            with self.subTest(kind=kind):
                tree = self.tree(kind)
                source = self.image(tree, (-.25, 2., 4., 1.))
                node = nodes.create_grade(tree)
                self.connect(tree, source, node)
                self.assertIsNone(bpy.context.scene.camera)
                before = (len(bpy.data.scenes), len(bpy.data.images), len(bpy.data.node_groups))
                with self.automatic_only():
                    _, full = self.snapshot(node)
                    _, linear = self.snapshot(node, linear=True)
                np.testing.assert_array_equal(full['rgba'], [[(-.25, 2., 4., 1.)] * 2])
                np.testing.assert_array_equal(linear['source']['rgba'], full['rgba'])
                self.assertFalse(full['rgba'].flags.writeable)
                self.assertEqual(full['chain'], ())
                self.assertEqual(full['_scope_provenance'], ())
                self.assertEqual(before, (len(bpy.data.scenes), len(bpy.data.images), len(bpy.data.node_groups)))

    def test_automatic_source_rewire_changes_snapshot_without_capture(self):
        tree = self.tree()
        first = self.image(tree, (.25, 0., 0., 1.))
        second = self.image(tree, (0., .5, 0., 1.))
        node = nodes.create_grade(tree)
        self.connect(tree, first, node)
        with self.automatic_only():
            old_spec, old = self.snapshot(node)
            self.connect(tree, second, node)
            new_spec, new = self.snapshot(node)
        self.assertNotEqual(old_spec['key'], new_spec['key'])
        self.assertEqual(old['rgba'][0, 0, 0], .25)
        self.assertEqual(new['rgba'][0, 0, 1], .5)
        self.assertFalse(sampling.scope_input_status(node)['native'])

    def test_reroute_muted_node_and_compositor_transform_are_transparent(self):
        tree = self.tree()
        source = self.image(tree)
        reroute = tree.nodes.new('NodeReroute')
        muted = tree.nodes.new('CompositorNodeExposure'); muted.mute = True
        muted.inputs['Exposure'].default_value = 10.
        transform = tree.nodes.new('CompositorNodeTransform')
        transform.inputs['X'].default_value = 300.
        transform.inputs['Scale'].default_value = 2.
        node = nodes.create_grade(tree)
        tree.links.new(source.outputs['Image'], reroute.inputs[0])
        tree.links.new(reroute.outputs[0], muted.inputs['Image'])
        tree.links.new(muted.outputs['Image'], transform.inputs['Image'])
        self.connect(tree, transform, node)
        with self.automatic_only():
            route = sources.resolve(node)
            _, snapshot = self.snapshot(node)
        self.assertEqual(route.kind, 'image')
        self.assertEqual(route.source.name, source.image.name)
        self.assertEqual(route.steps, ())
        np.testing.assert_allclose(snapshot['rgba'], [[(.2, .4, .6, 1.)] * 2])

    def test_shared_group_occurrences_keep_repeated_model_applications(self):
        tree = self.tree()
        source = self.image(tree, (.125, .25, .375, 1.))
        _, grade, first, second = self.group(tree)
        nodes.write_values(grade, {'exposure': .5})
        node = nodes.create_grade(tree)
        self.connect(tree, source, first)
        self.connect(tree, first, second)
        self.connect(tree, second, node)
        with self.automatic_only(), patch.object(lut, 'scope_signal',
                side_effect=AssertionError('An analytical Grade requested a final LUT')):
            route = sources.resolve(node)
            _, snapshot = self.snapshot(node)
        self.assertEqual(route.source.name, source.image.name)
        self.assertEqual([kind for kind, _ in route.steps], ['grade', 'grade'])
        self.assertEqual(len({entry[2] for entry in route.structure}), 2)
        self.assertEqual(len(snapshot['chain']), 2)
        incoming = snapshot['rgba'][..., :3]
        before, after = spaces.adapters(nodes.working_space())
        model = transforms.Grade(nodes.settings(grade))
        once = model.apply(incoming @ before.T) @ after.T
        expected = model.apply(once @ before.T) @ after.T
        actual = scope_analysis.apply_chain(incoming, snapshot['chain'], nodes.working_space())
        np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)
        self.assertGreater(np.max(np.abs(actual - once)), .01)

    def test_shared_grade_data_keeps_each_distinct_node_application(self):
        tree = self.tree()
        source = self.image(tree)
        first, second, node = (nodes.create_grade(tree) for _ in range(3))
        shared = grade_data()
        for current in (first, second):
            with grades.guarded(current):
                current.pg_grade = shared
            grades.sync_node(current)
        nodes.write_values(first, {'exposure': .5})
        self.connect(tree, source, first)
        self.connect(tree, first, second)
        self.connect(tree, second, node)
        with self.automatic_only():
            route = sources.resolve(node)
            _, snapshot = self.snapshot(node)
        self.assertEqual(len(route.steps), 2)
        self.assertEqual(len(snapshot['chain']), 2)
        self.assertNotEqual(route.steps[0][1], route.steps[1][1])
        self.assertEqual(snapshot['chain'][0][1].settings, snapshot['chain'][1][1].settings)

    def test_selected_editor_occurrence_climbs_exact_group_input(self):
        tree = self.tree('ShaderNodeTree')
        child, grade, first, second = self.group(tree)
        red = self.image(tree, (.5, 0., 0., 1.))
        green = self.image(tree, (0., .5, 0., 1.))
        self.connect(tree, red, first)
        self.connect(tree, green, second)
        context = self.editor(tree, child)
        with self.automatic_only():
            tree.nodes.active = first
            first_spec, first_snapshot = self.snapshot(grade, context)
            tree.nodes.active = second
            second_spec, second_snapshot = self.snapshot(grade, context)
        self.assertNotEqual(first_spec['_scope_channel'], second_spec['_scope_channel'])
        self.assertEqual(first_spec['_capture_context']['group_path'], (first.name,))
        self.assertEqual(second_spec['_capture_context']['group_path'], (second.name,))
        np.testing.assert_allclose(first_snapshot['rgba'][0, 0], (.5, 0., 0., 1.))
        np.testing.assert_allclose(second_snapshot['rgba'][0, 0], (0., .5, 0., 1.))

    def test_two_editors_share_numeric_identity_for_same_source(self):
        tree = self.tree()
        source = self.image(tree)
        node = nodes.create_grade(tree)
        self.connect(tree, source, node)
        first, second = self.editor(tree), self.editor(tree)
        first.area = SimpleNamespace(as_pointer=lambda: 101)
        second.area = SimpleNamespace(as_pointer=lambda: 102)
        with self.automatic_only():
            # Establish the decoded Image revision before comparing consumers.
            self.snapshot(node, first)
            a, _ = self.snapshot(node, first)
            b, _ = self.snapshot(node, second)
        self.assertNotEqual(a['_scope_channel'], b['_scope_channel'])
        self.assertEqual(a['key'], b['key'])
        self.assertEqual(a['scope_source'], b['scope_source'])

    def test_nested_editor_path_preserves_each_selected_parent_instance(self):
        tree = self.tree()
        outer, _, first, second = self.group(tree)
        inner, grade, inner_first, inner_second = self.group(outer)
        incoming = next(node for node in outer.nodes if node.bl_idname == 'NodeGroupInput')
        self.connect(outer, incoming, inner_first)
        self.connect(outer, inner_first, inner_second)
        red = self.image(tree, (.5, 0., 0., 1.))
        green = self.image(tree, (0., .5, 0., 1.))
        self.connect(tree, red, first)
        self.connect(tree, green, second)
        tree.nodes.active = second
        outer.nodes.active = inner_second
        with self.automatic_only():
            spec, snapshot = self.snapshot(grade, self.editor(tree, outer, inner))
        self.assertEqual(spec['_capture_context']['group_path'], (second.name, inner_second.name))
        self.assertEqual(len(snapshot['chain']), 1)
        np.testing.assert_allclose(snapshot['rgba'][0, 0], (0., .5, 0., 1.))

    def test_baked_color_reads_bound_image_without_reapplying_grade(self):
        tree = self.tree()
        upstream, node = nodes.create_grade(tree), nodes.create_grade(tree)
        image_node = self.image(tree, (.25, .5, 1., 1.))
        nodes.write_values(upstream, {'exposure': 4.})
        image_node.image['_pg_bake_schema']=2
        image_node.image['_pg_bake_storage']='FLOAT_RGBA'
        image_node.image['_pg_bake_kind']='COMPOSITOR'
        image_node.image['_pg_bake_width'],image_node.image['_pg_bake_height']=tuple(image_node.image.size)
        image_node.image.pack()
        bake.set_baked_image(upstream, image_node.image)
        self.connect(tree, upstream, node, source_socket='Baked Color')
        with self.automatic_only(), patch.object(lut, 'scope_signal',
                side_effect=AssertionError('Baked Color requested its live model')):
            route = sources.resolve(node)
            _, snapshot = self.snapshot(node)
        self.assertEqual(route.kind, 'image')
        self.assertEqual(route.steps, ())
        self.assertEqual(snapshot['chain'], ())
        np.testing.assert_array_equal(snapshot['rgba'], [[(.25, .5, 1., 1.)] * 2])

    def test_native_source_queries_wait_for_automatic_coherent_pair(self):
        for kind in ('ShaderNodeTree','CompositorNodeTree'):
            tree=self.tree(kind);source=self.image(tree)
            native=tree.nodes.new('ShaderNodeTexNoise' if kind=='ShaderNodeTree' else 'CompositorNodeExposure')
            node=nodes.create_grade(tree);self.connect(tree,native,node)
            with self.automatic_only():
                with self.assertRaisesRegex(lut.ScopePreparing,'automatic scope inputs'):self.snapshot(node)
                self.connect(tree,source,node);self.connect(tree,native,node,reference.SOCKET)
                with self.assertRaisesRegex(lut.ScopePreparing,'automatic scope inputs'):self.snapshot(node)
                with self.assertRaisesRegex(lut.ScopePreparing,'automatic scope inputs'):self.snapshot(node,linear=True)
            self.assertTrue(sampling.scope_input_status(node)['native'])

    def test_frozen_animated_source_keeps_its_frame_after_scene_advances(self):
        tree=self.tree();node=nodes.create_grade(tree)
        with tempfile.TemporaryDirectory(prefix='pg-frozen-frame-') as directory:
            root=Path(directory)
            png_fixture(root/'frame0001.png',(255,0,0,255))
            png_fixture(root/'frame0002.png',(0,255,0,255))
            image=bpy.data.images.load(str(root/'frame0001.png'));image.source='SEQUENCE'
            source=tree.nodes.new('CompositorNodeImage');source.image=image;source.frame_duration=2
            self.connect(tree,source,node)
            bpy.context.scene.frame_set(1)
            with self.automatic_only():
                sampling.probe_sources(node,nodes.grading_space(node))
                spec=sampling.describe(node,nodes.grading_space(node))
                linear=sampling.describe_linear(node,nodes.grading_space(node))
                try:
                    self.assertEqual(spec['_scope_frames'],(1,))
                    bpy.context.scene.frame_set(2)
                    snapshot=sampling.capture(spec)
                    linear_snapshot=sampling.capture_linear(linear,{})
                    np.testing.assert_allclose(snapshot['rgba'][0,0],(1,0,0,1),atol=4e-5)
                    np.testing.assert_allclose(linear_snapshot['source']['rgba'][0,0],(1,0,0,1),atol=4e-5)
                finally:sampling.release(spec);sampling.release(linear)

    def test_source_resolution_preserves_initialized_resident_multiview_buffers(self):
        tree=self.tree('ShaderNodeTree');node=nodes.create_grade(tree)
        source=tree.nodes.new('ShaderNodeTexImage');self.connect(tree,source,node)
        scene=bpy.data.scenes.new('Private view settings')
        scene.render.use_multiview=True;scene.render.views_format='MULTIVIEW'
        settings=scene.render.image_settings
        settings.file_format='OPEN_EXR';settings.color_depth='32';settings.exr_codec='ZIPS'
        settings.views_format='INDIVIDUAL';settings.color_management='OVERRIDE'
        settings.linear_colorspace_settings.name='scene_linear'
        try:
            with tempfile.TemporaryDirectory(prefix='pg-resident-eyes-') as directory:
                root=Path(directory);path=root/'stereo.png'
                png_fixture(path,((255,0,0,255)*2+(0,255,0,255)*2)*2,width=4,height=2)
                image=bpy.data.images.load(str(path));source.image=image
                image.use_multiview=True;image.views_format='STEREO_3D'
                image.stereo_3d_format.display_mode='SIDEBYSIDE'
                with bpy.context.temp_override(area=None,region=None,scene=scene,
                        image_user=source.image_user,texture=None,camera=None):
                    bpy.ops.image.open('EXEC_DEFAULT',False,filepath=str(path),use_multiview=True,
                        use_sequence_detection=False,use_udim_detecting=False,relative_path=False)
                def export(name):
                    output=root/(name+'.exr');right=root/(name+'_R.exr')
                    try:image.save_render(str(output),scene=scene)
                    except RuntimeError:
                        if not right.is_file():raise
                    return right
                export('warm')
                path.unlink()
                before=(image.filepath,image.source,image.is_dirty,image.session_uid)
                with self.automatic_only():
                    route=sources.resolve(node)
                self.assertEqual(route.kind,'image')
                # The getter bug evicts the only remaining pixels, making this
                # second source-only export fail after the file is removed.
                exported=export('resident')
                exr=component('scopes.exr')
                np.testing.assert_allclose(exr.sample(str(exported),'',pass_name='')[0,0],(0,1,0,1))
                self.assertEqual(before,(image.filepath,image.source,image.is_dirty,image.session_uid))
        finally:bpy.data.scenes.remove(scene)

    def test_native_pair_retains_coherent_grid_until_automatic_replacement_completes(self):
        from color_tools.perceptual_grade_core.scopes.samples import sample_rgba, tiled_layout
        from color_tools.perceptual_grade_blender.jobs.handlers.native_capture import _sample_layout
        tree=self.tree();node=nodes.create_grade(tree)
        source=tree.nodes.new('CompositorNodeImage')
        native=tree.nodes.new('CompositorNodeExposure')
        native.inputs[0].default_value=(.1,.2,.3,1.)
        self.connect(tree,source,node);self.connect(tree,native,node,reference.SOCKET)
        context=contexts.source_context(node,SimpleNamespace(scene=bpy.context.scene,
            view_layer=bpy.context.scene.view_layers[0],object=None,space_data=None,
            window=None,area=None,region=None))
        with tempfile.TemporaryDirectory(prefix='pg-reference-grid-') as directory:
            root=Path(directory)
            for tile,color in ((1001,(255,0,0,255)),(1002,(0,255,0,255)),(1003,(0,0,255,255))):
                png_fixture(root/f'tile.{tile}.png',color)
            image=bpy.data.images.load(str(root/'tile.1001.png'));image.source='TILED'
            image.filepath=str(root/'tile.<UDIM>.png');image.tiles.new(1002);source.image=image
            for tile in tuple(image.tiles):
                if tile.number not in (1001,1002):image.tiles.remove(tile)
            native_pixels=np.array([[(.1,0,0,1),(.2,0,0,1),(.3,0,0,1),(.4,0,0,1)]],np.float32)
            specs=[];pending=[]
            def submit(spec):
                state=dict(done=False);specs.append(spec);pending.append(state)
                if '_image_source' in spec.inputs:
                    tile_ids=spec.inputs['_image_source']['tile_numbers']
                    layout=tiled_layout(tuple((tile,2,1) for tile in tile_ids))
                    rgba=np.zeros((*layout.mass.shape,4),np.float32)
                    for tile,color in ((1001,(1,0,0,1)),(1002,(0,1,0,1)),(1003,(0,0,1,1))):
                        rgba[layout.tiles==tile]=color
                else:
                    layout=_sample_layout(spec.inputs['sample_grid'])
                    rgba=sample_rgba(native_pixels,layout)
                grid={key:getattr(layout,key) for key in ('mass','x','uv','tiles','ids','key')}
                def result():
                    return dict(identity=spec.inputs['identity'],rgba=rgba,layout=grid,
                                label='frozen fixture',prepared_provenance=())
                return SimpleNamespace(retired=lambda:state['done'],cancel=lambda:state.update(done=True),result=result)
            runtime=SimpleNamespace(session=SimpleNamespace(path=root),closed=False,fenced=False,
                helpers={},poll=lambda **kwargs:None,submit=submit)
            scheduler=component('graph.scheduler');automatic=component('scopes.automatic')
            with patch.dict(self.session.components,services=Component({'get_runtime':lambda:runtime,'current_runtime':lambda:runtime})), \
                    patch.object(scheduler,'wake',new=lambda *args,**kwargs:None):
                try:
                    self.assertTrue(automatic.observe(node,context),capture.status(node))
                    self.assertEqual(len(specs),1)
                    self.assertIn('_image_source',specs[0].inputs)
                    with self.assertRaises(lut.ScopePreparing):self.snapshot(node,context)
                    pending[0]['done']=True;capture.poll()
                    self.assertEqual(len(specs),2)
                    self.assertEqual(specs[1].inputs['socket_name'],reference.SOCKET)
                    with self.assertRaises(lut.ScopePreparing):self.snapshot(node,context)
                    pending[1]['done']=True;capture.poll()
                    before,snapshot=self.snapshot(node,context)
                    self.assertTrue(before['comparison'])
                    np.testing.assert_allclose(snapshot['comparison'][0][...,0],[[.2,.4,.2,.4]])
                    np.testing.assert_array_equal(snapshot['rgba'][0,-1],(0,1,0,1))
                    previous_shape=snapshot['rgba'].shape
                    image.tiles.remove(next(tile for tile in image.tiles if tile.number==1002));image.tiles.new(1003)
                    self.assertTrue(automatic.observe(node,context))
                    retained_spec,retained=self.snapshot(node,context)
                    self.assertTrue(retained_spec['comparison'])
                    np.testing.assert_array_equal(retained['rgba'],snapshot['rgba'])
                    np.testing.assert_array_equal(retained['comparison'][0],snapshot['comparison'][0])
                    self.assertEqual(sampling.scope_input_status(node,context)['state'],'updating')
                    self.assertEqual(len(specs),3)
                    pending[2]['done']=True;capture.poll()
                    self.assertEqual(len(specs),4)
                    _,still_retained=self.snapshot(node,context)
                    np.testing.assert_array_equal(still_retained['rgba'],snapshot['rgba'])
                    self.assertNotEqual(specs[1].inputs['sample_grid']['key'],specs[3].inputs['sample_grid']['key'])
                    pending[3]['done']=True;capture.poll()
                    after,changed=self.snapshot(node,context)
                    self.assertTrue(after['comparison'])
                    self.assertEqual(changed['rgba'].shape,previous_shape)
                    np.testing.assert_array_equal(changed['rgba'][0,-1],(0,0,1,1))
                    self.assertEqual(sampling.scope_input_status(node,context)['state'],'ready')
                finally:
                    for item in pending:item['done']=True
                    automatic.clear();capture.clear();capture.collect_retired()

    def test_shader_alpha_link_selects_straight_or_premultiplied_rgb(self):
        tree = self.tree('ShaderNodeTree')
        for float_buffer in (False, True):
            with self.subTest(float_buffer=float_buffer):
                source = self.image(tree, (.8, .4, .2, .5), float_buffer=float_buffer)
                source.image.alpha_mode = 'STRAIGHT'
                node = nodes.create_grade(tree)
                self.connect(tree, source, node)
                with self.automatic_only():
                    premul = sources.resolve(node)
                    _, before = self.snapshot(node)
                    self.connect(tree, source, node, 'Alpha', 'Alpha')
                    straight = sources.resolve(node)
                    _, after = self.snapshot(node)
                self.assertTrue(premul.source.premultiply)
                self.assertFalse(straight.source.premultiply)
                np.testing.assert_allclose(before['rgba'][..., :3],
                    after['rgba'][..., :3] * after['rgba'][..., 3, None], rtol=3e-5, atol=1e-6)
                np.testing.assert_array_equal(before['rgba'][..., 3], after['rgba'][..., 3])

    def test_alpha_output_is_source_scalar_with_opaque_coverage(self):
        tree = self.tree('ShaderNodeTree')
        source = self.image(tree, (.2, .4, .6, .5))
        node = nodes.create_grade(tree)
        self.connect(tree, source, node, source_socket='Alpha')
        with self.automatic_only():
            _, snapshot = self.snapshot(node)
        np.testing.assert_array_equal(snapshot['rgba'], [[(.5, .5, .5, 1.)] * 2])

    def test_iterative_walk_exceeds_python_recursion_depth_and_rejects_cycle(self):
        tree = self.tree()
        source = self.image(tree)
        node = nodes.create_grade(tree)
        output = source.outputs['Image']
        # Bound the native fixture's link-update cost while still proving that
        # resolution does not consume Python stack space per graph edge.
        for _ in range(256):
            reroute = tree.nodes.new('NodeReroute')
            tree.links.new(output, reroute.inputs[0])
            output = reroute.outputs[0]
        tree.links.new(output, node.inputs['Color'])
        previous_limit = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(200)
            with self.automatic_only():
                self.assertEqual(sources.resolve(node).source.name, source.image.name)
        finally:
            sys.setrecursionlimit(previous_limit)
        # A separate small cycle avoids Blender's own reroute-type propagation
        # across the deep fixture when constructing an invalid native graph.
        first, second = (tree.nodes.new('NodeReroute') for _ in range(2))
        tree.links.new(first.outputs[0], second.inputs[0])
        tree.links.new(second.outputs[0], first.inputs[0])
        tree.links.new(second.outputs[0], node.inputs['Color'])
        with self.automatic_only(), self.assertRaisesRegex(ValueError, 'cycle'):
            sources.resolve(node)


if __name__ == '__main__':
    unittest.main()

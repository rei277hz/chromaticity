"""Installed native scope capture: real snapshots, no source checkout imports."""
import importlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import addon_utils
import bpy
import numpy as np


def main(repository, report_path):
    repository, report_path = Path(repository).resolve(), Path(report_path)
    package = repository / 'perceptual_grade'
    assert tuple(bpy.app.version) in {(5, 2, 4), (5, 3, 0)}, bpy.app.version
    native_binary = Path(bpy.app.binary_path).resolve()
    bpy.context.preferences.system.gpu_backend = 'METAL' if sys.platform == 'darwin' else 'OPENGL'
    bpy.context.preferences.extensions.repos.new(name='PG native scope acceptance',
        module='pg_scopes', custom_directory=str(repository))
    name = 'bl_ext.pg_scopes.perceptual_grade'
    errors = []
    addon = addon_utils.enable(name, default_set=False, handle_error=errors.append)
    assert addon is not None and not errors, repr(errors)
    lifecycle = importlib.import_module(name + '.perceptual_grade_blender.integration.lifecycle')
    assert Path(lifecycle.__file__).resolve().is_relative_to(package)
    application = lifecycle.registered_session()
    capture = application.component('scopes.capture')
    context_adapter = application.component('scopes.context')
    sampling = application.component('scopes.sampling')
    automatic_scopes=application.component('scopes.automatic')
    guard=application.component('graph.output_guard')
    nodes = application.component('graph.nodes')
    capture.enable_diagnostics(True)
    preparing = application.component('graph.lut').ScopePreparing
    runtime = application.app.execution.get_runtime()
    output_directory = report_path.parent / 'file-output-must-not-run'
    report = dict(passed=False, blender=list(bpy.app.version), compositor={}, shader=[], viewport=[],
                  source_graphs_unchanged=True, no_file_output_writes=True)

    def graph_state():
        trees = list(bpy.data.node_groups)
        trees += [owner.node_tree for values in (bpy.data.materials, bpy.data.worlds)
                  for owner in values if owner.node_tree is not None]
        return tuple((tree.name_full, tuple((node.name, node.bl_idname,
            getattr(getattr(node, 'node_tree', None), 'name_full', None),
            str(getattr(node, 'directory', ''))) for node in tree.nodes),
            tuple((link.from_node.name, link.from_socket.identifier,
                   link.to_node.name, link.to_socket.identifier) for link in tree.links))
            for tree in trees)

    def scene(name, width=32, height=16):
        # These scenes have never been active in a window. Snapshotting them
        # exercises dependency-graph synchronization before native serialization.
        value = bpy.data.scenes.new(name)
        value.render.engine = 'BLENDER_EEVEE'
        value.render.resolution_x = width
        value.render.resolution_y = height
        value.render.resolution_percentage = 100
        value.render.compositor_device = 'CPU'
        value.render.film_transparent = False
        value.cycles.samples = 4
        value.cycles.device = 'CPU'
        value.render.image_settings.file_format = 'PNG'
        value.render.filepath = str(output_directory / 'original-render')
        return value

    def plain_context(value):
        return SimpleNamespace(scene=value, view_layer=value.view_layers[-1], object=None,
            space_data=None, window=None, area=None, region=None)

    def sample(target, value, *, socket='Color', context=None, size=None, exact_size=False):
        before = graph_state()
        active_scene = bpy.context.window.scene
        render_settings = (value.render.filepath, value.render.image_settings.file_format,
                           value.render.resolution_percentage, value.camera)
        selected=context or plain_context(value)
        occurrence=context_adapter.source_context(target,selected)
        route=sampling.source_route(target,socket,occurrence)
        submitted=sum(item['event']=='request_created' for item in capture.diagnostics())
        if route.kind!='native':
            rgba,_chain,identity,label=sampling.source_samples(target,nodes.working_space(),socket,size,
                force=True,native_context=occurrence)
            assert sum(item['event']=='request_created' for item in capture.diagnostics())==submitted
            descriptor=dict(identity=identity)
        else:
            # Passive source reads cannot acquire. The foreground coordinator
            # observes the visible demand and starts its immutable source batch.
            capture.check_stale(target,occurrence,force=True)
            try:sampling.source_samples(target,nodes.working_space(),socket,size,native_context=occurrence)
            except (ValueError,preparing):pass
            assert sum(item['event']=='request_created' for item in capture.diagnostics())==submitted
            frozen=context_adapter.source_context(target,selected)
            guard.reconcile()
            automatic_scopes.observe(target,frozen)
            deadline=time.monotonic()+180
            while True:
                capture.poll()
                status=capture.status(target,frozen)
                if status['state']=='error':
                    rejected=next((item for item in reversed(capture.diagnostics()) if item['event']=='snapshot_rejected'),{})
                    raise ValueError(status['error']+' '+json.dumps(rejected))
                if status['state']=='captured' and automatic_scopes.status(target,frozen)=='ready':
                    descriptor=capture.accepted_descriptor(target,socket,frozen)
                    rgba,identity,label=capture.sample(target,socket,size,descriptor=descriptor,exact_size=exact_size)
                    break
                guard.reconcile()
                automatic_scopes.observe(target,frozen)
                assert time.monotonic()<deadline,('Native scope capture timed out',status)
                time.sleep(.01)
        assert identity == descriptor['identity'] and label
        assert not rgba.flags.writeable and np.isfinite(rgba).all()
        assert graph_state() == before, 'Capture changed live graph nodes or links'
        assert bpy.context.window.scene == active_scene, 'Capture changed the active scene'
        assert render_settings == (value.render.filepath, value.render.image_settings.file_format,
                                   value.render.resolution_percentage, value.camera)
        assert not output_directory.exists(), 'Capture ran a user File Output node'
        assert not tuple(runtime.session.path.glob('capture-*')), 'Retired capture retained its snapshot'
        return rgba

    def target(tree):
        """Use the shipped current interface, preserving its native output."""
        node=nodes.create_grade(tree)
        node.name='Selected Grade'
        application.component('graph.lut').adopt_native(node,nodes.output_intent(node))
        return node

    comp_scene = scene('Compositor capture')
    tree = bpy.data.node_groups.new('Native compositor', 'CompositorNodeTree')
    comp_scene.compositing_node_group = tree
    tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    final = tree.nodes.new('NodeGroupOutput')
    pixels = np.empty((16, 32, 4), dtype=np.float32)
    pixels[:] = (-.25, 2., .5, .375)
    pixels[4:12, 8:16] = (.75, .4, .1, .75)
    image = bpy.data.images.new('Signed HDR source', width=32, height=16, alpha=True, float_buffer=True)
    image.colorspace_settings.name = 'Non-Color'
    image.alpha_mode = 'CHANNEL_PACKED'
    image.pixels.foreach_set(pixels.ravel())
    image.update()
    source = tree.nodes.new('CompositorNodeImage')
    source.image = image
    transform = tree.nodes.new('CompositorNodeTransform')
    transform.inputs['X'].default_value = 4
    transform.inputs['Interpolation'].default_value = 'Nearest'
    tree.links.new(source.outputs['Image'], transform.inputs['Image'])
    grade = target(tree)
    tree.links.new(transform.outputs['Image'], grade.inputs['Color'])
    # Downstream output deliberately disagrees with the selected Grade input.
    other = tree.nodes.new('CompositorNodeRGB')
    other.outputs[0].default_value = (.9, .8, .7, 1.)
    tree.links.new(other.outputs[0], final.inputs['Image'])
    file_output = tree.nodes.new('CompositorNodeOutputFile')
    file_output.directory = str(output_directory)
    file_output.file_output_items.new('RGBA', 'Forbidden')
    tree.links.new(source.outputs['Image'], file_output.inputs['Forbidden'])
    automatic = sample(grade, comp_scene)
    np.testing.assert_allclose(automatic,pixels,rtol=0,atol=2e-6)
    assert not capture.states, 'Simple Transform admitted native capture'
    report['automatic_transform']=True
    neutral=tree.nodes.new('ShaderNodeMixRGB');neutral.blend_type='MIX'
    neutral.inputs[0].default_value=0.
    tree.links.new(transform.outputs['Image'],neutral.inputs[1])
    tree.links.new(neutral.outputs['Color'],grade.inputs['Color'])
    actual=sample(grade,comp_scene)
    expected = np.zeros_like(pixels)
    expected[:, 4:] = pixels[:, :-4]
    np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-6)
    report['compositor']['transform'] = dict(minimum=float(actual[..., 0].min()),
        maximum=float(actual[..., 1].max()), alpha=float(actual[0, 5, 3]))

    comp_scene.render.resolution_x, comp_scene.render.resolution_y = 16, 8
    domain_result = sample(grade, comp_scene, size=(64, 32))
    assert domain_result.shape == (16, 32, 4), domain_result.shape
    np.testing.assert_allclose(domain_result, expected, rtol=0, atol=2e-6)
    comp_scene.render.resolution_x, comp_scene.render.resolution_y = 32, 16
    report['compositor']['native_domain'] = dict(shape=list(domain_result.shape))

    mix = tree.nodes.new('ShaderNodeMixRGB')
    mix.blend_type = 'MIX'
    mix.inputs[0].default_value = .25
    mix.inputs[2].default_value = (.5, .25, .125, 1.)
    tree.links.new(transform.outputs['Image'], mix.inputs[1])
    tree.links.new(mix.outputs['Color'], grade.inputs['Color'])
    mixed = sample(grade, comp_scene)
    np.testing.assert_allclose(mixed[8, 20, :3], expected[8, 20, :3] * .75 +
        np.array((.5, .25, .125)) * .25, rtol=0, atol=2e-6)
    report['compositor']['mix'] = dict(pixel=mixed[8, 20].tolist())

    blur = tree.nodes.new('CompositorNodeBlur')
    blur.inputs['Size'].default_value = (3., 3.)
    tree.links.new(transform.outputs['Image'], blur.inputs['Image'])
    tree.links.new(blur.outputs['Image'], grade.inputs['Color'])
    blurred = sample(grade, comp_scene)
    assert np.any(np.abs(blurred - actual) > .001), 'Blur did not evaluate'
    assert 0 < blurred[8, 11, 3] < .75, blurred[8, 11].tolist()
    assert blurred[..., 0].min() < 0 and blurred[..., 1].max() > 1
    report['compositor']['blur'] = dict(edge=blurred[8, 11].tolist())

    child = bpy.data.node_groups.new('Shared compositor occurrence', 'CompositorNodeTree')
    child.interface.new_socket(name='Color', in_out='INPUT', socket_type='NodeSocketColor')
    child.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
    entry, result = child.nodes.new('NodeGroupInput'), child.nodes.new('NodeGroupOutput')
    nested_grade = target(child)
    child.links.new(entry.outputs['Color'], nested_grade.inputs['Color'])
    child.links.new(nested_grade.outputs['Color'], result.inputs['Color'])
    first = tree.nodes.new('CompositorNodeGroup'); first.node_tree = child
    second = tree.nodes.new('CompositorNodeGroup'); second.node_tree = child
    tree.links.new(neutral.outputs['Color'], first.inputs['Color'])
    tree.links.new(other.outputs['Color'], second.inputs['Color'])
    tree.links.new(second.outputs['Color'], final.inputs['Image'])
    tree.nodes.active = first
    nested_context = plain_context(comp_scene)
    nested_context.space_data = SimpleNamespace(type='NODE_EDITOR', id=comp_scene, node_tree=tree,
        path=(SimpleNamespace(node_tree=tree), SimpleNamespace(node_tree=child)))
    nested = sample(nested_grade, comp_scene, context=nested_context)
    np.testing.assert_allclose(nested, expected, rtol=0, atol=2e-6)
    report['compositor']['nested'] = dict(selected=first.name, other=second.name)

    encoded = bpy.data.images.new('Byte sRGB alpha source', width=32, height=16,
                                  alpha=True, float_buffer=False)
    encoded.colorspace_settings.name = 'sRGB'
    encoded.alpha_mode = 'STRAIGHT'
    encoded_pixels = np.full((16, 32, 4), (.5, .25, .8, .5), dtype=np.float32)
    encoded.pixels.foreach_set(encoded_pixels.ravel()); encoded.update()
    encoded.pixels.foreach_get(encoded_pixels.ravel())
    source.image = encoded
    tree.links.new(source.outputs['Image'], grade.inputs['Color'])
    color_managed = sample(grade, comp_scene)
    rgb = encoded_pixels[0, 0, :3]
    linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    expected_encoded = np.concatenate((linear * encoded_pixels[0, 0, 3],
                                       encoded_pixels[0, 0, 3:]))
    np.testing.assert_allclose(color_managed[8, 16], expected_encoded, rtol=0, atol=2e-5)
    report['compositor']['byte_srgb_alpha'] = dict(pixel=color_managed[8, 16].tolist())

    assert grade.inputs.get('Color Reference') is not None
    reference = bpy.data.images.new('Portrait reference', width=16, height=32,
                                   alpha=True, float_buffer=True)
    reference.colorspace_settings.name = 'Non-Color'
    reference.alpha_mode = 'CHANNEL_PACKED'
    reference_pixels = np.full((32, 16, 4), (.15, .6, 1.5, .8), dtype=np.float32)
    reference.pixels.foreach_set(reference_pixels.ravel()); reference.update()
    reference_node = tree.nodes.new('CompositorNodeImage'); reference_node.image = reference
    tree.links.new(reference_node.outputs['Image'], grade.inputs['Color Reference'])
    reference_capture = sample(grade, comp_scene, socket='Color Reference', size=(32, 16), exact_size=True)
    assert reference_capture.shape == color_managed.shape, reference_capture.shape
    np.testing.assert_allclose(reference_capture[8, 16], (.15, .6, 1.5, .8), rtol=0, atol=2e-6)
    report['compositor']['reference_grid'] = dict(primary=list(color_managed.shape),
        reference=list(reference_capture.shape))

    # On the first acquisition neither member has a cached sample size. The
    # portrait reference must wait for the landscape primary and adopt with it.
    paired=target(tree)
    assert paired.inputs.get('Color Reference') is not None
    pair_primary=tree.nodes.new('ShaderNodeMixRGB');pair_primary.inputs[0].default_value=0.
    pair_reference=tree.nodes.new('ShaderNodeMixRGB');pair_reference.inputs[0].default_value=0.
    tree.links.new(source.outputs['Image'],pair_primary.inputs[1])
    tree.links.new(reference_node.outputs['Image'],pair_reference.inputs[1])
    tree.links.new(pair_primary.outputs[0],paired.inputs['Color'])
    tree.links.new(pair_reference.outputs[0],paired.inputs['Color Reference'])
    paired_rgba=sample(paired,comp_scene)
    paired_context=context_adapter.source_context(paired,plain_context(comp_scene))
    paired_ref=capture.accepted_descriptor(paired,'Color Reference',paired_context)
    reference_rgba,_,_=capture.sample(paired,'Color Reference',descriptor=paired_ref)
    assert reference_rgba.shape==paired_rgba.shape==(16,32,4)
    np.testing.assert_allclose(reference_rgba[8,16],reference_pixels[0,0],rtol=0,atol=2e-6)
    report['compositor']['first_native_pair']=dict(primary=list(paired_rgba.shape),reference=list(reference_rgba.shape))

    native_adjustments={}
    for kind in ('CompositorNodeHueSat','CompositorNodeCurveRGB','CompositorNodeColorBalance'):
        adjustment=tree.nodes.new(kind)
        tree.links.new(source.outputs['Image'],adjustment.inputs['Image'])
        tree.links.new(adjustment.outputs['Image'],grade.inputs['Color'])
        initial=sample(grade,comp_scene)
        if kind=='CompositorNodeHueSat':adjustment.inputs['Value'].default_value=.5
        elif kind=='CompositorNodeCurveRGB':
            adjustment.mapping.curves[3].points[-1].location=(1.,.5)
            adjustment.mapping.update()
        else:adjustment.inputs['Gain'].default_value=.5
        occurrence=context_adapter.source_context(grade,plain_context(comp_scene))
        assert capture.check_stale(grade,occurrence,force=True)
        descriptor=capture.accepted_descriptor(grade,context=occurrence)
        retained,_,_=capture.sample(grade,descriptor=descriptor)
        np.testing.assert_array_equal(retained,initial)
        submitted=sum(item['event']=='request_created' for item in capture.diagnostics())
        capture.poll()
        assert sum(item['event']=='request_created' for item in capture.diagnostics())==submitted
        updated=sample(grade,comp_scene)
        assert np.max(np.abs(updated-initial))>.01,kind+' did not evaluate its changed input'
        native_adjustments[kind]=dict(before=initial[8,16].tolist(),after=updated[8,16].tolist())
    report['compositor']['native_adjustments']=native_adjustments

    # Automatic acquisition freezes the upstream model into a private helper
    # graph. A pending live final cube is preserved throughout capture.
    upstream=nodes.create_grade(tree)
    nodes.write_chromatic(upstream,{'global_gain':.173})
    tree.links.new(source.outputs['Image'],upstream.inputs['Color'])
    pending_mix=tree.nodes.new('ShaderNodeMixRGB');pending_mix.inputs[0].default_value=0.
    tree.links.new(upstream.outputs['Color'],pending_mix.inputs[1])
    tree.links.new(pending_mix.outputs['Color'],grade.inputs['Color'])
    lut=application.component('graph.lut')
    try:lut.validate_output(upstream,nodes.bake_model(upstream),final=True)
    except (ValueError,RuntimeError):pass
    else:raise AssertionError('Pending final-cube fixture was already ready')
    requests=sum(item['event']=='request_created' for item in capture.diagnostics())
    upstream_before=lut._graph_snapshot(upstream)
    prepared=sample(grade,comp_scene)
    assert sum(item['event']=='request_created' for item in capture.diagnostics())==requests+2
    assert lut._graph_snapshot(upstream)==upstream_before,'Capture rewrote the live pending PG graph'
    assert prepared.shape==color_managed.shape
    report['compositor']['pending_upstream_private_capture']=True

    shader_scene = scene('Shader capture', 64, 32)
    for obj in tuple(shader_scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    shader_scene.view_layers.new('Selected scope layer')
    camera = bpy.data.objects.new('Scope camera', bpy.data.cameras.new('Scope camera'))
    shader_scene.collection.objects.link(camera)
    camera.location = (0, 0, 3)
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = 4
    shader_scene.camera = camera
    material = bpy.data.materials.new('Shared visible material')
    material.use_nodes = True
    shader = material.node_tree
    shader.nodes.clear()
    material_grade = target(shader)
    material_signal = shader.nodes.new('ShaderNodeMixRGB')
    material_signal.blend_type = 'SUBTRACT'
    material_signal.inputs[0].default_value = 1
    material_signal.inputs[1].default_value = (.8, 3., 1.3, 1.)
    material_signal.inputs[2].default_value = (1., 1., 1., 1.)
    shader.links.new(material_signal.outputs['Color'], material_grade.inputs['Color'])
    emission = shader.nodes.new('ShaderNodeEmission')
    shader.links.new(material_grade.outputs['Color'], emission.inputs['Color'])
    surface = shader.nodes.new('ShaderNodeOutputMaterial')
    shader.links.new(emission.outputs[0], surface.inputs['Surface'])
    for index, (left, right) in enumerate(((-1.8, -.2), (.2, 1.8))):
        mesh = bpy.data.meshes.new('Visible user mesh ' + str(index))
        mesh.from_pydata([(left, -.75, 0), (right, -.75, 0),
                          (right, .75, 0), (left, .75, 0)], [], [(0, 1, 2, 3)])
        mesh.update()
        obj = bpy.data.objects.new('Visible user ' + str(index), mesh)
        shader_scene.collection.objects.link(obj)
        mesh.materials.append(material)
    world = bpy.data.worlds.new('Scope World')
    world.use_nodes = True
    shader_scene.world = world
    world_tree = world.node_tree
    world_grade = target(world_tree)
    world_signal = world_tree.nodes.new('ShaderNodeMixRGB')
    world_signal.blend_type = 'SUBTRACT'
    world_signal.inputs[0].default_value = 1
    world_signal.inputs[1].default_value = (.7, 2.5, 1.4, 1.)
    world_signal.inputs[2].default_value = (1., 1., 1., 1.)
    world_tree.links.new(world_signal.outputs['Color'], world_grade.inputs['Color'])
    world_tree.links.new(world_grade.outputs['Color'], world_tree.nodes['Background'].inputs['Color'])
    for engine in ('BLENDER_EEVEE', 'CYCLES'):
        shader_scene.render.engine = engine
        rgba = sample(material_grade, shader_scene)
        for x in (16, 48):
            np.testing.assert_allclose(rgba[16, x, :3], (-.2, 2., .3), rtol=0, atol=.003)
            assert rgba[16, x, 3] > .99, rgba[16, x].tolist()
        assert rgba[0, 0, 3] < .01, rgba[0, 0].tolist()
        report['shader'].append(dict(engine=engine, owner='material',
            left=rgba[16, 16].tolist(), right=rgba[16, 48].tolist()))
        rgba = sample(world_grade, shader_scene)
        np.testing.assert_allclose(rgba[0, 0, :3], (-.3, 1.5, .4), rtol=0, atol=.003)
        assert rgba[0, 0, 3] > .99, rgba[0, 0].tolist()
        assert rgba[16, 16, 3] < .01, rgba[16, 16].tolist()
        report['shader'].append(dict(engine=engine, owner='world', background=rgba[0, 0].tolist()))

    # A viewport's orthographic clip interval can extend behind its origin.
    # Generated planes exercise that interval through the installed helper,
    # including planes beyond each boundary that must remain invisible.
    ortho = np.diag((.25, .75, -.5, 1.))
    asymmetric = ortho.copy(); asymmetric[2, 3] = .5
    perspective = np.zeros((4, 4))
    perspective[0, 0], perspective[1, 1] = 1., 3.
    perspective[2, 2], perspective[2, 3], perspective[3, 2] = -1000.01 / 999.99, -20. / 999.99, -1.
    for label, projection, depths in (
        ('orthographic', ortho, (.5, -.5, 2.2, -2.2)),
        ('asymmetric_orthographic', asymmetric, (.5, -.5, 3.2, -1.2)),
        ('perspective', perspective, (-2., -2., -.005, -1001.)),
    ):
        viewport_scene = scene('Viewport ' + label, 96, 32)
        viewport_scene.camera = camera
        for index, z in enumerate(depths):
            # Keep each plane in a separate screen column in either projection.
            distance = -z if label == 'perspective' else 1.
            x = (-.75 + .5 * index) * distance / projection[0, 0]
            half_width = .15 * distance / projection[0, 0]
            half_height = .5 * distance / projection[1, 1]
            mesh = bpy.data.meshes.new(label + ' plane ' + str(index))
            mesh.from_pydata([(x - half_width, -half_height, z),
                (x + half_width, -half_height, z), (x + half_width, half_height, z),
                (x - half_width, half_height, z)], [], [(0, 1, 2, 3)])
            mesh.update()
            obj = bpy.data.objects.new(mesh.name, mesh)
            viewport_scene.collection.objects.link(obj)
            mesh.materials.append(material)
        for engine in ('BLENDER_EEVEE', 'CYCLES'):
            viewport_scene.render.engine = engine
            frozen = context_adapter.describe(material_grade, context=plain_context(viewport_scene))
            frozen['view'] = dict(frozen['view'], source='viewport', width=96, height=32,
                view_matrix=tuple(map(tuple, np.eye(4))),
                projection_matrix=tuple(map(tuple, projection)),
                clip_start=.01, clip_end=1000., perspective='PERSP' if label == 'perspective' else 'ORTHO',
                visible_objects=tuple(obj.name for obj in viewport_scene.objects))
            rgba = sample(material_grade, viewport_scene, context=frozen)
            for x in (12, 36):
                np.testing.assert_allclose(rgba[16, x, :3], (-.2, 2., .3), rtol=0, atol=.003)
                assert rgba[16, x, 3] > .99, (label, engine, rgba[16, x].tolist())
            for x in (60, 84):
                assert rgba[16, x, 3] < .01, (label, engine, 'clip boundary', rgba[16, x].tolist())
            report['viewport'].append(dict(projection=label, engine=engine,
                positive_or_first=rgba[16, 12].tolist(), negative_or_second=rgba[16, 36].tolist(),
                clipped_near=rgba[16, 60].tolist(), clipped_far=rgba[16, 84].tolist()))

    # A Render Layers source chooses its own layer. It must still render that
    # layer when the editor context points to another one, even if use is off.
    shader_scene.render.engine = 'BLENDER_EEVEE'
    material_signal.inputs[1].default_value = (1.7, 1.2, 1.1, 1.)
    render_tree = bpy.data.node_groups.new('Render Layers compositor', 'CompositorNodeTree')
    shader_scene.compositing_node_group = render_tree
    render_tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    render_source = render_tree.nodes.new('CompositorNodeRLayers')
    other_layer = shader_scene.view_layers[-1]
    render_source.scene = shader_scene
    other_layer.use = False
    render_source.layer = other_layer.name
    render_grade = target(render_tree)
    render_tree.links.new(render_source.outputs['Image'], render_grade.inputs['Color'])
    render_output = render_tree.nodes.new('NodeGroupOutput')
    render_tree.links.new(render_grade.outputs['Color'], render_output.inputs['Image'])
    render_context = plain_context(shader_scene)
    render_context.view_layer = shader_scene.view_layers[0]
    rendered = sample(render_grade, shader_scene, context=render_context)
    np.testing.assert_allclose(rendered[16, 16], (.7, .2, .1, 1.), rtol=0, atol=.003)
    assert not other_layer.use, 'Capture changed the live render-layer enable state'
    report['compositor']['render_layers'] = dict(layer=other_layer.name,
        editor_layer=render_context.view_layer.name, pixel=rendered[16, 16].tolist())

    external_source = tree.nodes.new('CompositorNodeRLayers')
    external_source.scene = shader_scene
    external_source.layer = other_layer.name
    tree.links.new(external_source.outputs['Image'], grade.inputs['Color'])
    externally_rendered = sample(grade, comp_scene, size=(64, 32))
    # Native Render Layers uses the owning compositor scene's canvas even when
    # its scene input references a scene with a different render resolution.
    assert externally_rendered.shape == (16, 32, 4), externally_rendered.shape
    np.testing.assert_allclose(externally_rendered[8, 8], (.7, .2, .1, 1.), rtol=0, atol=.003)
    assert not other_layer.use, 'External capture changed the live layer enable state'
    report['compositor']['external_render_layers'] = dict(scene=shader_scene.name,
        layer=other_layer.name, shape=list(externally_rendered.shape),
        pixel=externally_rendered[8, 8].tolist())

    visible_users = [obj for obj in shader_scene.objects if obj.type == 'MESH']
    for obj in visible_users:
        obj.hide_render = True
    try:
        sample(material_grade, shader_scene)
    except ValueError as error:
        assert 'no visible samples' in str(error), str(error)
        report['invisible_material_error'] = str(error)
    else:
        raise AssertionError('Invisible material should report an explicit capture error')
    finally:
        for obj in visible_users:
            obj.hide_render = False
    assert not tuple(runtime.session.path.glob('capture-*')), 'Failed capture retained its snapshot'

    helper = runtime.helpers['capture']
    assert Path(helper.process.args[0]).resolve() == native_binary
    assert helper.process.pid != os.getpid()
    report['helper_is_native'] = True
    report['snapshot_leases_released'] = not tuple(runtime.session.path.glob('capture-*'))
    process = helper.process
    addon.unregister()
    report['helper_exited'] = process.poll() is not None
    report['passed'] = True
    report_path.write_text(json.dumps(report, indent=2), encoding='utf8')
    print('PG_NATIVE_SCOPE_CAPTURE', json.dumps(report), flush=True)


if __name__ == '__main__':
    main(*sys.argv[sys.argv.index('--') + 1:])

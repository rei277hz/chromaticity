"""Real Blender fixtures and a small unencoded EXR render/readback helper."""
import unittest
import time
import bpy
import numpy as np
from color_tools import perceptual_grade_blender as addon
from color_tools.perceptual_grade_blender.integration import lifecycle


from .session import SessionTest, component, patch


grades, stacks = component('graph.grades'), component('graph.stacks')


class BlenderTest(SessionTest):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        addon.register()
        self.session = lifecycle.registered_session()
        self.assertIsNotNone(self.session)

    def tearDown(self):
        addon.unregister()
        bpy.ops.wm.read_factory_settings(use_empty=True)


def grade_data():
    data = bpy.data.node_groups.new('Test grade', grades.PGGradeData.bl_idname)
    data[grades.TAG] = grades.SCHEMA
    grades.assign_values(data, grades.defaults())
    return data


def sequence(tree, entries):
    node = stacks.create(tree)
    with grades.guarded(node):
        for grade in entries:
            item = node.pg_stack_entries.add()
            item.grade = grade
            item.key = str(len(node.pg_stack_entries))
    stacks.bind_dependencies(node)
    stacks.refresh(node, True)
    return node


def wait_for_scopes(node,view=(),timeout=30):
    """Pump bake/scope adapters until a coherent installed signal is analyzed."""
    nodes, lut = component('graph.nodes'), component('graph.lut')
    sampling, jobs = component('scopes.sampling'), component('scopes.jobs')
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        lut.tick()
        result=sampling.get(node,nodes.grading_space(node),view)
        jobs.tick()
        state=jobs._states[node.as_pointer()]
        if (result is not None and result['_scope_key']==state['spec']['key']
                and state['completed']==state['spec']['key']
                and not result.get('_active_statistics_pending')):return result
        if state['failed']==state['spec']['key']:raise AssertionError('Scope analysis failed')
        time.sleep(.001)
    raise AssertionError('Scope analysis did not finish')


def render_scene():
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    scene.render.resolution_x = scene.render.resolution_y = 8
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'OPEN_EXR'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '32'
    scene.render.image_settings.color_management = 'OVERRIDE'
    scene.render.image_settings.linear_colorspace_settings.name = 'scene_linear'
    camera = bpy.data.objects.new('Test camera', bpy.data.cameras.new('Test camera'))
    scene.collection.objects.link(camera)
    scene.camera = camera
    world = bpy.data.worlds.new('Test world')
    world.use_nodes = True
    scene.world = world
    return scene, world


def render(path):
    output = component('graph.output')
    output.guarded_render()
    bpy.data.images['Render Result'].save_render(str(path), scene=bpy.context.scene)
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.colorspace_settings.name = 'Non-Color'
        image.alpha_mode = 'PREMUL'
        return np.asarray(image.pixels[:]).reshape(image.size[1], image.size[0], 4)
    finally:
        bpy.data.images.remove(image)

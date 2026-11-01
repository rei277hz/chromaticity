"""Repeatable native evaluation timings; correctness assertions, no speed threshold."""
from tests.support.session import component as _component, SessionTest, patch
import json
import os
from pathlib import Path
import platform
import statistics
import tempfile
import time
pass

import bpy
import numpy as np

gpu = _component('graph.gpu'); lut = _component('graph.lut'); nodes = _component('graph.nodes'); output = _component('graph.output'); output_resources = _component('graph.output_resources')
from tests.support import reference as oracle
from tests.support.blender import BlenderTest, render, render_scene


SIZE = 256
WARM_RUNS = 3


class OutputEvaluationTests(BlenderTest):
    def setUp(self):
        super().setUp()
        cpu = patch.object(gpu, 'acquire', return_value=(None, None))
        cpu.start()
        self.addCleanup(cpu.stop)

    def fixture(self, kind):
        scene, world = render_scene()
        scene.render.resolution_x = scene.render.resolution_y = SIZE
        scene.render.threads_mode = 'FIXED'
        scene.render.threads = min(4, os.cpu_count() or 1)
        scene.render.use_persistent_data = True
        scene.render.compositor_device = 'CPU'
        if kind == 'shader':
            tree = world.node_tree
            grade = nodes.create_grade(tree)
            coordinates = tree.nodes.new('ShaderNodeTexCoord')
            normalize = tree.nodes.new('ShaderNodeVectorMath')
            normalize.operation = 'MULTIPLY_ADD'
            normalize.inputs[1].default_value = (.25, .25, .25)
            normalize.inputs[2].default_value = (.5, .5, .5)
            tree.links.new(coordinates.outputs['Normal'], normalize.inputs[0])
            tree.links.new(normalize.outputs['Vector'], grade.inputs['Color'])
            tree.links.new(grade.outputs['Color'], tree.nodes['Background'].inputs['Color'])
        else:
            tree = bpy.data.node_groups.new('Evaluation compositor', 'CompositorNodeTree')
            tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
            grade = nodes.create_grade(tree)
            y, x = np.mgrid[0:SIZE, 0:SIZE].astype(np.float32) / (SIZE - 1)
            rgb = np.stack((.1 + .4 * x, .1 + .4 * y, .1 + .2 * (x + y)), axis=-1)
            image = bpy.data.images.new('Evaluation gradient', width=SIZE, height=SIZE,
                                        float_buffer=True, alpha=True)
            image.colorspace_settings.name = 'Non-Color'
            image.alpha_mode = 'PREMUL'
            image.pixels.foreach_set(np.concatenate((rgb, np.full((SIZE, SIZE, 1), .4,
                                                                   np.float32)), axis=-1).ravel())
            image.update()
            source = tree.nodes.new('CompositorNodeImage')
            source.image = image
            target = tree.nodes.new('NodeGroupOutput')
            target.is_active_output = True
            tree.links.new(source.outputs['Image'], grade.inputs['Color'])
            tree.links.new(grade.outputs['Color'], target.inputs['Image'])
            scene.compositing_node_group = tree
        nodes.write_tone(grade, {'input_midtones': 42., 'input_white': 230.})
        nodes.write_chromatic(grade, {'global_gain': .1, 'web_hue_1_0': 8., 'web_chroma_1_1': .1})
        return scene, grade

    def measure(self, kind):
        started = time.perf_counter()
        scene, grade = self.fixture(kind)
        fixture_seconds = time.perf_counter() - started
        images = output_resources.bank_images(grade)
        links = tuple((slot, image.as_pointer()) for slot, image in sorted(images.items()))
        self.assertEqual(len(links), 4)
        native_render, prepare_render = output._native_render, output.prepare_render
        timings = {}

        def timed(name, function, *args, **kwargs):
            start = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                timings[name] = time.perf_counter() - start

        records, pixels = {}, {}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(output, '_native_render', side_effect=lambda *args, **kwargs:
                             timed('native', native_render, *args, **kwargs)), \
                patch.object(output, 'prepare_render', side_effect=lambda *args, **kwargs:
                             timed('prepare', prepare_render, *args, **kwargs)):
            for mode, muted in (('muted', True), ('four_banks', False)):
                grade.mute = muted
                cold, warm = {}, []
                for iteration in range(WARM_RUNS + 1):
                    timings.clear()
                    result = render(Path(directory) / (mode + '.exr'))
                    self.assertEqual(result.shape, (SIZE, SIZE, 4))
                    self.assertTrue(np.isfinite(result).all())
                    lut.validate_output(grade, nodes.bake_model(grade), final=True)
                    self.assertEqual(lut.installed_cube(grade).size, 65)
                    self.assertEqual(tuple((slot, image.as_pointer()) for slot, image
                                           in sorted(output_resources.bank_images(grade).items())), links)
                    if iteration == 0:
                        cold = dict(timings)
                        pixels[mode] = result
                    else:
                        np.testing.assert_array_equal(result, pixels[mode])
                        warm.append(dict(timings))
                records[mode] = dict(cold=cold, warm=warm,
                    warm_native_median_seconds=statistics.median(row['native'] for row in warm),
                    warm_prepare_median_seconds=statistics.median(row['prepare'] for row in warm))
        expected = nodes.bake_model(grade).apply(pixels['muted'][..., :3])
        self.assertLess(float(oracle.error(pixels['four_banks'][..., :3], expected).max()), .003)
        np.testing.assert_allclose(pixels['four_banks'][..., 3], pixels['muted'][..., 3],
                                   rtol=0, atol=1e-7)
        self.assertGreater(float(np.max(np.abs(pixels['four_banks'] - pixels['muted']))), .001)
        baseline = records['muted']['warm_native_median_seconds']
        active = records['four_banks']['warm_native_median_seconds']
        report = dict(kind=kind, size=[SIZE, SIZE], warm_runs=WARM_RUNS,
            version=list(bpy.app.version), build=bpy.app.build_hash.decode(),
            platform=platform.platform(), machine=platform.machine(),
            host_logical_cpus=os.cpu_count(), render_threads=scene.render.threads,
            shader_engine='CYCLES', shader_device='CPU', samples=1,
            compositor_device='CPU', persistent_data=True, fixture_seconds=fixture_seconds,
            modes=records, warm_native_difference_seconds=active-baseline,
            warm_native_ratio=active/baseline,
            measurement='Native render operator wall time; EXR save/readback excluded. '
                        'Exact-output preparation is reported separately. '
                        'First render of each mode includes compilation/cache setup. '
                        'CPU-only diagnostic; no hardware-GPU or viewport responsiveness claim.')
        print('PG_OUTPUT_EVALUATION', json.dumps(report, sort_keys=True), flush=True)

    def test_shader_warm_evaluation(self):
        self.measure('shader')

    def test_compositor_warm_evaluation(self):
        self.measure('compositor')

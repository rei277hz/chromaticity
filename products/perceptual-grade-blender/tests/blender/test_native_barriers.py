"""Native bpy operators: ignored handler exceptions and guarded outputs."""
from tests.support.session import component as _component, SessionTest, patch
from pathlib import Path
import tempfile
pass

import bpy

grades = _component('graph.grades'); lut = _component('graph.lut'); nodes = _component('graph.nodes'); output = _component('graph.output')
from tests.support.blender import BlenderTest, render_scene, sequence


class NativeBarrierTests(BlenderTest):
    def tearDown(self):
        output.clear()
        super().tearDown()

    def test_native_save_does_not_veto_handler_exception(self):
        def fail(*_):
            raise RuntimeError('Expected native save_pre veto probe')
        bpy.app.handlers.save_pre.append(fail)
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'native.blend'
                self.assertEqual(bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False), {'FINISHED'})
                self.assertTrue(path.exists())
        finally:
            bpy.app.handlers.save_pre.remove(fail)

    def test_native_render_does_not_veto_handler_exception(self):
        render_scene()
        completed = []
        def fail(*_):
            raise RuntimeError('Expected native render_pre veto probe')
        def complete(*_):
            completed.append(True)
        bpy.app.handlers.render_pre.append(fail)
        bpy.app.handlers.render_complete.append(complete)
        try:
            self.assertEqual(bpy.ops.render.render(), {'FINISHED'})
            self.assertEqual(completed, [True])
        finally:
            bpy.app.handlers.render_pre.remove(fail)
            bpy.app.handlers.render_complete.remove(complete)

    def test_guarded_save_reuses_prepared_native_handler_and_reopens(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'guarded.blend'
            real = nodes.save_handler
            with patch.object(nodes, 'save_handler', wraps=real) as prepare:
                self.assertEqual(output.guarded_save(str(path)), {'FINISHED'})
                # The registered callback retains its original function. The
                # wrapper calls the shared preparation once before native Save.
                self.assertEqual(prepare.call_count, 1)
            self.assertTrue(path.exists())
            bpy.ops.wm.open_mainfile(filepath=str(path))
            self.assertFalse(output.busy())

    def test_guarded_sequence_uses_native_filenames_zero_frame_and_skip(self):
        scene, _ = render_scene()
        scene.render.image_settings.file_format = 'PNG'
        scene.frame_start, scene.frame_end, scene.frame_step = 0, 2, 2
        scene.frame_set(9, subframe=.5)
        with tempfile.TemporaryDirectory() as directory:
            scene.render.filepath = str(Path(directory) / 'frame_####')
            path0, path2 = (Path(scene.render.frame_path(frame=frame)) for frame in (0, 2))
            self.assertEqual(output.guarded_render(scene, animation=True), {'FINISHED'})
            self.assertTrue(path0.exists() and path2.exists())
            self.assertEqual((scene.frame_current, scene.frame_subframe), (9, .5))
            before = (path0.stat().st_mtime_ns, path2.stat().st_mtime_ns)
            scene.render.use_overwrite = False
            self.assertEqual(output.guarded_render(scene, animation=True), {'FINISHED'})
            self.assertEqual((path0.stat().st_mtime_ns, path2.stat().st_mtime_ns), before)

    def test_guarded_render_failure_never_starts_native_render(self):
        render_scene()
        started = []
        def start(*_):
            started.append(True)
        bpy.app.handlers.render_init.append(start)
        try:
            with patch.object(output, 'prepare_render', side_effect=RuntimeError('Exact LUT failed')):
                with self.assertRaisesRegex(RuntimeError, 'Exact LUT failed'):
                    output.guarded_render()
            self.assertEqual(started, [])
        finally:
            bpy.app.handlers.render_init.remove(start)

    def test_invalid_inverse_stack_blocks_guarded_still_and_sequence(self):
        scene, world = render_scene()
        grade = nodes.create_grade(world.node_tree)
        nodes.write_values(grade, {'exposure': .1})
        stack = sequence(world.node_tree, [grade.pg_grade])
        stack.pg_stack_entries[0].direction = 'INVERSE'
        world.node_tree.links.new(stack.outputs['Color'], world.node_tree.nodes['Background'].inputs['Color'])
        lut.ensure(stack, nodes.bake_model(stack), force=True)
        previous_image = lut.image_for(stack)
        # A previously valid final output must not authorize rendering after
        # the inverse becomes undefined. Exercise real model validation.
        grades.write_matrix(grade.pg_grade, ((1., 0., 0.), (0., 0., 0.), (0., 0., 1.)))
        grades.publish(grade.pg_grade)
        self.assertIn('singular', stack['_pg_error'])
        scene.frame_start, scene.frame_end = 1, 2
        scene.frame_set(7, subframe=.25)
        started = []
        def start(*_):
            started.append(True)
        bpy.app.handlers.render_init.append(start)
        try:
            for animation in (False, True):
                with self.subTest(animation=animation):
                    with self.assertRaisesRegex(ValueError, 'singular'):
                        output.guarded_render(scene, animation=animation)
                    self.assertEqual(started, [])
                    self.assertIn('singular', stack['_pg_error'])
                    self.assertEqual(lut.image_for(stack), previous_image)
                    self.assertNotIn(stack.as_pointer(), lut._states)
                    self.assertFalse(output.busy() or nodes._rendering)
                    self.assertEqual((scene.frame_current, scene.frame_subframe), (7, .25))
        finally:
            bpy.app.handlers.render_init.remove(start)

    def test_guarded_sequence_captures_animated_grade_and_endpoint_rows(self):
        scene, world = render_scene()
        node = nodes.create_grade(world.node_tree)
        node.inputs['Color'].default_value = (.2, .3, .4, 1.)
        world.node_tree.links.new(node.outputs['Color'], world.node_tree.nodes['Background'].inputs['Color'])
        data = grades.ensure(node)
        for frame, exposure, gain in ((1, 0., .1), (2, 1., .2)):
            nodes.write_values(node, {'exposure': exposure})
            nodes.write_chromatic(node, {'global_gain': gain})
            data.keyframe_insert(data_path='["' + grades.MATRIX + '"]', frame=frame)
            data.keyframe_insert(data_path='pg_chromatic.global_gain', frame=frame)
        scene.frame_start, scene.frame_end = 1, 2
        scene.frame_set(7, subframe=.25)
        observed = []
        native = output._native_render
        def capture(scene, frame, **kwargs):
            manifest = lut.validate_output(node, nodes.bake_model(node), final=True)
            observed.append((frame, nodes.linear_matrix(node).copy(), nodes.read_chromatic(node).global_gain,
                             manifest['signature']))
            return native(scene, frame, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            scene.render.filepath = str(Path(directory) / 'animated_####')
            with patch.object(output, '_native_render', side_effect=capture):
                self.assertEqual(output.guarded_render(scene, animation=True), {'FINISHED'})
        self.assertEqual([item[0] for item in observed], [1, 2])
        self.assertAlmostEqual(observed[0][1][0, 0], 1.)
        self.assertAlmostEqual(observed[1][1][0, 0], 2.)
        self.assertAlmostEqual(observed[0][2], .1)
        self.assertAlmostEqual(observed[1][2], .2)
        self.assertNotEqual(observed[0][3], observed[1][3])
        self.assertEqual((scene.frame_current, scene.frame_subframe), (7, .25))

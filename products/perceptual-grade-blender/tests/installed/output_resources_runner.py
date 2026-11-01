"""Installed native GUI regression for permanent LUT links and undo.

Keep only scalar locators across timer turns: every undo replaces native IDs.
The critical cases publish asynchronously after a snapshot and immediately
undo without adding another snapshot after publication.
"""
import faulthandler
import importlib
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

import addon_utils
import bpy
import numpy as np


def main(repository, destination):
    repository, destination = Path(repository).resolve(), Path(destination)
    assert not bpy.app.background and tuple(bpy.app.version) == (5, 2, 2)
    faulthandler.enable(all_threads=True)
    bpy.context.preferences.view.show_splash = False
    bpy.context.preferences.edit.use_global_undo = True
    bpy.context.preferences.edit.undo_steps = 64
    bpy.context.preferences.extensions.repos.new(
        name='Output lifetime regression', module='pg_output', custom_directory=str(repository))
    package = 'bl_ext.pg_output.perceptual_grade'
    errors = []
    addon = addon_utils.enable(package, default_set=False, handle_error=errors.append)
    assert addon is not None and not errors, repr(errors)

    prefix = 'perceptual_grade_blender.'
    lifecycle = importlib.import_module(package + '.' + prefix + 'integration.lifecycle')
    registry = importlib.import_module(package + '.' + prefix + 'integration.registry')
    for value in (lifecycle, registry):
        assert Path(value.__file__).resolve().is_relative_to(repository / 'perceptual_grade')
    application = lifecycle.registered_session()
    assert application is not None

    def module(suffix):
        value = importlib.import_module(package + '.' + suffix)
        assert Path(value.__file__).resolve().is_relative_to(repository / 'perceptual_grade')
        component = suffix.removeprefix(prefix)
        if suffix.startswith(prefix) and component in registry.COMPONENTS:
            return application.component(component)
        return value

    nodes, lut = module('perceptual_grade_blender.graph.nodes'), module('perceptual_grade_blender.graph.lut')
    grades, stacks = module('perceptual_grade_blender.graph.grades'), module('perceptual_grade_blender.graph.stacks')
    resources, output = module('perceptual_grade_blender.graph.output_resources'), module('perceptual_grade_blender.graph.output')
    spaces = module('perceptual_grade_blender.graph.spaces')
    started = time.monotonic()
    report = dict(passed=False, cases=[], numeric_checks=0, preserved_checks=0, snapshot_checks=0, fixed_edge_checks=0,
                  native_undo=0, native_redo=0, events=[], build=bpy.app.build_hash.decode())
    command = ''
    base = (('material', 'PG output material', 'Grade'),
            ('material', 'PG output material', 'Stack'),
            ('group', 'PG output compositor', 'Grade'),
            ('group', 'PG output compositor', 'Stack'))
    duplicate = ('material', 'PG output material', 'Duplicate')
    initialized = ('group', 'PG output compositor', 'Initialized')
    copied = (('material', 'PG output copied material', 'Grade'),
              ('material', 'PG output copied material', 'Stack'))

    def record(event):
        report['events'].append(dict(event=event, seconds=round(time.monotonic() - started, 3)))
        destination.write_text(json.dumps(report, indent=2), encoding='utf8')
        print('PG_OUTPUT_EVENT', event, flush=True)

    @bpy.app.handlers.persistent
    def undone(_): report['native_undo'] += 1
    @bpy.app.handlers.persistent
    def redone(_): report['native_redo'] += 1
    bpy.app.handlers.undo_post.append(undone)
    bpy.app.handlers.redo_post.append(redone)

    def find(locator):
        kind, owner, name = locator
        tree = (bpy.data.materials[owner].node_tree if kind == 'material'
                else bpy.data.node_groups[owner])
        return tree.nodes[name]

    def editor():
        window = bpy.context.window_manager.windows[0]
        area = next(area for area in window.screen.areas if area.type == 'NODE_EDITOR')
        return window, area, next(region for region in area.regions if region.type == 'WINDOW')

    def edges(locator):
        node = find(locator)
        live_images = {item.as_pointer() for item in bpy.data.images}
        live_trees = {item.as_pointer() for item in bpy.data.node_groups}
        tree = node.node_tree
        assert tree.as_pointer() in live_trees
        image_edges, helper_edges = [], []
        for item in tree.nodes:
            if hasattr(item, 'image') and item.image is not None:
                pointer = item.image.as_pointer()
                assert pointer in live_images, (locator, item.name, 'Image is absent from Main')
                image_edges.append((item.name, pointer))
            if hasattr(item, 'node_tree') and item.node_tree is not None:
                pointer = item.node_tree.as_pointer()
                assert pointer in live_trees, (locator, item.name, 'Helper is absent from Main')
                helper_edges.append((item.name, pointer))
        if resources.is_current(node):
            assert len(resources.bank_images(node)) == 4
        report['fixed_edge_checks'] += 1
        return (tree.as_pointer(), tuple(sorted(image_edges)), tuple(sorted(helper_edges)),
                tuple(sorted((link.from_node.name, link.from_socket.identifier,
                              link.to_node.name, link.to_socket.identifier) for link in tree.links)))

    def fingerprint(locators=base):
        return tuple(edges(locator) for locator in locators)

    def ready(locators=base):
        if nodes.recovery_pending():return False
        for locator in locators:
            node = find(locator)
            if lut.is_adopted(node):continue
            image = lut.image_for(node)
            if (nodes.resource_action(node) or image is None or node.get(lut.INCOMPLETE)
                    or image.get('_pg_cube_size') != 65
                    or image.get('_pg_cube_signature') != lut.cm.signature(nodes.bake_model(node))):
                return False
        return True

    def validate(locators=base):
        for locator in locators:
            edges(locator)
            node = find(locator)
            shader = node.id_data.bl_idname == 'ShaderNodeTree'
            inputs = ['Color', 'Alpha'] if shader else ['Color']
            if nodes.is_grade(node):inputs.append('Color Reference')
            if shader:inputs.append('Vector')
            outputs = ['Color', 'Alpha', 'Baked Color', 'Baked Alpha'] if shader else ['Color', 'Baked Color']
            assert [socket.name for socket in node.inputs] == inputs
            assert [socket.name for socket in node.outputs] == outputs
            if lut.is_adopted(node):
                state = resources.record(node.node_tree,node)['state']
                assert not state.graph_valid and not any(slot.valid for slot in state.slots)
                assert nodes.recovery_status()['state'] == 'completed'
                report['preserved_checks'] += 1
                continue
            model = nodes.bake_model(node)
            lut.validate_output(node, model, final=True)
            image = lut.image_for(node)
            raw = np.empty(len(image.pixels), np.float32)
            image.pixels.foreach_get(raw)
            rgba = raw.reshape(-1, 4)[:65 ** 3]
            actual = (lut.cm.unpack_rgbe(rgba) if image.get('_pg_cube_encoding') == 'RGBE_DIFFERENCES'
                      else rgba[:, :3])
            indices = np.linspace(0, 65 ** 3 - 1, 19, dtype=int)
            expected = model.bake_native(lut.cm.lattice()[indices])
            # Software OpenGL and the CPU reference can differ by one small
            # scene-linear float32 step near zero; the observed maximum is 6.11e-5.
            np.testing.assert_allclose(actual[indices], expected, rtol=.002, atol=1e-4)
            report['numeric_checks'] += 1

    def native_snapshot(locators=base):
        """Test oracle only: compare actual restored data, never repair it."""
        result=[]
        for locator in locators:
            node=find(locator)
            banks=[]
            for index,image in resources.bank_images(node).items():
                pixels=np.empty(len(image.pixels),np.float32)
                image.pixels.foreach_get(pixels)
                banks.append((index,hashlib.sha256(memoryview(pixels).cast('B')).hexdigest(),
                    hashlib.sha256(image.packed_file.data).hexdigest() if image.packed_file else None))
            rows=spaces.read_rows(node)
            result.append((resources.selected_index(node),rows,tuple(banks)))
        return tuple(result)

    def assert_native_snapshot(expected):
        assert native_snapshot() == expected, 'Recovery changed or failed to restore authored native data'
        report['snapshot_checks'] += 1

    def setup():
        material = bpy.data.materials.new(base[0][1])
        material.use_nodes = True
        material.use_fake_user = True
        bpy.context.view_layer.objects.active.data.materials.clear()
        bpy.context.view_layer.objects.active.data.materials.append(material)
        compositor = bpy.data.node_groups.new(base[2][1], 'CompositorNodeTree')
        compositor.use_fake_user = True
        bpy.context.scene.compositing_node_group = compositor
        for tree in (material.node_tree, compositor):
            grade = nodes.create_grade(tree)
            grade.name = 'Grade'
            nodes.write_chromatic(grade, {'global_gain': .25})
            stack = stacks.create(tree)
            stack.name = 'Stack'
            with grades.guarded(stack):
                entry = stack.pg_stack_entries.add()
                entry.grade = grade.pg_grade
                entry.key = 'entry'
            stacks.bind_dependencies(stack)
            stacks.refresh(stack, True)
        window = bpy.context.window_manager.windows[0]
        area = max(window.screen.areas, key=lambda item: item.width * item.height)
        area.type = 'NODE_EDITOR'
        area.ui_type = 'ShaderNodeTree'
        area.spaces.active.shader_type = 'OBJECT'
        area.spaces.active.show_region_ui = False
        bpy.context.window_manager.pg_diagram_enabled = False

    def edit(value):
        for locator in (base[0], base[2]):
            nodes.write_chromatic(find(locator), {'global_gain': value})

    def values():
        return tuple(nodes.read_chromatic(find(locator)).global_gain for locator in (base[0], base[2]))

    def private(left, right):
        a, b = find(left), find(right)
        assert a.node_tree != b.node_tree
        assert not ({image.as_pointer() for image in resources.bank_images(a).values()} &
                    {image.as_pointer() for image in resources.bank_images(b).values()})

    class PG_OT_resource_scenario(bpy.types.Operator):
        bl_idname = 'pg_test.resource_scenario'
        bl_label = 'Output lifetime scenario'
        bl_options = {'UNDO'}

        def execute(self, context):
            try:
                if command == 'duplicate':
                    source = find(base[0])
                    for node in source.id_data.nodes:
                        node.select = node == source
                    source.id_data.nodes.active = source
                    assert bpy.ops.node.duplicate() == {'FINISHED'}
                    clone = source.id_data.nodes.active
                    assert clone != source
                    clone.name = duplicate[2]
                    grades.new(clone)
                    nodes.write_chromatic(clone, {'global_gain': .75})
                elif command == 'copy_tree':
                    material = bpy.data.materials[base[0][1]].copy()
                    material.name = copied[0][1]
                    material.use_fake_user = True
                    # Keep the whole-tree case to the original two owners.
                    extra = material.node_tree.nodes.get(duplicate[2])
                    if extra is not None:
                        grades.release_node_references(extra)
                        material.node_tree.nodes.remove(extra)
                elif command == 'independent':
                    for locator in copied:
                        node = find(locator)
                        with context.temp_override(pg_node=node):
                            assert bpy.ops.perceptual_grade.prepare_output() == {'FINISHED'}
                    grades.new(find(copied[0]))
                    nodes.write_chromatic(find(copied[0]), {'global_gain': -.25})
                elif command == 'delete':
                    node = find(duplicate)
                    grades.release_node_references(node)
                    node.id_data.nodes.remove(node)
                elif command == 'pending':
                    node = bpy.data.node_groups[initialized[1]].nodes.new(grades.KINDS['CompositorNodeTree'])
                    node.name = initialized[2]
                elif command == 'initialize':
                    node = find(initialized)
                    with context.temp_override(pg_node=node):
                        assert bpy.ops.perceptual_grade.prepare_output() == {'FINISHED'}
                    node.name = initialized[2]
                    nodes.write_chromatic(node, {'global_gain': .125})
                else:
                    raise AssertionError(command)
            except BaseException:
                report['operator_error'] = traceback.format_exc()
                record('operator_failed')
                raise
            return {'FINISHED'}

    bpy.utils.register_class(PG_OT_resource_scenario)

    def turns(count=5):
        for _ in range(count):
            yield

    def wait(predicate, label, timeout=120):
        end = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > end:
                raise TimeoutError(label)
            yield

    def key(kind, **modifiers):
        window, area, region = editor()
        x, y = region.x + region.width // 2, region.y + region.height // 2
        window.event_simulate(type=kind, value='PRESS', unicode=None, x=x, y=y, **modifiers)
        del window, area, region
        yield from turns()
        window, area, region = editor()
        window.event_simulate(type=kind, value='RELEASE', unicode=None, x=x, y=y, **modifiers)
        del window, area, region
        yield from turns()

    def action(value):
        nonlocal command
        command = value
        record(value + '_begin')
        yield from key('F6')
        assert 'operator_error' not in report, report.get('operator_error')
        record(value + '_complete')

    def push(label):
        window, area, region = editor()
        with bpy.context.temp_override(window=window, area=area, region=region):
            assert bpy.ops.ed.undo_push(message=label) == {'FINISHED'}

    def scenario():
        yield from wait(lambda: nodes.recovery_status()['state']=='completed' and not nodes.recovery_pending(), 'Initial runtime recovery')
        setup()
        yield from turns(12)
        keymap = bpy.context.window_manager.keyconfigs.addon.keymaps.new(name='Screen', space_type='EMPTY')
        keymap.keymap_items.new('ed.undo', 'Z', 'PRESS', ctrl=True)
        keymap.keymap_items.new('ed.redo', 'Z', 'PRESS', ctrl=True, shift=True)
        keymap.keymap_items.new('pg_test.resource_scenario', 'F6', 'PRESS')
        del keymap
        bpy.context.window_manager.keyconfigs.update()
        yield from wait(ready, 'Baseline publication')
        validate()
        baseline_native=native_snapshot()
        push('Fixed owners before publication')
        before = fingerprint()
        edit(.5)
        assert not ready(), 'Model change must queue new numerical output'
        changed_native=native_snapshot()
        push('Changed model before asynchronous publication')
        assert fingerprint() == before
        yield from wait(ready, 'Completed post-snapshot asynchronous publication')
        assert fingerprint() == before
        validate()
        # No undo push occurs between this completed publication and undo.
        record('post_snapshot_publication_complete')
        for iteration in range(3):
            yield from key('Z', ctrl=True)
            assert values() == (.25, .25), values()
            fingerprint()
            yield from wait(ready, 'Undo runtime reconciliation')
            assert_native_snapshot(baseline_native)
            validate()
            yield from key('Z', ctrl=True, shift=True)
            assert values() == (.5, .5), values()
            fingerprint()
            yield from wait(ready, 'Redo runtime reconciliation')
            assert_native_snapshot(changed_native)
            validate()
            report['cases'].append('async_undo_redo_' + str(iteration))
            record('async_undo_redo')

        yield from action('pending')
        assert find(initialized).node_tree is None
        yield from turns(30)
        assert find(initialized).node_tree is None
        yield from action('initialize')
        before = edges(initialized)
        yield from wait(lambda: ready((initialized,)), 'Explicit initialization publication')
        assert edges(initialized) == before
        validate((initialized,))
        yield from key('Z', ctrl=True)
        assert find(initialized).node_tree is None
        yield from key('Z', ctrl=True, shift=True)
        yield from wait(lambda: ready((initialized,)), 'Initialization redo')
        validate((initialized,))
        report['cases'].append('explicit_initialize_undo_redo')
        yield from action('duplicate')
        private(base[0], duplicate)
        yield from wait(lambda: ready(base + (duplicate,)), 'Private same-tree duplicate')
        validate(base + (duplicate,))
        assert nodes.read_chromatic(find(base[0])).global_gain == .5
        assert nodes.read_chromatic(find(duplicate)).global_gain == .75
        report['cases'].append('same_tree_divergence')
        yield from action('copy_tree')
        assert all(nodes.resource_action(find(locator)) == 'independent' for locator in base[:2] + copied)
        before = fingerprint(base + copied)
        yield from turns(30)
        assert fingerprint(base + copied) == before
        yield from action('independent')
        for left, right in zip(base[:2], copied):
            private(left, right)
        yield from wait(lambda: ready(base + copied + (duplicate,)), 'Whole-tree independence')
        validate(base + copied + (duplicate,))
        report['cases'].append('whole_tree_independence')
        yield from action('delete')
        assert duplicate[2] not in bpy.data.materials[duplicate[1]].node_tree.nodes
        yield from key('Z', ctrl=True)
        yield from wait(lambda: ready(base + copied + (duplicate,)), 'Deletion undo')
        validate(base + copied + (duplicate,))
        yield from key('Z', ctrl=True, shift=True)
        assert duplicate[2] not in bpy.data.materials[duplicate[1]].node_tree.nodes
        report['cases'].append('deletion_undo_redo')
        yield from wait(lambda: ready(base + copied), 'Post-deletion rebuild')
        path = destination.with_suffix('.blend')
        saved_wrappers = {locator: find(locator).bl_idname for locator in base + copied}
        assert output.guarded_save(str(path)) == {'FINISHED'}
        assert bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False, use_scripts=False) == {'FINISHED'}
        yield from turns(12)
        yield from wait(lambda: ready(base + copied), 'Reload rebuild')
        validate(base + copied)
        assert {locator: find(locator).bl_idname for locator in base + copied} == saved_wrappers
        report['cases'].append('portable_save_reload')
        report['covered'] = ['shader_grade', 'shader_stack', 'compositor_grade', 'compositor_stack']
        record('cases_complete')

    sequence = scenario()

    def advance():
        try:
            if time.monotonic() - started > 570:
                raise TimeoutError('Output lifetime test exceeded 9.5 minutes')
            if getattr(bpy.context.window_manager, 'is_event_handling_break', False):
                return .016
            next(sequence)
            return .016
        except StopIteration:
            try:
                addon.unregister()
                report['passed'] = True
                record('complete')
                bpy.ops.wm.quit_blender('EXEC_DEFAULT')
            except BaseException:
                report['error'] = traceback.format_exc()
                record('failed_teardown')
                os._exit(1)
            return None
        except BaseException:
            report['error'] = traceback.format_exc()
            record('failed')
            print(report['error'], flush=True)
            os._exit(1)

    record('started')
    bpy.app.timers.register(advance, first_interval=.5, persistent=True)


if __name__ == '__main__':
    main(*sys.argv[sys.argv.index('--') + 1:])

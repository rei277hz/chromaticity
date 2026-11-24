"""Drive a live Viewer: final renders silently promote AUTO to full precision.

After setup, only authoritative Grade settings and the requested backend change.
No render, image tag, node rebind, mute toggle, or manual reconciliation may make
an edit visible. A composite completion and changed Viewer pixels are required.
"""

import addon_utils
import importlib
import json
from pathlib import Path
import sys
import time
import traceback

import bpy
from bpy.app.handlers import persistent
import gpu
import numpy as np


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:-1])
phase = sys.argv[-1]
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade compositor test", module="pg_compositor",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_compositor.perceptual_grade")
nodes = importlib.import_module(extension.__name__ + ".nodes")
stage2_bindings = importlib.import_module(extension.__name__ + ".kernel.stage2_bindings")
parameter_layout = importlib.import_module(extension.__name__ + ".kernel.stage2_parameters")
errors = []
assert addon_utils.enable(
    extension.__name__, default_set=False, handle_error=errors.append
) is extension
assert not errors and not bpy.app.background, errors

_publish_grade_parameters = nodes._publish_grade_parameters


def trace_grade_publication(*args, **kwargs):
    try:
        result = _publish_grade_parameters(*args, **kwargs)
    except BaseException:
        traceback.print_exc()
        raise
    if result:
        print("GRADE BANK PUBLICATION ERRORS", [repr(error) for error in result], flush=True)
    return result


nodes._publish_grade_parameters = trace_grade_publication
_run_bank_publication = nodes.run_bank_publication


def trace_bank_publication(*args, **kwargs):
    result = _run_bank_publication(*args, **kwargs)
    if result.outcome != "committed":
        print("GRADE BANK PUBLICATION RESULT", result.outcome,
              [repr(error) for error in result.errors], flush=True)
    return result


nodes.run_bank_publication = trace_bank_publication

# A spatially varying image is essential: constant results use float32 even in
# AUTO and would conceal the half-precision intermediate overflow regression.
PALETTE = np.asarray([
    (0, 0, 0, 0), (1e-8, 1e-8, 1e-8, .1), (1e-6, 1e-6, 1e-6, .25),
    (.0001, .0001, .0001, .5), (.01, .01, .01, .37), (.18, .18, .18, .5),
    (1, 1, 1, .75), (16, 16, 16, 1), (64, 64, 64, .2), (256, 256, 256, .6),
    (900, 900, 900, .3), (918, 918, 918, .4), (920, 920, 920, .7),
    (922, 922, 922, .8), (1024, 1024, 1024, 1), (2048, 2048, 2048, .5),
    (-.01, -.01, -.01, .5), (-1, -1, -1, .75), (-.1, .2, .3, .25),
    (1, -.2, .1, .6), (-4, 2, .5, 1), (1, 0, 0, 0), (0, 1, 0, .33),
    (0, 0, 1, .66), (4, 0, 0, 1), (0, 16, 1, .4), (32, .1, 4, .8),
    (.01, .5, 1, .9), (1, 1, 0, .3), (.5, .5, 1, .7),
    (.125, .25, .5, 1), (-1e-8, 1e-8, 0, .5),
    (np.inf, .3, .4, .5), (.2, np.nan, .4, .75), (.2, .3, -np.inf, 1.),
], dtype=np.float32)
CONFIGS = ("reset", "exposure", "tone", "anchors", "color")
SCENE_TREE = "Interactive Grade Root"
NESTED_TREE = "Nested Grade Consumer"
MATERIAL = "Shared Shader Consumer"
GRADE = "Interactive Shared Grade"
BLEND = report_path.parent / "stale-kernel.blend"
rows = []
events = []
pending_frame = {}
result = {"passed": False, "rows": rows}
started = time.monotonic()


def consumers():
    return (
        bpy.data.node_groups[NESTED_TREE].nodes["Nested Grade"],
        bpy.data.node_groups[SCENE_TREE].nodes["Shared Grade"],
        bpy.data.materials[MATERIAL].node_tree.nodes["Shader Grade"],
    )


def grade_settings():
    return nodes._snapshot_values(nodes._grade_settings(
        bpy.data.node_groups[GRADE], nodes._working_space(),
    ))


def parameter_image(node):
    tree = node.node_tree
    banks = tuple(tree[key] for key in nodes.PARAMETER_BANK_BINDINGS)
    active = tree[nodes.PARAMETER_ACTIVE_BANK]
    selectors = [item for item in tree.nodes if item.get(nodes.PARAMETER_SELECTOR)]
    assert len(banks) == 2 and active in (0, 1)
    assert len(selectors) == 1
    selector = selectors[0]
    if tree.bl_idname == nodes.SHADER_TREE:
        selected = int(round(float(selector.outputs["Value"].default_value)))
    else:
        selected = int(round(float(selector.inputs[0].default_value)))
    assert selected == active
    readers = [item for item in tree.nodes if item.get(stage2_bindings.PARAMETER_READER)]
    observed = {(item.get(stage2_bindings.PARAMETER_READER_BANK),
                 item.get(stage2_bindings.PARAMETER_READER_ROLE)): item.image
                for item in readers}
    assert {(bank, role) for bank in (0, 1) for role in nodes.PARAMETER_ROLES} <= set(observed)
    assert all(observed[bank, role] == nodes.parameter_bank_images(banks[bank])[role]
               for bank, role in observed)
    assert all(nodes.parameter_bundle_receipt_matches(primary) for primary in banks)
    return banks[active]


def identity():
    users = consumers()
    parameters = [parameter_image(node) for node in users]
    assert all(image == parameters[0] for image in parameters), "Shared parameter image split"
    trees = (bpy.data.node_groups[SCENE_TREE], bpy.data.node_groups[NESTED_TREE],
             bpy.data.materials[MATERIAL].node_tree)
    return {
        "kernels": [node.node_tree.as_pointer() for node in users],
        "links": [[(link.from_socket.as_pointer(), link.to_socket.as_pointer())
                   for link in tree.links] for tree in trees],
        "node_counts": [len(node.node_tree.nodes) for node in users],
    }


def configure(name):
    grade = bpy.data.node_groups[GRADE]
    for field, value in nodes._LINEAR_DEFAULTS.items():
        setattr(grade.pg_linear, field, value)
    for field, value in nodes.TONE_DEFAULTS.items():
        setattr(grade.pg_tone, field, value)
    for field, value in nodes._COLOR_DEFAULTS.items():
        setattr(grade.pg_color, field, value)
    if name != "reset":
        grade.pg_linear.exposure = .5 if name == "exposure" else 1.
    if name == "tone":
        grade.pg_tone.fit = .5
    elif name == "anchors":
        for field, value in zip(nodes.TONE_LEVEL_FIELDS, (8., 40., 235., 1150.)):
            setattr(grade.pg_tone, field, value)
        grade.pg_tone.fit = 2.
    elif name == "color":
        grade.pg_tone.fit = .25
        grade.pg_tone.muted_gain = .0625
        grade.pg_tone.highlight_chroma = -.0625
        grade.pg_tone.vivid_gain = .03125
        grade.pg_color.adaptance_a_1 = .0625
        grade.pg_color.adaptance_b_2 = -.03125
        grade.pg_color.web_hue_1_0 = 12.
        grade.pg_color.web_chroma_1_2 = .0625
        grade.pg_color.web_scale_2_3 = .125


def setup():
    scene = bpy.context.scene
    scene.render.compositor_device = "GPU"
    scene.render.compositor_precision = "AUTO"
    scene.render.resolution_x = len(PALETTE)
    scene.render.resolution_y = 8
    scene.render.resolution_percentage = 100
    image = bpy.data.images.new("Compositor palette", width=len(PALETTE), height=8,
                                alpha=True, float_buffer=True)
    image.colorspace_settings.name = "Non-Color"
    image.alpha_mode = "CHANNEL_PACKED"
    image.use_half_precision = False
    image.pixels.foreach_set(np.tile(PALETTE, (8, 1)).ravel())
    image.update()
    image.pack()
    root = bpy.data.node_groups.new(SCENE_TREE, nodes.COMPOSITOR_TREE)
    root.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    output = root.nodes.new("NodeGroupOutput")
    source = root.nodes.new("CompositorNodeImage")
    source.image = image
    nested = bpy.data.node_groups.new(NESTED_TREE, nodes.COMPOSITOR_TREE)
    for direction in ("INPUT", "OUTPUT"):
        nested.interface.new_socket(name="Color", in_out=direction,
                                    socket_type="NodeSocketColor")
    incoming = nested.nodes.new("NodeGroupInput")
    outgoing = nested.nodes.new("NodeGroupOutput")
    grade = nodes._make_grade()
    grade.name = GRADE
    node = nodes.create_node(nested)
    node.name = "Nested Grade"
    node.pg_grade = grade
    nested.links.new(incoming.outputs["Color"], node.inputs["Color"])
    nested.links.new(node.outputs["Color"], outgoing.inputs["Color"])
    wrapper = root.nodes.new("CompositorNodeGroup")
    wrapper.node_tree = nested
    shared = nodes.create_node(root)
    shared.name = "Shared Grade"
    shared.pg_grade = grade
    root.links.new(source.outputs["Image"], shared.inputs["Color"])
    root.links.new(source.outputs["Image"], wrapper.inputs["Color"])
    viewer = root.nodes.new("CompositorNodeViewer")
    root.links.new(wrapper.outputs["Color"], viewer.inputs["Image"])
    root.links.new(wrapper.outputs["Color"], output.inputs["Image"])
    root.nodes.active = viewer
    material = bpy.data.materials.new(MATERIAL)
    material.use_nodes = True
    material.use_fake_user = True
    shader = nodes.create_node(material.node_tree)
    shader.name = "Shader Grade"
    shader.pg_grade = grade
    shader_source = material.node_tree.nodes.new("ShaderNodeRGB")
    material.node_tree.links.new(shader_source.outputs[0], shader.inputs["Color"])
    scene.compositing_node_group = root
    area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
    area.type = "NODE_EDITOR"
    area.ui_type = "CompositorNodeTree"
    area.spaces.active.show_backdrop = True


@persistent
def observe_started(*_args):
    global pending_frame
    try:
        states = [nodes._node_stores.get(node.as_pointer(), {}).get("state")
                  for node in consumers()]
        pending_frame = {
            "current": all(state is not None and nodes.node_policy.output_allowed(state)
                           for state in states),
            "settings": grade_settings(),
            "device": bpy.context.scene.render.compositor_device,
            "precision": bpy.context.scene.render.compositor_precision,
        }
    except (KeyError, ReferenceError):
        pending_frame = {"current": False}


@persistent
def observe(*_args):
    events.append(dict(pending_frame, finished=time.monotonic()))


@persistent
def observe_loaded_schema(*_args):
    result["loaded_schema"] = [node.node_tree.get(nodes._KERNEL_KIND) for node in consumers()]


bpy.app.handlers.composite_pre.append(observe_started)
bpy.app.handlers.composite_post.append(observe)
if phase == "exercise":
    setup()
    tasks = [(name, device, precision) for device, precision in (
        ("GPU", "AUTO"), ("CPU", "FULL"), ("GPU", "FULL"),
    ) for name in CONFIGS]
    tasks.append(("color", "GPU", "AUTO"))
    reference_rows = None
else:
    reference_rows = json.loads((report_path.parent / "exercise.json").read_text())
    bpy.app.handlers.load_post.insert(0, observe_loaded_schema)
    bpy.ops.wm.open_mainfile(filepath=str(BLEND))
    tasks = [("color", "GPU", "AUTO"), ("reset", "GPU", "AUTO")]
    result["settings_preserved"] = list(grade_settings()) == reference_rows["saved_settings"]
    assert result["settings_preserved"]
    assert result["loaded_schema"] == [3, 3, 3], result
    np.testing.assert_array_equal(
        np.asarray(bpy.data.images["Compositor palette"].pixels[:len(PALETTE) * 4],
                   dtype=np.float32).reshape(-1, 4), PALETTE,
    )

index = 0
stage = "apply"
wait_started = started
floor = 0
previous_pixels = None
fixed_identity = None
expected_settings = None
automatic_updates = 0


def pixel_error(actual, expected):
    error = np.max(np.abs(actual[:, :3] - expected[:, :3]), axis=1)
    return float(np.max(error / (1 + np.max(np.abs(expected[:, :3]), axis=1))))


def check_pixels(pixels, device, precision):
    assert np.isfinite(pixels).all(), pixels.tolist()
    invalid = ~np.isfinite(PALETTE[:, :3]).all(axis=1)
    np.testing.assert_array_equal(pixels[invalid, :3],
                                  np.tile((1., 0., 1.), (int(invalid.sum()), 1)))
    if device == "GPU" and precision == "AUTO":
        # One binary16 ULP at the source alpha, including zero/subnormals.
        half = PALETTE[:, 3].astype(np.float16)
        ulp = (np.nextafter(half, np.float16(np.inf)) - half).astype(np.float32)
        assert np.all(np.abs(pixels[:, 3] - PALETTE[:, 3]) <= ulp), pixels[:, 3]
    else:
        np.testing.assert_array_equal(pixels[:, 3], PALETTE[:, 3])


def check_truth(pixels, name, device, precision):
    if name not in ("reset", "exposure"):
        return
    # These in-gamut neutrals do not invoke boundary repair. They independently
    # anchor the CPU references and catch the old AUTO near-white collapse.
    expected = PALETTE[3:9].copy()
    expected[:, :3] *= 2.**(.5 if name == "exposure" else 0.)
    error = pixel_error(pixels[3:9], expected)
    limit = .01 if (device, precision) == ("GPU", "AUTO") else 1e-4
    users = consumers()
    bank_state = tuple((
        int(node.node_tree[nodes.PARAMETER_ACTIVE_BANK]),
        tuple(tuple(float(value) for value in np.asarray(
            node.node_tree[key].pixels[parameter_layout.TONE_SCALARS_SLOT * 4:
                                       (parameter_layout.TONE_SCALARS_SLOT + 1) * 4],
            dtype=np.float32,
        )) for key in nodes.PARAMETER_BANK_BINDINGS),
    ) for node in users)
    assert error <= limit, ("neutral exposure", name, device, precision, error,
                            pixels[3:9, :3].tolist(), expected[:, :3].tolist(), bank_state)


def finish(error=None):
    result.update(passed=error is None, error=error, seconds=time.monotonic() - started,
                  events=len(events), gpu={"backend": gpu.platform.backend_type_get(),
                                           "renderer": gpu.platform.renderer_get()})
    report_path.write_text(json.dumps(result, indent=2))
    bpy.ops.wm.quit_blender()


def exercise_grade_viewer_adoption():
    """A restored Grade requests a new Viewer evaluation after graph admission."""
    grade = consumers()[0]
    pointer = grade.as_pointer()
    scene_id = bpy.context.scene.as_pointer()
    receipts = nodes._compositor_receipts
    gate = nodes._grade_resources.gate
    kernel = grade.node_tree
    bank_generation = kernel[nodes.PARAMETER_GENERATION]
    banks = tuple(kernel[key] for key in nodes.PARAMETER_BANK_BINDINGS)
    viewer = next(image for image in bpy.data.images if image.type == "COMPOSITING")
    pixels = np.asarray(viewer.pixels[:], dtype=np.float32)
    requested = []
    held = {}
    request = nodes._request_compositor_evaluation
    deliver = receipts.completed

    def generation():
        return receipts.snapshot(scene_id).get(pointer)

    def track_request(scene):
        if scene.as_pointer() == scene_id:
            requested.append(generation())
        request(scene)

    def hold_completion(receipt):
        if receipt is not None and receipt.successful and receipt.identity == scene_id:
            binding = dict(receipt.snapshot).get(pointer)
            if binding is not None:
                held[binding] = receipt
                return
        deliver(receipt)

    while gate.blocked() or nodes._compositor_output_pending(grade):
        yield "current Grade Viewer"
    previous = generation()
    assert previous is not None
    receipts.completed = hold_completion
    nodes._request_compositor_evaluation = track_request
    try:
        receipts.forget(pointer)
        assert not nodes._refresh_nodes((grade,))
        first = generation()
        assert first is not None and first != previous and requested == [first], requested
        while first not in held or gate.blocked():
            yield "first adopted Grade Viewer completion"

        gate.evaluation_started(
            "compositor", scene_id, snapshot=receipts.snapshot(scene_id),
        )
        receipts.forget(pointer)
        try:
            assert not nodes._refresh_nodes((grade,))
            nodes._collect_compositor_receipts()
            assert generation() is None and requested == [first], requested
            assert grade.get(nodes._NODE_PENDING) == "status.waiting_compositor"
        finally:
            receipt = gate.evaluation_finished("compositor", scene_id)
            deliver(receipt)

        # The regular membership pass retries the unbound node once admission returns.
        nodes._collect_compositor_receipts()
        second = generation()
        assert second != first and requested == [first, second], requested
        deliver(held[first])
        nodes._collect_compositor_receipts()
        assert nodes._compositor_output_pending(grade)
        assert grade.get(nodes._NODE_PENDING) == "status.waiting_compositor"
        while second not in held:
            yield "retried Grade Viewer completion"
        deliver(held[second])
        nodes._collect_compositor_receipts()
        assert not nodes._compositor_output_pending(grade)
        assert not grade.get(nodes._NODE_PENDING)
        assert grade.node_tree == kernel and kernel[nodes.PARAMETER_GENERATION] == bank_generation
        assert tuple(kernel[key] for key in nodes.PARAMETER_BANK_BINDINGS) == banks
        np.testing.assert_array_equal(viewer.pixels[:], pixels)
        result["grade_viewer_adoption"] = True
    finally:
        receipts.completed = deliver
        nodes._request_compositor_evaluation = request


def exercise_viewer_receipts():
    yield from exercise_grade_viewer_adoption()
    helper = importlib.import_module(extension.__name__ + ".lut_helper")
    scene = bpy.context.scene
    scene.render.compositor_device = "CPU"
    scene.render.compositor_precision = "FULL"
    width, height = 16, 8
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    tree = scene.compositing_node_group
    stack = nodes.create_stack_node(tree)
    grade = nodes._make_grade()
    stack.pg_stack_entries.add().grade = grade
    source = next(node for node in tree.nodes if node.bl_idname == "CompositorNodeImage")
    viewer = next(node for node in tree.nodes if node.bl_idname == "CompositorNodeViewer")
    image = bpy.data.images.new("Stack Viewer source", width, height, alpha=True, float_buffer=True)
    image.colorspace_settings.name = "Non-Color"
    image.alpha_mode = "CHANNEL_PACKED"
    image.use_half_precision = False
    neutral_patches = np.asarray(((.005, .005, .005, .4), (.01, .01, .01, .65)), dtype=np.float32)
    image.pixels.foreach_set(np.tile(np.repeat(neutral_patches, width // 2, axis=0), (height, 1)).ravel())
    image.update()
    source.image = image
    tree.links.new(source.outputs["Image"], stack.inputs["Color"])
    tree.links.new(stack.outputs["Color"], viewer.inputs["Image"])
    tree.nodes.active = viewer
    stack_id = stack.as_pointer()
    scene_id = scene.as_pointer()
    receipts = nodes._compositor_receipts

    def generation(identity=scene_id):
        return receipts.snapshot(identity).get(stack_id)

    def quality():
        state = nodes._record_for(stack)["state"]
        assert state.error is None, state.error
        return state.applied_quality if state.applied_signature == state.desired_signature else None

    def viewer_patches():
        pixels = next(image for image in bpy.data.images if image.type == "COMPOSITING")
        assert tuple(pixels.size) == (width, height), tuple(pixels.size)
        rgba = np.asarray(pixels.pixels[:], dtype=np.float32).reshape(height, width, 4)
        return rgba[height // 2, [width // 4, 3 * width // 4]]

    while quality() != "full" or generation() is None or nodes._compositor_output_pending(stack):
        yield
    initial = viewer_patches()
    assert np.isfinite(initial).all() and np.all(initial[:, :3] > 1e-5), initial
    np.testing.assert_allclose(initial[:, 3], neutral_patches[:, 3], atol=1e-6, rtol=0)
    held = {}
    deliver = receipts.completed
    advance = helper.HelperStackJob.advance
    allow_refinement = False

    def hold_completion(receipt):
        if receipt is not None and receipt.successful:
            binding = dict(receipt.snapshot).get(stack_id)
            if binding is not None:
                held[receipt.identity, binding] = receipt
                return
        deliver(receipt)

    def hold_refinement(job):
        if job.preview_emitted and not job.cancelled and not allow_refinement:
            return None
        return advance(job)

    receipts.completed = hold_completion
    helper.HelperStackJob.advance = hold_refinement
    try:
        window = bpy.context.window
        gesture = nodes._begin_gesture(window.as_pointer(), stack)
        grade.pg_linear.exposure = 1.0
        while quality() != "preview" or (scene_id, generation()) not in held:
            yield
        preview = generation()
        allow_refinement = True
        nodes._end_gesture(window.as_pointer(), gesture)
        while quality() != "full" or (scene_id, generation()) not in held:
            yield
        full = generation()
        assert full != preview, (full, preview)
        deliver(held[scene_id, preview])
        nodes._collect_compositor_receipts()
        assert nodes._compositor_output_pending(stack)
        assert stack.get(nodes._NODE_PENDING) == "status.waiting_compositor"
        deliver(held[scene_id, full])
        nodes._collect_compositor_receipts()
        assert not nodes._compositor_output_pending(stack)
        assert not stack.get(nodes._NODE_PENDING)
        actual = viewer_patches()
        np.testing.assert_allclose(actual[:, :3], 2 * initial[:, :3], atol=1e-5, rtol=.03)
        assert np.any(np.abs(actual[:, :3] - initial[:, :3]) > 1e-5)
        np.testing.assert_allclose(actual[:, 3], initial[:, 3], atol=1e-6, rtol=0)
        result["stack_viewer_refinement"] = True

        kernel = stack.node_tree
        nodes._reset_compositor_receipts()
        assert generation() is None
        failures = nodes._refresh_nodes((stack,))
        assert not failures, failures
        adopted = generation()
        assert adopted is not None and adopted != full, (adopted, full)
        assert stack.node_tree == kernel and quality() == "full"
        deliver(held[scene_id, full])
        nodes._collect_compositor_receipts()
        assert nodes._compositor_output_pending(stack)
        assert stack.get(nodes._NODE_PENDING) == "status.waiting_compositor"
        while (scene_id, adopted) not in held:
            yield
        deliver(held[scene_id, adopted])
        nodes._collect_compositor_receipts()
        assert not nodes._compositor_output_pending(stack)
        assert not stack.get(nodes._NODE_PENDING)
        np.testing.assert_allclose(viewer_patches(), actual, atol=1e-6, rtol=0)
        result["stack_viewer_adoption"] = True

        second_scene = bpy.data.scenes.new("Second Stack Viewer Scene")
        second_scene.render.compositor_device = "CPU"
        second_scene.render.compositor_precision = "FULL"
        second_scene.render.resolution_x = width
        second_scene.render.resolution_y = height
        second_scene.render.resolution_percentage = 100
        second_id = second_scene.as_pointer()
        window.scene = second_scene
        second_scene.compositing_node_group = tree
        effects = getattr(second_scene, "compositor_effects", None)
        if effects is not None:
            # Exercise the default Viewer for a stack with the Grade in the first,
            # non-active effect. Its output feeds the active passthrough effect.
            output = next(node for node in tree.nodes if node.bl_idname == "NodeGroupOutput")
            tree.links.new(stack.outputs["Color"], output.inputs["Image"])
            graded_effect = effects.active
            passthrough = bpy.data.node_groups.new("Viewer active passthrough", nodes.COMPOSITOR_TREE)
            for direction in ("INPUT", "OUTPUT"):
                passthrough.interface.new_socket(name="Image", in_out=direction, socket_type="NodeSocketColor")
            passthrough.links.new(
                passthrough.nodes.new("NodeGroupInput").outputs["Image"],
                passthrough.nodes.new("NodeGroupOutput").inputs["Image"],
            )
            active_effect = effects.new("Viewer active passthrough")
            active_effect.node_group = passthrough
            active_effect.is_active = True
        while generation(second_id) is None:
            yield "second scene binding"
        second = generation(second_id)
        assert second != adopted and generation() == adopted, (second, generation(), adopted)
        assert stack.node_tree == kernel
        assert nodes._compositor_output_pending(stack)
        assert stack.get(nodes._NODE_PENDING) == "status.waiting_compositor"
        deliver(held[scene_id, adopted])
        nodes._collect_compositor_receipts()
        assert nodes._compositor_output_pending(stack)
        while (second_id, second) not in held:
            yield "second scene Viewer completion"
        deliver(held[second_id, second])
        nodes._collect_compositor_receipts()
        assert not nodes._compositor_output_pending(stack)
        assert not stack.get(nodes._NODE_PENDING)

        if effects is not None:
            assert effects.active == active_effect
            np.testing.assert_allclose(viewer_patches(), actual, atol=1e-6, rtol=0)
            graded_effect.enable_for_preview = False
        else:
            second_scene.compositing_node_group = None
        while generation(second_id) is not None:
            yield "second scene detachment"
        window.scene = scene
        assert generation() == adopted
        assert not nodes._compositor_output_pending(stack)
        assert not stack.get(nodes._NODE_PENDING)
        result["stack_viewer_scenes"] = True
    finally:
        receipts.completed = deliver
        helper.HelperStackJob.advance = advance


def complete():
    baseline = reference_rows["rows"] if reference_rows else rows
    references = {row["config"]: np.asarray(row["pixels"], dtype=np.float32)
                  for row in baseline if (row["device"], row["precision"]) == ("CPU", "FULL")}
    for row in rows:
        error = pixel_error(np.asarray(row["pixels"], dtype=np.float32), references[row["config"]])
        limit = .01 if (row["device"], row["precision"]) == ("GPU", "AUTO") else 1e-4
        row["normalized_rgb_error"] = error
        assert error <= limit, (row["config"], row["device"], row["precision"], error)
    if phase == "exercise":
        result["automatic_updates"] = automatic_updates
        result["saved_settings"] = list(grade_settings())
        for node in consumers():
            node.node_tree[nodes._KERNEL_KIND] = 3
        result["saved_schema"] = [node.node_tree[nodes._KERNEL_KIND] for node in consumers()]
        assert bpy.ops.wm.save_as_mainfile(filepath=str(BLEND)) == {"FINISHED"}
    else:
        result["repaired_schema"] = [node.node_tree[nodes._KERNEL_KIND] for node in consumers()]
        assert result["repaired_schema"] == [nodes._KERNEL_SCHEMA] * 3
        exercise = exercise_viewer_receipts()
        deadline = time.monotonic() + 120
        waiting_for = None

        def viewer_tick():
            nonlocal waiting_for
            try:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for {waiting_for or 'Viewer completion'}")
                waiting_for = next(exercise)
            except StopIteration:
                finish()
                return None
            except Exception:
                exercise.close()
                finish(traceback.format_exc())
                return None
            return .05

        bpy.app.timers.register(viewer_tick, first_interval=.05)
        return
    finish()


def tick():
    global index, stage, wait_started, floor, previous_pixels, fixed_identity
    global expected_settings, automatic_updates
    try:
        now = time.monotonic()
        if now - wait_started >= 40:
            users = consumers()
            diagnostic = {
                "task": tasks[index], "stage": stage, "event_floor": floor,
                "last_events": events[-3:], "expected_settings": expected_settings,
                "node_states": [repr(nodes._record_for(node)["state"]) for node in users],
                "pending_preparation": bool(nodes._preparation_runtime.pending),
                "pending_resources": bool(nodes._grade_resources.pending),
                "viewers": [(image.name, tuple(image.size)) for image in bpy.data.images
                            if image.type == "COMPOSITING"],
            }
            raise AssertionError(("Viewer did not automatically update", phase, diagnostic))
        name, device, precision = tasks[index]
        scene = bpy.context.scene
        if stage == "apply":
            floor = len(events) if index else 0
            if not (phase == "reload" and index == 0):
                if scene.render.compositor_device != device:
                    scene.render.compositor_device = device
                if scene.render.compositor_precision != precision:
                    scene.render.compositor_precision = precision
                configure(name)
            expected_settings = grade_settings()
            wait_started = now
            stage = "observe"
            return .1
        users = consumers()
        current = all(nodes.node_policy.output_allowed(nodes._record_for(node)["state"])
                      for node in users)
        if not current or len(events) <= floor:
            return .1
        frame = events[-1]
        if (not frame.get("current") or frame.get("settings") != expected_settings
                or (frame.get("device"), frame.get("precision")) != (device, precision)
                or now - frame["finished"] < .3):
            return .1
        viewers = [image for image in bpy.data.images if image.type == "COMPOSITING"]
        if not viewers or tuple(viewers[0].size) != (len(PALETTE), 8):
            return .1
        pixels = np.asarray(viewers[0].pixels[:len(PALETTE) * 4], dtype=np.float32).reshape(-1, 4)
        same_backend_edit = index > 0 and tasks[index - 1][1:] == (device, precision)
        if same_backend_edit and np.array_equal(pixels, previous_pixels):
            return .1
        assert grade_settings() == expected_settings
        assert (scene.render.compositor_device, scene.render.compositor_precision) == (device, precision)
        current_identity = identity()
        if fixed_identity is None:
            fixed_identity = current_identity
        else:
            assert current_identity == fixed_identity, ("Grade topology changed", current_identity, fixed_identity)
        check_pixels(pixels, device, precision)
        check_truth(pixels, name, device, precision)
        if same_backend_edit:
            automatic_updates += 1
        rows.append({"config": name, "device": device, "precision": precision,
                     "pixels": pixels.tolist(), "events": len(events), "identity": current_identity,
                     "parameter": parameter_image(users[0]).as_pointer()})
        print("COMPOSITOR", name, device, precision, "completed", len(events), flush=True)
        previous_pixels = pixels
        index += 1
        if index == len(tasks):
            complete()
            return None
        stage = "apply"
        wait_started = now
        return .1
    except Exception:
        traceback.print_exc()
        finish(traceback.format_exc())
        return None


bpy.app.timers.register(tick, first_interval=.1)

"""Keep generated Grade images out of Blender's interactive save prompt."""

import addon_utils
import importlib
import json
from pathlib import Path
import sys

import bpy
import numpy as np


repository, report_path = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.context.preferences.extensions.repos.new(
    name="Perceptual Grade image save test",
    module="pg_image_save",
    custom_directory=str(repository),
)
extension = importlib.import_module("bl_ext.pg_image_save.perceptual_grade")
nodes = importlib.import_module("bl_ext.pg_image_save.perceptual_grade.nodes")
errors = []
assert addon_utils.enable(
    extension.__name__, default_set=False, handle_error=errors.append
) is extension
assert not errors, errors
assert not bpy.app.background
bpy.context.preferences.filepaths.save_modified_images = "ASK"


def reconcile():
    nodes._render_init(bpy.context.scene)
    try:
        nodes._render_pre(bpy.context.scene)
    finally:
        nodes._render_finished(bpy.context.scene)


def parameter_banks(node):
    tree = node.node_tree
    missing = tuple(key for key in nodes.PARAMETER_BANK_BINDINGS if key not in tree)
    assert not missing, (node.name, tree.name, missing,
                         nodes._node_stores.get(node.as_pointer()),
                         node.get(nodes._NODE_ERROR))
    banks = tuple(tree[key] for key in nodes.PARAMETER_BANK_BINDINGS)
    active = tree[nodes.PARAMETER_ACTIVE_BANK]
    assert len(banks) == 2 and banks[0] != banks[1]
    assert active in (0, 1)
    selectors = [item for item in tree.nodes if item.get(nodes.PARAMETER_SELECTOR)]
    assert len(selectors) == 1, (node.name, selectors)
    selector = selectors[0]
    if tree.bl_idname == nodes.SHADER_TREE:
        selected = int(round(float(selector.outputs["Value"].default_value)))
    else:
        selected = int(round(float(selector.inputs[0].default_value)))
    assert selected == active, (node.name, active, selected)
    assert all(image.get(nodes.PARAMETER_IMAGE) == nodes.PARAMETER_SCHEMA
               for image in banks)
    readers = [item for item in tree.nodes if item.get(nodes.PARAMETER_READER)]
    observed = {item.get(nodes.PARAMETER_READER_BANK): item.image for item in readers}
    assert set(observed) == {0, 1}, (node.name, observed)
    assert all(observed[bank] == banks[bank] for bank in (0, 1)), node.name
    return banks


def parameter_image(node):
    return parameter_banks(node)[node.node_tree[nodes.PARAMETER_ACTIVE_BANK]]


def assert_clean_shared_image(users):
    banks = tuple(parameter_banks(node) for node in users)
    assert all(pair == banks[0] for pair in banks)
    for node in users:
        state = nodes._node_stores[node.as_pointer()]["state"]
        assert nodes.node_policy.output_allowed(state), (node.name, state)
        assert not node.get(nodes._NODE_ERROR)
    for image in banks[0]:
        assert image.packed_file is not None
        assert not image.is_dirty, "Grade publication left an unsaved parameter image"
    return parameter_image(users[0])


material = bpy.data.materials.new("Grade Save Material")
material.use_nodes = True
material.use_fake_user = True
shader = nodes.create_node(material.node_tree)
compositor_tree = bpy.data.node_groups.new("Grade Save Compositor", nodes.COMPOSITOR_TREE)
compositor_tree.use_fake_user = True
compositor = nodes.create_node(compositor_tree)
grade = nodes._make_grade()
shader.pg_grade = grade
compositor.pg_grade = grade
users = (shader, compositor)
reconcile()
image = assert_clean_shared_image(users)
authoritative_pixels = np.asarray(image.pixels[:], dtype=np.float32)
original_banks = parameter_banks(shader)
original_active = shader.node_tree[nodes.PARAMETER_ACTIVE_BANK]

# A dirty active bank is not a valid last-good result. Reconciliation restores
# the exact authoritative parameter snapshot and keeps selector metadata aligned.
damaged = parameter_image(shader)
nodes._write_grade_parameters(damaged, authoritative_pixels + 0.25)
assert damaged.is_dirty
reconcile()
repaired = assert_clean_shared_image(users)
np.testing.assert_array_equal(repaired.pixels[:], authoritative_pixels)
assert len({node.node_tree[nodes.PARAMETER_ACTIVE_BANK] for node in users}) == 1
assert all(nodes.node_policy.output_allowed(nodes._node_stores[node.as_pointer()]["state"])
           for node in users)
assert all(node.node_tree.get(nodes.PARAMETER_SIGNATURE)
           == nodes._preparation_signature(
               nodes._grade_settings(grade, nodes._working_space()),
               nodes._working_space(),
           ) for node in users)

# Failed integrity repair must fail closed; a later clean retry restores output.
damaged = parameter_image(shader)
nodes._write_grade_parameters(damaged, authoritative_pixels + 0.5)
original_writer = nodes._write_grade_parameters
repair_attempts = []


def fail_integrity_repair(target, pixels):
    repair_attempts.append(target.as_pointer())
    raise RuntimeError("simulated dirty Grade bank repair failure")


nodes._write_grade_parameters = fail_integrity_repair
try:
    reconcile()
finally:
    nodes._write_grade_parameters = original_writer
assert repair_attempts, "Dirty active bank did not request a repair"
for node in users:
    state = nodes._node_stores[node.as_pointer()]["state"]
    assert not nodes.node_policy.output_allowed(state)
    assert node.get(nodes._NODE_ERROR)
    assert node.node_tree.get(nodes._ERROR_KERNEL_KIND) == nodes._KERNEL_SCHEMA
reconcile()
repaired = assert_clean_shared_image(users)
np.testing.assert_array_equal(repaired.pixels[:], authoritative_pixels)
for node in users:
    state = nodes._node_stores[node.as_pointer()]["state"]
    assert nodes.node_policy.output_allowed(state)
    assert not node.get(nodes._NODE_ERROR)
original_banks = parameter_banks(shader)
original_bank_pointers = tuple(image.as_pointer() for image in original_banks)
original_active = shader.node_tree[nodes.PARAMETER_ACTIVE_BANK]
original_kernels = tuple(node.node_tree.as_pointer() for node in users)

for exposure in (0.25, 0.5, 0.75):
    grade.pg_linear.exposure = exposure
    reconcile()
    image = assert_clean_shared_image(users)
    assert tuple(item.as_pointer() for item in parameter_banks(shader)) == original_bank_pointers
    active = shader.node_tree[nodes.PARAMETER_ACTIVE_BANK]
    assert active == 1 - original_active
    original_active = active
    assert tuple(node.node_tree.as_pointer() for node in users) == original_kernels
    assert not bpy.ops.image.save_all_modified.poll()

filename = report_path.parent / "grade-images.blend"
assert bpy.ops.wm.save_as_mainfile(
    "EXEC_DEFAULT", filepath=str(filename), show_save_modified_images_dialog=True,
) == {"FINISHED"}
grade.pg_linear.exposure = 0.8125
reconcile()
image = assert_clean_shared_image(users)
saved_pixels = np.asarray(image.pixels[:], dtype=np.float32)
saved_banks = parameter_banks(shader)
saved_bank_names = tuple(bank.name for bank in saved_banks)
saved_bank_pixels = tuple(np.asarray(bank.pixels[:], dtype=np.float32) for bank in saved_banks)
saved_active_bank = shader.node_tree[nodes.PARAMETER_ACTIVE_BANK]
grade_name = grade.name
material_name = material.name
shader_name = shader.name
compositor_tree_name = compositor_tree.name
compositor_name = compositor.name

# This must finish before a save handler can rescue a dirty image. Blender
# returns INTERFACE instead if the native unsaved-image popup was opened.
save_result = bpy.ops.wm.save_mainfile(
    "INVOKE_DEFAULT", show_save_modified_images_dialog=True,
)
assert save_result == {"FINISHED"}, save_result
del image, grade, material, shader, compositor_tree, compositor, users
bpy.ops.wm.open_mainfile(filepath=str(filename))
grade = bpy.data.node_groups[grade_name]
shader = bpy.data.materials[material_name].node_tree.nodes[shader_name]
compositor = bpy.data.node_groups[compositor_tree_name].nodes[compositor_name]
users = (shader, compositor)
restored_banks = parameter_banks(shader)
assert tuple(bank.name for bank in restored_banks) == saved_bank_names
assert all(not bank.is_dirty and bank.packed_file is not None for bank in restored_banks)
for bank, pixels in zip(restored_banks, saved_bank_pixels):
    np.testing.assert_array_equal(bank.pixels[:], pixels)
assert shader.node_tree[nodes.PARAMETER_ACTIVE_BANK] == saved_active_bank
assert parameter_image(shader) == parameter_image(compositor)
np.testing.assert_array_equal(parameter_image(shader).pixels[:], saved_pixels)
assert grade.pg_linear.exposure == 0.8125
reconcile()
assert_clean_shared_image(users)


original_invalidation = nodes._invalidate_grade_parameters
original_dispatch = nodes._dispatch
original_publication = nodes._publish_grade_parameters
for fail_invalidation in (False, True):
    image = assert_clean_shared_image(users)
    image.use_fake_user = True
    previous_banks = parameter_banks(shader)
    previous_bank_pointers = tuple(
        bank.as_pointer() for bank in previous_banks
    )
    previous_signature = image.get(nodes.PARAMETER_SIGNATURE)
    previous_pixels = np.asarray(image.pixels[:], dtype=np.float32)
    previous_kernels = tuple(node.node_tree.as_pointer() for node in users)
    tag_attempts, installation_receipts, invalidation_errors = [], [], []

    def observing_invalidation(candidate):
        signature = candidate.get(nodes.PARAMETER_SIGNATURE)
        assert candidate.as_pointer() != image.as_pointer()
        assert candidate in previous_banks
        assert signature != previous_signature
        assert all(node.node_tree.get(nodes.PARAMETER_SIGNATURE) == signature
                   for node in users)
        assert all(parameter_image(node) == candidate for node in users)
        assert all(parameter_banks(node) == previous_banks for node in users)
        assert candidate.packed_file is not None and not candidate.is_dirty
        assert not installation_receipts, installation_receipts
        tag_attempts.append(candidate.as_pointer())
        if fail_invalidation:
            raise RuntimeError("simulated Grade image invalidation failure")
        original_invalidation(candidate)

    def observing_dispatch(node, event, *args, **kwargs):
        if event.kind == "installation_result" and event.error is None:
            assert len(tag_attempts) == 1, tag_attempts
            installation_receipts.append(node.as_pointer())
        return original_dispatch(node, event, *args, **kwargs)

    def observing_publication(*args, **kwargs):
        result = original_publication(*args, **kwargs)
        invalidation_errors.extend(error for _nodes, error in result)
        return result

    nodes._invalidate_grade_parameters = observing_invalidation
    nodes._dispatch = observing_dispatch
    nodes._publish_grade_parameters = observing_publication
    try:
        grade.pg_linear.exposure += 0.0625
        reconcile()
    finally:
        nodes._invalidate_grade_parameters = original_invalidation
        nodes._dispatch = original_dispatch
        nodes._publish_grade_parameters = original_publication
    assert len(tag_attempts) == 1, tag_attempts
    assert image.get(nodes.PARAMETER_SIGNATURE) == previous_signature
    np.testing.assert_array_equal(image.pixels[:], previous_pixels)
    assert image.packed_file is not None and not image.is_dirty
    if fail_invalidation:
        assert not installation_receipts, installation_receipts
        assert any("simulated Grade image invalidation failure" in str(error)
                   for error in invalidation_errors), invalidation_errors
        for node in users:
            state = nodes._node_stores[node.as_pointer()]["state"]
            assert not nodes.node_policy.output_allowed(state)
            assert node.get(nodes._NODE_ERROR)
            assert node.node_tree.get(nodes._ERROR_KERNEL_KIND) == nodes._KERNEL_SCHEMA
        image.use_fake_user = False
        del image
        reconcile()
        assert_clean_shared_image(users)
    else:
        assert not invalidation_errors, invalidation_errors
        assert set(installation_receipts) == {node.as_pointer() for node in users}
        assert tuple(node.node_tree.as_pointer() for node in users) == previous_kernels
        assert_clean_shared_image(users)
        image.use_fake_user = False
        del image


class PackingImage:
    """Inject native packing failures while retaining the real pixel buffer."""

    def __init__(self, image, fail_count, attempts, *, silent=False):
        self.image = image
        self.fail_count = fail_count
        self.attempts = attempts
        self.silent = silent

    def __getattr__(self, name):
        return getattr(self.image, name)

    def pack(self):
        self.attempts.append(self.image.as_pointer())
        if len(self.attempts) <= self.fail_count:
            if self.silent:
                return None
            raise RuntimeError("simulated Grade parameter packing failure")
        return self.image.pack()


original_packer = nodes._pack_grade_parameters
packing_results = []
for fail_count, silent in ((1, False), (1, True)):
    image = assert_clean_shared_image(users)
    image.use_fake_user = True
    previous_bank_pointers = tuple(
        bank.as_pointer() for bank in parameter_banks(shader)
    )
    previous_pixels = np.asarray(image.pixels[:], dtype=np.float32)
    previous_signature = image.get(nodes.PARAMETER_SIGNATURE)
    attempts = []

    def failing_packer(target):
        return original_packer(PackingImage(target, fail_count, attempts, silent=silent))

    nodes._pack_grade_parameters = failing_packer
    try:
        grade.pg_linear.exposure += 0.125
        reconcile()
    finally:
        nodes._pack_grade_parameters = original_packer
    assert len(attempts) == 1, attempts
    assert attempts[0] != image.as_pointer()
    assert attempts[0] in previous_bank_pointers
    assert image.get(nodes.PARAMETER_SIGNATURE) == previous_signature
    np.testing.assert_array_equal(image.pixels[:], previous_pixels)
    assert not image.is_dirty, "Failed candidate packing dirtied the published image"
    for node in users:
        state = nodes._node_stores[node.as_pointer()]["state"]
        assert not nodes.node_policy.output_allowed(state)
        assert node.get(nodes._NODE_ERROR)
        assert node.node_tree.get(nodes._ERROR_KERNEL_KIND) == nodes._KERNEL_SCHEMA
    packing_results.append({
        "failures": fail_count, "silent": silent, "rollback_clean": not image.is_dirty,
    })
    image.use_fake_user = False
    del image
    reconcile()
    assert_clean_shared_image(users)
assert not bpy.ops.image.save_all_modified.poll()

# Failure presentation and unused-resource cleanup must not hide a transaction's
# causal error or prevent the other shared consumer from failing closed.
image = assert_clean_shared_image(users)
image.use_fake_user = True
original_writer = nodes._write_grade_parameters
original_presenter = nodes._fail_installation
original_retirement = nodes._retire_kernels
original_publication = nodes._publish_grade_parameters
transaction_failures = []
upload_attempts = []
presented = []
retirement_attempts = []


def failing_upload(target, pixels):
    original_writer(target, pixels)
    upload_attempts.append(target.as_pointer())
    if len(upload_attempts) == 1:
        raise RuntimeError("transaction upload failed")


def failing_presenter(records, signature, error, quality="full"):
    result = original_presenter(records, signature, error, quality)
    presented.extend(record["node"].as_pointer() for record in records)
    if len(presented) == 1:
        raise RuntimeError("transaction presenter failed")
    return result


def failing_retirement(kernels):
    result = original_retirement(kernels)
    if len(presented) >= len(users) and not retirement_attempts:
        retirement_attempts.append(True)
        return result + (RuntimeError("transaction retirement failed"),)
    return result


def record_publication(*args, **kwargs):
    result = original_publication(*args, **kwargs)
    transaction_failures.extend(error for _nodes, error in result)
    return result


nodes._write_grade_parameters = failing_upload
nodes._fail_installation = failing_presenter
nodes._retire_kernels = failing_retirement
nodes._publish_grade_parameters = record_publication
try:
    grade.pg_linear.exposure += 0.125
    reconcile()
finally:
    nodes._write_grade_parameters = original_writer
    nodes._fail_installation = original_presenter
    nodes._retire_kernels = original_retirement
    nodes._publish_grade_parameters = original_publication


def diagnostic_messages(error):
    if isinstance(error, BaseExceptionGroup):
        return [message for child in error.exceptions for message in diagnostic_messages(child)]
    return [str(error)]


transaction_diagnostics = sorted({message for error in transaction_failures
                                  for message in diagnostic_messages(error)})
assert transaction_diagnostics == ["transaction presenter failed", "transaction retirement failed",
                                   "transaction upload failed"], transaction_diagnostics
assert retirement_attempts
assert set(presented) == {node.as_pointer() for node in users}
for node in users:
    assert not nodes.node_policy.output_allowed(nodes._node_stores[node.as_pointer()]["state"])
    assert node.node_tree.get(nodes._ERROR_KERNEL_KIND) == nodes._KERNEL_SCHEMA
image.use_fake_user = False
bpy.data.images.remove(image)
del image
reconcile()
assert_clean_shared_image(users)

# Node effect consumers may return presentation errors without raising. Keep
# those per-node errors in the same diagnostic shape and continue shared fanout.
image = assert_clean_shared_image(users)
image.use_fake_user = True
returned_failures = []
returned_presented = []
returned_upload_attempts = []


def failing_returned_upload(target, pixels):
    original_writer(target, pixels)
    returned_upload_attempts.append(target.as_pointer())
    if len(returned_upload_attempts) == 1:
        raise RuntimeError("returned-path upload failed")


def returning_presenter(records, signature, error, quality="full"):
    result = original_presenter(records, signature, error, quality)
    returned_presented.extend(record["node"].as_pointer() for record in records)
    if len(returned_presented) == 1:
        return result + (RuntimeError("returned presenter failure"),)
    return result


def record_returned_publication(*args, **kwargs):
    result = original_publication(*args, **kwargs)
    returned_failures.extend(error for _nodes, error in result)
    return result


nodes._write_grade_parameters = failing_returned_upload
nodes._fail_installation = returning_presenter
nodes._publish_grade_parameters = record_returned_publication
try:
    grade.pg_linear.exposure += 0.125
    reconcile()
finally:
    nodes._write_grade_parameters = original_writer
    nodes._fail_installation = original_presenter
    nodes._publish_grade_parameters = original_publication
returned_diagnostics = sorted({message for error in returned_failures
                               for message in diagnostic_messages(error)})
assert returned_diagnostics == [
    "returned presenter failure", "returned-path upload failed"], returned_failures
assert set(returned_presented) == {node.as_pointer() for node in users}
for node in users:
    assert not nodes.node_policy.output_allowed(nodes._node_stores[node.as_pointer()]["state"])
    assert node.node_tree.get(nodes._ERROR_KERNEL_KIND) == nodes._KERNEL_SCHEMA
image.use_fake_user = False
bpy.data.images.remove(image)
del image
reconcile()
assert_clean_shared_image(users)

# A failed retirement of the previous, unused kernel is reported while the
# replacement remains current for both users of the successfully updated image.
current_shader_kernel = shader.node_tree
previous_kernel = current_shader_kernel.copy()
shader.node_tree = previous_kernel
replacement_failures = []
replacement_retirements = []


def failing_previous_retirement(kernels):
    if any(kernel == previous_kernel for kernel in kernels):
        replacement_retirements.append(previous_kernel.as_pointer())
        return (RuntimeError("previous kernel retirement failed"),)
    return original_retirement(kernels)


def record_replacement_publication(*args, **kwargs):
    result = original_publication(*args, **kwargs)
    replacement_failures.extend(error for _nodes, error in result)
    return result


nodes._retire_kernels = failing_previous_retirement
nodes._publish_grade_parameters = record_replacement_publication
try:
    grade.pg_linear.exposure += 0.125
    reconcile()
finally:
    nodes._retire_kernels = original_retirement
    nodes._publish_grade_parameters = original_publication
assert replacement_retirements == [previous_kernel.as_pointer()], replacement_retirements
assert [message for error in replacement_failures for message in diagnostic_messages(error)] == [
    "previous kernel retirement failed"], replacement_failures
assert previous_kernel.users == 0
assert shader.node_tree == current_shader_kernel
assert_clean_shared_image(users)
assert not original_retirement((previous_kernel,))
del previous_kernel, current_shader_kernel

# The save handler retains a policy-authorized fallback for a derived image
# dirtied outside ordinary publication, without advancing its signature.
image = assert_clean_shared_image(users)
fallback_signature = image.get(nodes.PARAMETER_SIGNATURE)
nodes._write_grade_parameters(image, np.asarray(image.pixels[:], dtype=np.float32))
assert image.is_dirty
nodes._save_pre(None)
assert image.get(nodes.PARAMETER_SIGNATURE) == fallback_signature
assert_clean_shared_image(users)
del image

# Saving the addon must leave Blender's protection for real user images intact.
user_image = bpy.data.images.new("Unsaved user painting", width=1, height=1)
user_image.pixels[:] = (0.25, 0.5, 0.75, 1.0)
assert user_image.is_dirty
nodes._save_pre(None)
assert user_image.is_dirty and user_image.packed_file is None
assert bpy.ops.image.save_all_modified.poll()
window = next(window for manager in bpy.data.window_managers for window in manager.windows)
with bpy.context.temp_override(window=window):
    user_save_result = bpy.ops.wm.save_mainfile(
        "INVOKE_DEFAULT", show_save_modified_images_dialog=True,
    )
assert user_save_result == {"INTERFACE"}, user_save_result
assert user_image.is_dirty
assert user_image.packed_file is None

report_path.write_text(json.dumps({
    "passed": True,
    "grade_save": sorted(save_result),
    "user_image_save": sorted(user_save_result),
    "packing_failures": packing_results,
    "transaction_diagnostics": transaction_diagnostics,
    "save_fallback_repacked": True,
    "replacement_retirement_reported": True,
    "returned_presenter_reported": True,
    "serialized_pixels_exact": True,
    "invalidation_order_and_failure_checked": True,
}, indent=2))
bpy.ops.wm.quit_blender("EXEC_DEFAULT")

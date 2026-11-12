"""Verify Grade ownership conversion against native node and animation data."""

from types import SimpleNamespace
import importlib

import bpy


def _settings(nodes, owner):
    linear = owner if nodes._is_per_node_grade_node(owner) else owner.pg_linear
    tone = owner if nodes._is_per_node_grade_node(owner) else owner.pg_tone
    return {field: getattr(controls, field)
            for controls, fields in ((linear, nodes._LINEAR_FIELDS),
                                     (tone, nodes._TONE_FIELDS))
            for field in fields}


def _assert_values(actual, expected):
    assert actual.keys() == expected.keys()
    for field, value in expected.items():
        if isinstance(value, str):
            assert actual[field] == value, (field, actual[field], value)
        else:
            assert abs(actual[field] - value) < 1e-6, (field, actual[field], value)


def _curves(action, slot):
    if action is None:
        return ()
    return tuple(curve for layer in action.layers for strip in layer.strips
                 if (bag := strip.channelbag(slot)) is not None
                 for curve in bag.fcurves)


def _paths(action, slot):
    return {curve.data_path for curve in _curves(action, slot)}


def _driver_state(tree):
    return {(curve.data_path, curve.array_index, curve.driver.type,
             curve.driver.expression)
            for curve in tree.animation_data.drivers}


def _exception_text(error):
    parts = [str(error)]
    parts.extend(_exception_text(child) for child in getattr(error, "exceptions", ()))
    return " ".join(parts)


def _edges(tree):
    return {(link.from_node.name, link.from_socket.name,
             link.to_node.name, link.to_socket.name) for link in tree.links}


def _menu(nodes, tree, node):
    class Layout:
        def __init__(self):
            self.items = []

        def separator(self):
            pass

        def operator(self, operator_id, **kwargs):
            item = SimpleNamespace(operator_id=operator_id, **kwargs)
            self.items.append(item)
            return item

    layout = Layout()
    tree.nodes.active = node
    context = SimpleNamespace(space_data=SimpleNamespace(type="NODE_EDITOR", edit_tree=tree))
    nodes.draw_context_menu(SimpleNamespace(layout=layout), context)
    expected = nodes._is_grade_node(node)
    assert nodes.PG_OT_convert_grade.poll(context) == expected
    assert len(layout.items) == int(expected), layout.items
    if expected:
        assert layout.items[0].operator_id == nodes.PG_OT_convert_grade.bl_idname
        assert layout.items[0].target_kind == (
            "DATABLOCK" if nodes._is_per_node_grade_node(node) else "NODE"
        )
        wrong_editor = SimpleNamespace(
            pg_node=node, space_data=SimpleNamespace(type="VIEW_3D", edit_tree=tree),
        )
        assert not nodes.PG_OT_convert_grade.poll(wrong_editor)
        unrelated = bpy.data.node_groups.new("Unrelated conversion context", tree.bl_idname)
        try:
            wrong_tree = SimpleNamespace(
                pg_node=node,
                space_data=SimpleNamespace(type="NODE_EDITOR", edit_tree=unrelated),
            )
            assert not nodes.PG_OT_convert_grade.poll(wrong_tree)
        finally:
            bpy.data.node_groups.remove(unrelated)


def _round_trip(nodes, tree, assert_grade_current):
    shared = nodes.create_node(tree)
    shared.name = 'Convert "Grade" \\ safely'
    _menu(nodes, tree, shared)
    neutral = _settings(nodes, shared)
    with nodes._suspend(shared.pg_linear):
        shared.pg_linear.exposure = 1.5
    local = nodes.convert_grade_node(shared, "NODE")
    _assert_values(_settings(nodes, local), neutral)
    _menu(nodes, tree, local)
    shared = nodes.convert_grade_node(local, "DATABLOCK")
    assert shared.pg_grade is not None
    _assert_values(_settings(nodes, shared.pg_grade), neutral)
    original_grade = shared.pg_grade
    with nodes._suspend(original_grade.pg_linear):
        original_grade.pg_linear.exposure = 0.625
        original_grade.pg_linear.cr_balance = 0.125
        original_grade.pg_linear.yb_heading = -17.0
    with nodes._suspend(original_grade.pg_tone):
        original_grade.pg_tone.fit = 0.25
        original_grade.pg_tone.peak_nits = "4000"
    expected = _settings(nodes, original_grade)
    other = nodes.create_node(tree)
    other.pg_grade = original_grade
    parent = tree.nodes.new("NodeFrame")
    shared.parent = parent
    shared.location = (25.0, -75.0)
    shared.label = "Preserved conversion label"
    shared.width = 305
    shared.hide = True
    shared.mute = True
    shared.use_custom_color = True
    shared.color = (0.15, 0.25, 0.35)
    shared["user_marker"] = "preserved"
    for item in tree.nodes:
        item.select = item in (shared, other)
    tree.nodes.active = shared
    source = tree.nodes.new("ShaderNodeRGB" if tree.bl_idname == nodes.SHADER_TREE
                            else "CompositorNodeRGB")
    tree.links.new(source.outputs[0], shared.inputs["Color"])
    tree.links.new(shared.outputs["Color"], other.inputs["Color"])
    shared.inputs["Color"].default_value = (0.1, 0.2, 0.3, 0.4)
    if tree.bl_idname == nodes.SHADER_TREE:
        tree.links.new(shared.outputs["Alpha"], other.inputs["Alpha"])
        shared.inputs["Alpha"].default_value = 0.625
    original_edges = _edges(tree)
    original_name = shared.name
    context = SimpleNamespace(pg_node=shared,
                              space_data=SimpleNamespace(type="NODE_EDITOR", edit_tree=tree))
    errors = []
    operator = SimpleNamespace(target_kind="NODE", report=lambda *args: errors.append(args))
    assert nodes.PG_OT_convert_grade.execute(operator, context) == {"FINISHED"}, errors
    local = tree.nodes[original_name]
    assert nodes._is_per_node_grade_node(local)
    _assert_values(_settings(nodes, local), expected)
    assert other.pg_grade == original_grade
    local.exposure = 0.875
    assert original_grade.pg_linear.exposure == 0.625
    expected["exposure"] = 0.875
    local.exposure = expected["exposure"]
    shared = nodes.convert_grade_node(local, "DATABLOCK")
    assert shared.pg_grade != original_grade
    assert other.pg_grade == original_grade
    _assert_values(_settings(nodes, shared.pg_grade), expected)
    assert shared.name == original_name and tree.nodes.active == shared
    assert shared.parent == parent and tuple(shared.location) == (25.0, -75.0)
    assert shared.label == "Preserved conversion label" and shared.width == 305
    assert shared.hide and shared.mute
    assert shared["user_marker"] == "preserved"
    assert shared.select and other.select
    assert _edges(tree) == original_edges, (_edges(tree), original_edges)
    assert all(abs(a - b) < 1e-6 for a, b in zip(
        shared.inputs["Color"].default_value, (0.1, 0.2, 0.3, 0.4)))
    if tree.bl_idname == nodes.SHADER_TREE:
        assert shared.inputs["Alpha"].default_value == 0.625
    _menu(nodes, tree, source)
    assert not nodes._drain_preparations()
    assert_grade_current(shared)
    # A failed candidate must leave the original node, links, and Grade intact.
    restore = nodes._restore_node_connections
    injected = False

    def reject_candidate(node, snapshot):
        nonlocal injected
        result = restore(node, snapshot)
        if node != shared and snapshot["values"] and not injected:
            injected = True
            raise RuntimeError("injected conversion candidate failure")
        return result

    nodes._restore_node_connections = reject_candidate
    try:
        try:
            nodes.convert_grade_node(shared, "NODE")
        except RuntimeError as error:
            assert "injected conversion candidate failure" in str(error), error
        else:
            raise AssertionError("Conversion silently accepted a failed replacement")
    finally:
        nodes._restore_node_connections = restore
    assert tree.nodes[original_name] == shared
    assert injected
    assert _edges(tree) == original_edges, (_edges(tree), original_edges)
    _assert_values(_settings(nodes, shared.pg_grade), expected)


def _animated_snapshot(nodes, tree, assert_grade_current):
    local = nodes.create_per_node_node(tree)
    local.name = 'Animated "Grade" \\ conversion'
    sibling = nodes.create_per_node_node(tree)
    scene = bpy.context.scene
    for frame, value in ((1, 0.0), (3, 2.0)):
        scene.frame_set(frame)
        local.exposure = value
        assert local.keyframe_insert(data_path="exposure", frame=frame)
        local.location.x = 10 + value * 10
        assert local.keyframe_insert(data_path="location", index=0, frame=frame)
        sibling.cr_balance = value * 0.125
        assert sibling.keyframe_insert(data_path="cr_balance", frame=frame)
    grade_path = local.path_from_id("exposure")
    location_path = local.path_from_id("location")
    sibling_path = sibling.path_from_id("cr_balance")
    animation = tree.animation_data
    original_action = animation.action
    original_slot = animation.action_slot
    for curve in _curves(original_action, original_slot):
        for point in curve.keyframe_points:
            point.interpolation = "LINEAR"
    grade_driver = local.driver_add("fit")
    grade_driver.driver.expression = "frame / 10.0"
    local["preserved_driver"] = 0.0
    generic_driver = local.driver_add('["preserved_driver"]')
    generic_driver.driver.expression = "0.75"
    grade_driver_path = grade_driver.data_path
    generic_driver_path = generic_driver.data_path
    # Share this Action with another tree: conversion must isolate its edits.
    if tree.is_embedded_data:
        owner = next(material for material in bpy.data.materials
                     if material.node_tree == tree)
        other_owner = owner.copy()
        other_tree = other_owner.node_tree
    else:
        other_owner = other_tree = tree.copy()
    other_tree.animation_data_create()
    other_tree.animation_data.action = original_action
    other_tree.animation_data.action_slot = original_slot
    nla_action = original_action.copy()
    nla_action.use_fake_user = True
    track = animation.nla_tracks.new()
    track.mute = True
    strip = track.strips.new("Muted Grade conversion", 1, nla_action)
    strip.action_slot = nla_action.slots[0]
    scene.frame_set(2, subframe=0.25)
    bpy.context.view_layer.update()
    assert abs(local.exposure - 1.25) < 1e-6, (
        tree.bl_idname, scene.frame_current, scene.frame_subframe, local.exposure,
        [(curve.data_path, tuple(tuple(point.co) for point in curve.keyframe_points))
         for curve in _curves(animation.action, animation.action_slot)],
    )
    assert abs(local.fit - 0.225) < 1e-6, (
        tree.bl_idname, scene.frame_current, scene.frame_subframe, local.fit,
    )
    expected = _settings(nodes, local)
    location = tuple(local.location)
    name = local.name
    original_grades = {grade.as_pointer() for grade in bpy.data.node_groups
                       if grade.bl_idname == nodes.PGGradeData.bl_idname}
    original_drivers = {curve.data_path for curve in animation.drivers}
    restore = nodes._restore_node_connections
    injected = False

    def reject_candidate(node, snapshot):
        nonlocal injected
        result = restore(node, snapshot)
        if node != local and snapshot["values"] and not injected:
            injected = True
            raise RuntimeError("injected animated conversion failure")
        return result

    nodes._restore_node_connections = reject_candidate
    try:
        try:
            nodes.convert_grade_node(local, "DATABLOCK")
        except RuntimeError as error:
            assert "injected animated conversion failure" in str(error), error
        else:
            raise AssertionError("Animated conversion did not roll back its failed candidate")
    finally:
        nodes._restore_node_connections = restore
    assert tree.nodes[name] == local and animation.action == original_action
    assert injected
    assert strip.action == nla_action and track.mute
    assert {curve.data_path for curve in animation.drivers} == original_drivers
    assert {grade.as_pointer() for grade in bpy.data.node_groups
            if grade.bl_idname == nodes.PGGradeData.bl_idname} == original_grades
    _assert_values(_settings(nodes, local), expected)
    shared = nodes.convert_grade_node(local, "DATABLOCK")
    assert shared.name == name
    _assert_values(_settings(nodes, shared.pg_grade), expected)
    assert tuple(shared.location) == location
    assert animation.action != original_action
    assert grade_path not in _paths(animation.action, animation.action_slot)
    assert {location_path, sibling_path} <= _paths(animation.action, animation.action_slot)
    assert grade_path in _paths(original_action, original_slot)
    assert other_tree.animation_data.action == original_action
    assert strip.action != nla_action
    assert track.mute
    assert grade_path not in _paths(strip.action, strip.action_slot)
    assert {location_path, sibling_path} <= _paths(strip.action, strip.action_slot)
    assert grade_path in _paths(nla_action, nla_action.slots[0])
    driver_paths = {curve.data_path for curve in animation.drivers}
    assert grade_driver_path not in driver_paths
    assert generic_driver_path in driver_paths
    bpy.context.scene.frame_set(3)
    _assert_values(_settings(nodes, shared.pg_grade), expected)
    assert abs(shared.location.x - 30) < 1e-6, shared.location.x
    assert abs(shared["preserved_driver"] - 0.75) < 1e-6
    assert abs(sibling.cr_balance - 0.25) < 1e-6
    assert not nodes._drain_preparations()
    assert_grade_current(shared)
    round_trip = nodes.convert_grade_node(shared, "NODE")
    bpy.context.scene.frame_set(1)
    _assert_values(_settings(nodes, round_trip), expected)
    for node in tuple(other_tree.nodes):
        other_tree.nodes.remove(node)
    if tree.is_embedded_data:
        bpy.data.materials.remove(other_owner)
    else:
        bpy.data.node_groups.remove(other_owner)
    nla_action.use_fake_user = False


def _retired_receipt(nodes, tree, assert_grade_current):
    local = nodes.create_per_node_node(tree)
    record = nodes._record_for(local)
    source = record["source"]
    signature = record["state"].desired_preparation_signature
    replacement = nodes.convert_grade_node(local, "DATABLOCK")
    replacement_record = nodes._record_for(replacement)
    assert replacement_record["source"] is not source
    state, kernel = replacement_record["state"], replacement.node_tree
    assert not nodes._handle_preparation_result(source, signature, object(), None)
    assert nodes._record_for(replacement)["state"] == state
    assert replacement.node_tree == kernel
    assert not nodes._drain_preparations()
    assert_grade_current(replacement)


def _backup_cleanup(nodes):
    safe = bpy.data.node_groups.new(
        "Safe Grade conversion backup test", nodes.SHADER_TREE,
    )
    unsafe = bpy.data.node_groups.new(
        "Unsafe Grade conversion backup test", nodes.SHADER_TREE,
    )
    safe_name, unsafe_name = safe.name, unsafe.name
    backup_tag = nodes._CONVERSION_BACKUP
    safe[backup_tag] = True
    safe[backup_tag + "_safe_to_cleanup"] = True
    unsafe[backup_tag] = True
    unsafe[backup_tag + "_safe_to_cleanup"] = False
    nodes._cleanup_conversion_backups()
    assert bpy.data.node_groups.get(safe_name) is None
    assert bpy.data.node_groups.get(unsafe_name) == unsafe
    bpy.data.node_groups.remove(unsafe, do_unlink=False)


def prepare_persistence(nodes, trees):
    """Add converted fixtures to trees covered by the runner's existing reload."""
    fixtures = []
    frame = bpy.context.scene.frame_current + bpy.context.scene.frame_subframe
    for tree in trees:
        shared = nodes.create_node(tree)
        shared.pg_grade = nodes._make_grade()
        shared.pg_grade.pg_linear.exposure = 0.4375
        shared.pg_grade.pg_tone.fit = 0.375
        local = nodes.convert_grade_node(shared, "NODE")
        local.name = "Saved converted animated Grade"
        assert local.keyframe_insert(data_path="exposure", frame=frame)
        local.exposure = 1.4375
        assert local.keyframe_insert(data_path="exposure", frame=frame + 2)
        local.exposure = 0.4375
        fixtures.append({
            "tree": tree.name, "node": local.name, "type": local.bl_idname,
            "values": _settings(nodes, local), "keyed": True,
            "frames": ((frame, 0.4375), (frame + 2, 1.4375)),
        })
        local = nodes.create_per_node_node(tree)
        local.exposure = -0.625
        local.fit = 0.125
        shared = nodes.convert_grade_node(local, "DATABLOCK")
        shared.name = "Saved converted static Grade"
        fixtures.append({
            "tree": tree.name, "node": shared.name, "type": shared.bl_idname,
            "values": _settings(nodes, shared.pg_grade), "keyed": False,
        })
    assert not nodes._drain_preparations()
    return fixtures


def check_persistence(nodes, fixtures, assert_grade_current):
    for fixture in fixtures:
        tree = bpy.data.node_groups[fixture["tree"]]
        node = tree.nodes[fixture["node"]]
        assert node.bl_idname == fixture["type"]
        owner = node if fixture["keyed"] else node.pg_grade
        _assert_values(_settings(nodes, owner), fixture["values"])
        assert_grade_current(node)
        if fixture["keyed"]:
            animation = tree.animation_data
            curve = next(curve for curve in _curves(animation.action, animation.action_slot)
                         if curve.data_path == node.path_from_id("exposure"))
            assert tuple(tuple(point.co) for point in curve.keyframe_points) == fixture["frames"]
        tree.nodes.remove(node)
        if not fixture["keyed"] and owner.users == 0:
            bpy.data.node_groups.remove(owner)


def _assert_original_animation(nodes, tree, node, original, values, links,
                               action, slot, driver_state):
    assert node.name == original["name"] and node.bl_idname == "PGShaderGradePerNode"
    assert tree.nodes.get(original["name"]) == node
    assert tree.nodes.active == node and node.select
    _assert_values(_settings(nodes, node), values)
    assert _edges(tree) == links, (_edges(tree), links)
    animation = tree.animation_data
    assert animation.action == action and animation.action_slot == slot
    assert _driver_state(tree) == driver_state
    assert node.path_from_id("exposure") in _paths(action, slot)


def _transaction_failure_cases(nodes, tree, assert_grade_current):
    """Exercise reversible conversion failures before committing source removal."""
    scene = bpy.context.scene
    frame = scene.frame_current + scene.frame_subframe
    node = nodes.create_per_node_node(tree)
    node.name = "Conversion rollback fixture"
    node_name = node.name
    node_pointer = node.as_pointer()
    node.exposure = 0.625
    assert node.keyframe_insert(data_path="exposure", frame=frame)
    node.cr_balance = 0.25
    assert node.keyframe_insert(data_path="cr_balance", frame=frame)
    node["generic_driver"] = 0.0
    node.driver_add("fit").driver.expression = "frame / 10.0"
    node.driver_add("cr_balance").driver.expression = "frame / 20.0"
    node.driver_add('["generic_driver"]').driver.expression = "0.75"
    failures = nodes._refresh_nodes((node,))
    assert not failures, failures
    assert not nodes._drain_preparations()
    assert_grade_current(node)
    observer = bpy.data.objects.new("Grade conversion external driver", None)
    scene.collection.objects.link(observer)
    observer["grade_value"] = 0.0
    external_curve = observer.driver_add('["grade_value"]')
    external_variable = external_curve.driver.variables.new()
    external_variable.name = "grade_value"
    external_variable.type = "SINGLE_PROP"
    external_target = external_variable.targets[0]
    external_target.id_type = "NODETREE"
    external_target.id = tree
    external_target.data_path = node.path_from_id("exposure")
    external_curve.driver.expression = external_variable.name
    original_target_path = external_target.data_path
    bpy.context.view_layer.update()
    assert abs(observer["grade_value"] - node.exposure) < 1e-6
    tree.nodes.active = node
    node.select = True
    source = tree.nodes.new("ShaderNodeRGB")
    source_name = source.name
    tree.links.new(source.outputs["Color"], node.inputs["Color"])
    values = _settings(nodes, node)
    name = node.name
    original = {"name": name}
    links = _edges(tree)
    action = tree.animation_data.action
    slot = tree.animation_data.action_slot
    driver_state = _driver_state(tree)
    grade_driver_paths = {node.path_from_id("fit"), node.path_from_id("cr_balance")}
    try:
        rename = nodes._rename_conversion_node
        for fail_at, mutate in ((1, False), (2, True)):
            calls = 0
            injected = False

            def fail_rename(candidate, candidate_name):
                nonlocal calls, injected
                calls += 1
                if calls == fail_at:
                    if mutate:
                        rename(candidate, candidate_name)
                    injected = True
                    raise RuntimeError("injected conversion rename failure")
                rename(candidate, candidate_name)

            nodes._rename_conversion_node = fail_rename
            try:
                try:
                    nodes.convert_grade_node(node, "DATABLOCK")
                except RuntimeError as error:
                    assert "injected conversion rename failure" in str(error), error
                else:
                    raise AssertionError("Injected rename failure did not abort conversion")
            finally:
                nodes._rename_conversion_node = rename
            assert injected
            _assert_original_animation(
                nodes, tree, node, original, values, links, action, slot, driver_state,
            )
            assert external_target.id == tree
            assert external_target.data_path == original_target_path

        animation_type = nodes.NodeAnimationConversion
        finish = animation_type.finish
        injected = False

        def finish_then_raise(animation):
            nonlocal injected
            finish(animation)
            injected = True
            raise RuntimeError("injected post-finish animation failure")

        animation_type.finish = finish_then_raise
        try:
            try:
                nodes.convert_grade_node(node, "DATABLOCK")
            except RuntimeError as error:
                assert "injected post-finish animation failure" in str(error), error
            else:
                raise AssertionError("Animation finalization failure did not roll back")
        finally:
            animation_type.finish = finish
        assert injected
        _assert_original_animation(
            nodes, tree, node, original, values, links, action, slot, driver_state,
        )
        assert external_target.id == tree
        assert external_target.data_path == original_target_path

        # Exercise rollback after one of two backed-up Grade drivers is removed.
        animation_module = importlib.import_module(animation_type.__module__)
        remove_driver = animation_module._remove_conversion_driver
        remove_backup = animation_type._remove_backup
        injected = False
        cleanup_injected = False

        def fail_partial_driver_removal(owner_animation, curve):
            nonlocal injected
            result = remove_driver(owner_animation, curve)
            if not injected:
                injected = True
                raise RuntimeError("injected partial Grade-driver removal")
            return result

        def fail_backup_cleanup(animation, failures):
            nonlocal cleanup_injected
            remove_backup(animation, failures)
            cleanup_injected = True
            failures.append(RuntimeError("injected rollback driver-backup cleanup failure"))

        animation_module._remove_conversion_driver = fail_partial_driver_removal
        animation_type._remove_backup = fail_backup_cleanup
        try:
            try:
                nodes.convert_grade_node(node, "DATABLOCK")
            except Exception as error:
                messages = _exception_text(error)
                assert "injected partial Grade-driver removal" in messages, messages
                assert "injected rollback driver-backup cleanup failure" in messages, messages
            else:
                raise AssertionError("Partial driver removal did not abort conversion")
        finally:
            animation_module._remove_conversion_driver = remove_driver
            animation_type._remove_backup = remove_backup
        assert injected
        assert cleanup_injected
        _assert_original_animation(
            nodes, tree, node, original, values, links, action, slot, driver_state,
        )
        assert external_target.id == tree
        assert external_target.data_path == original_target_path
        assert not any(group.get(animation_module._BACKUP_TAG)
                       for group in bpy.data.node_groups)

        # A final preparation failure remains reversible because deletion has not begun.
        drain = nodes._drain_preparations
        nodes._drain_preparations = lambda _nodes=None, **_kwargs: (
            ((node,), RuntimeError("injected final Grade preparation failure")),
        )
        try:
            try:
                nodes.convert_grade_node(node, "DATABLOCK")
            except RuntimeError as error:
                assert "injected final Grade preparation failure" in str(error), error
            else:
                raise AssertionError("Failed final preparation did not roll back")
        finally:
            nodes._drain_preparations = drain
        _assert_original_animation(
            nodes, tree, node, original, values, links, action, slot, driver_state,
        )
        assert external_target.id == tree
        assert external_target.data_path == original_target_path

        remove_source = nodes._remove_conversion_source

        def fail_before_source_removal(owner_tree, source_node):
            raise RuntimeError("injected pre-removal failure")

        nodes._remove_conversion_source = fail_before_source_removal
        try:
            try:
                nodes.convert_grade_node(node, "DATABLOCK")
            except RuntimeError as error:
                assert "injected pre-removal failure" in str(error), error
            else:
                raise AssertionError("Pre-removal failure did not roll back")
        finally:
            nodes._remove_conversion_source = remove_source
        _assert_original_animation(
            nodes, tree, node, original, values, links, action, slot, driver_state,
        )
        assert external_target.id == tree
        assert external_target.data_path == original_target_path

        # Deletion and temporary-backup cleanup may report an error after commit.
        # Both errors must leave the already validated replacement current.
        commit = animation_type.commit
        apply_disposal = nodes._apply_node_disposal
        source_kernel_pointer = node.node_tree.as_pointer()
        committed_error = False

        def commit_then_raise(animation):
            nonlocal committed_error
            commit(animation)
            if not committed_error:
                committed_error = True
                raise RuntimeError("injected post-delete conversion cleanup failure")

        animation_type.commit = commit_then_raise

        def remove_then_raise(owner_tree, source_node):
            remove_source(owner_tree, source_node)
            raise RuntimeError("injected post-delete source cleanup failure")

        def fail_source_disposal(_source_node):
            raise RuntimeError("injected source disposal failure")

        nodes._remove_conversion_source = remove_then_raise
        nodes._apply_node_disposal = fail_source_disposal
        try:
            replacement = nodes.convert_grade_node(node, "DATABLOCK")
        finally:
            animation_type.commit = commit
            nodes._remove_conversion_source = remove_source
            nodes._apply_node_disposal = apply_disposal
        assert committed_error
        assert tree.nodes.get(name) == replacement
        assert replacement.as_pointer() != node_pointer
        assert replacement.bl_idname == "PGShaderGrade"
        _assert_values(_settings(nodes, replacement.pg_grade), values)
        assert external_target.id == replacement.pg_grade
        assert external_target.data_path == "pg_linear.exposure"
        assert not replacement.get(nodes._NODE_ERROR)
        assert not replacement.get(nodes._NODE_PENDING)
        assert node_pointer not in nodes._node_stores
        assert not any(group.as_pointer() == source_kernel_pointer
                       for group in bpy.data.node_groups)
        assert not nodes._drain_preparations()
        assert_grade_current(replacement)
        assert any(curve.data_path == replacement.path_from_id('["generic_driver"]')
                   for curve in tree.animation_data.drivers)
        assert not (grade_driver_paths
                    & {curve.data_path for curve in tree.animation_data.drivers})
        assert not any(group.get(animation_module._BACKUP_TAG)
                       for group in bpy.data.node_groups)
    finally:
        bpy.data.objects.remove(observer, do_unlink=True)
        for candidate_name in (node_name, source_name, name):
            candidate = tree.nodes.get(candidate_name)
            if candidate is not None:
                tree.nodes.remove(candidate)


def run(nodes, assert_grade_current):
    _backup_cleanup(nodes)
    scene = bpy.context.scene
    old_frame, old_subframe = scene.frame_current, scene.frame_subframe
    old_compositor = scene.compositing_node_group
    obj = bpy.context.object
    old_material = obj.active_material
    material = bpy.data.materials.new("Grade conversion animation material")
    material.use_nodes = True
    obj.active_material = material
    compositor = bpy.data.node_groups.new("Grade conversion compositor", nodes.COMPOSITOR_TREE)
    scene.compositing_node_group = compositor
    try:
        for tree in (material.node_tree, compositor):
            _round_trip(nodes, tree, assert_grade_current)
            _animated_snapshot(nodes, tree, assert_grade_current)
            _retired_receipt(nodes, tree, assert_grade_current)
        _transaction_failure_cases(nodes, material.node_tree, assert_grade_current)
    finally:
        obj.active_material = old_material
        scene.compositing_node_group = old_compositor
        for tree in (material.node_tree, compositor):
            for node in tuple(tree.nodes):
                tree.nodes.remove(node)
        bpy.data.materials.remove(material)
        bpy.data.node_groups.remove(compositor)
        scene.frame_set(old_frame, subframe=old_subframe)

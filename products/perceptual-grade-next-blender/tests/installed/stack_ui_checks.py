"""Installed Blender checks for explicit Grade creation and adjustment UI."""

from types import SimpleNamespace


def runtime_status(runtime):
    with runtime._lock:
        pending_sources = tuple(source.latest for source in runtime._pending)
        publications = tuple(
            (source.key, tuple(slots))
            for source, slots in runtime._publications.items()
        )
        failure = runtime._failure
    with runtime._host_lock:
        host_queue = tuple(
            (work.lane, work.snapshot.request_signature)
            for work in runtime._host_queue
        )
        active = runtime._host_active
        host_active = (None if active is None else
                       (active.lane, active.snapshot.request_signature,
                        active.job is not None))
    return (f"pending_sources={pending_sources!r}, publications={publications!r}, "
            f"host_queue={host_queue!r}, host_active={host_active!r}, "
            f"failure={failure!r}")


class Layout:
    def __init__(self, parent=None):
        self.parent = parent
        self.enabled = True
        if parent is None:
            self.operators = []
            self.properties = []
            self.context = {}
            self.property_states = []
            self.operator_states = []
            self.operator_options = []
            self.templates = []
            self.rows = []
        else:
            for name in ("operators", "properties", "context", "property_states",
                         "operator_states", "operator_options", "templates", "rows"):
                setattr(self, name, getattr(parent, name))

    @property
    def effective_enabled(self):
        return self.enabled and (self.parent is None or self.parent.effective_enabled)

    def context_pointer_set(self, name, value):
        # Blender accepts RNA pointers here, never an integer row index.
        assert callable(getattr(value, "as_pointer", None)), (name, value)
        self.context[name] = value

    def row(self, **_kwargs):
        layout = Layout(self)
        self.rows.append(layout)
        return layout

    def column(self, **_kwargs):
        return Layout(self)

    def prop(self, owner, name, **_kwargs):
        key = (owner.as_pointer(), name)
        self.properties.append(key)
        self.property_states.append((*key, self.effective_enabled))

    def template_ID(self, owner, name, **kwargs):
        self.templates.append((owner.as_pointer(), name, kwargs))

    def operator(self, operator_id, **kwargs):
        properties = SimpleNamespace()
        self.operators.append((operator_id, properties))
        self.operator_states.append((operator_id, self.effective_enabled))
        self.operator_options.append((operator_id, kwargs, self.effective_enabled))
        return properties

    def separator(self):
        pass

    def label(self, **_kwargs):
        pass


def check_grade_ui(nodes, tree):
    previous_active = tree.nodes.active
    node = nodes.create_node(tree)
    context = SimpleNamespace(pg_node=node, space_data=SimpleNamespace(edit_tree=tree))
    grade = None
    try:
        tree.nodes.active = node
        nodes._drain_preparations()
        assert node.pg_grade is None
        initial_kernel = node.node_tree
        initial_groups = {group.as_pointer() for group in nodes.bpy.data.node_groups}
        source = nodes._record_for(node)["source"]
        assert not nodes._preparation_runtime.pending, runtime_status(
            nodes._preparation_runtime)

        with nodes._suspend(node.pg_linear):
            node.pg_linear.exposure = 0.5
        nodes._ensure_all_kernels()
        nodes._drain_preparations()
        assert node.pg_grade is None
        assert all(abs(getattr(node.pg_linear, name) - value) < 1e-6
                   for name, value in nodes._LINEAR_DEFAULTS.items())
        assert node.node_tree == initial_kernel
        assert nodes._record_for(node)["source"] is source
        assert not nodes._preparation_runtime.pending

        # Property updates can precede the UI router; reject each local write
        # without allocating data, requesting preparation, or changing output.
        for field in nodes._LINEAR_FIELDS:
            default = nodes._LINEAR_DEFAULTS[field]
            setattr(node.pg_linear, field, default + 0.1)
            assert node.pg_grade is None
            assert all(abs(getattr(node.pg_linear, name) - value) < 1e-6
                       for name, value in nodes._LINEAR_DEFAULTS.items())
            assert node.node_tree == initial_kernel
            assert nodes._record_for(node)["source"] is source
            assert not nodes._preparation_runtime.pending
            assert {group.as_pointer() for group in nodes.bpy.data.node_groups} == initial_groups

        gesture_window = 9281
        nodes._arm_gesture(gesture_window, node, (0, 0))
        gesture_token = nodes._armed_gestures[gesture_window][0]
        try:
            nodes._activate_gesture(gesture_window, gesture_token)
            node.pg_linear.exposure = 0.25
            assert node.pg_grade is None
            assert all(abs(getattr(node.pg_linear, name) - value) < 1e-6
                       for name, value in nodes._LINEAR_DEFAULTS.items())
            assert node.node_tree == initial_kernel
            assert nodes._record_for(node)["source"] is source
            assert not nodes._preparation_runtime.pending
            assert {group.as_pointer() for group in nodes.bpy.data.node_groups} == initial_groups
        finally:
            nodes._end_gesture(gesture_window, gesture_token)
            nodes._gesture_routers.pop(gesture_window, None)
        assert node.pg_grade is None
        assert all(abs(getattr(node.pg_linear, name) - value) < 1e-6
                   for name, value in nodes._LINEAR_DEFAULTS.items())
        assert not nodes._preparation_runtime.pending

        for operator in (nodes.PG_OT_match_white, nodes.PG_OT_reset_directions):
            assert not operator.poll(context)
            assert operator.execute(None, context) == {"CANCELLED"}
        assert node.pg_grade is None
        assert all(abs(getattr(node.pg_linear, name) - value) < 1e-6
                   for name, value in nodes._LINEAR_DEFAULTS.items())

        sidebar = Layout()
        nodes.PG_PT_linear.draw(SimpleNamespace(layout=sidebar), context)
        expected = {(node.pg_linear.as_pointer(), field) for field in nodes._LINEAR_FIELDS}
        assert set(sidebar.properties) == expected
        assert not any(enabled for _owner, _name, enabled in sidebar.property_states)
        assert sidebar.operator_states == [
            (nodes.PG_OT_match_white.bl_idname, False),
            (nodes.PG_OT_reset_directions.bl_idname, False),
        ]
        assert not sidebar.templates

        tone_sidebar = Layout()
        assert nodes.PG_PT_tone.poll(context)
        nodes.PG_PT_tone.draw(SimpleNamespace(layout=tone_sidebar), context)
        expected_tone = {(node.pg_tone.as_pointer(), field)
                         for field in nodes._TONE_FIELDS}
        assert set(tone_sidebar.properties) == expected_tone
        assert not any(enabled for _owner, _name, enabled
                       in tone_sidebar.property_states)
        assert tone_sidebar.operator_states == [(nodes.PG_OT_reset_tone.bl_idname, False)]

        # The existing node selector remains the explicit creation action.
        node_layout = Layout()
        getattr(nodes, node.bl_idname).draw_buttons(node, context, node_layout)
        assert node_layout.templates == [(node.as_pointer(), "pg_grade", {
            "new": nodes.PG_OT_new_grade.bl_idname,
            "unlink": nodes.PG_OT_unlink_grade.bl_idname,
        })]
        assert nodes.PG_OT_new_grade.poll(context)
        assert nodes.PG_OT_new_grade.execute(None, context) == {"FINISHED"}
        grade = node.pg_grade
        assert grade is not None
        assert all(abs(getattr(grade.pg_linear, name) - value) < 1e-6
                   for name, value in nodes._LINEAR_DEFAULTS.items())

        sidebar = Layout()
        nodes.PG_PT_linear.draw(SimpleNamespace(layout=sidebar), context)
        expected = {(grade.pg_linear.as_pointer(), field) for field in nodes._LINEAR_FIELDS}
        assert set(sidebar.properties) == expected
        assert all(enabled for _owner, _name, enabled in sidebar.property_states)
        assert sidebar.operator_states == [
            (nodes.PG_OT_match_white.bl_idname, True),
            (nodes.PG_OT_reset_directions.bl_idname, True),
        ]
        assert all(operator.poll(context)
                   for operator in (nodes.PG_OT_match_white, nodes.PG_OT_reset_directions))

        tone_sidebar = Layout()
        nodes.PG_PT_tone.draw(SimpleNamespace(layout=tone_sidebar), context)
        expected_tone = {(grade.pg_tone.as_pointer(), field)
                         for field in nodes._TONE_FIELDS}
        assert set(tone_sidebar.properties) == expected_tone
        assert all(enabled for _owner, _name, enabled
                   in tone_sidebar.property_states)
        assert tone_sidebar.operator_states == [(nodes.PG_OT_reset_tone.bl_idname, True)]

        assert nodes.PG_OT_unlink_grade.execute(None, context) == {"FINISHED"}
        sidebar = Layout()
        nodes.PG_PT_linear.draw(SimpleNamespace(layout=sidebar), context)
        assert not any(enabled for _owner, _name, enabled in sidebar.property_states)
        tone_sidebar = Layout()
        nodes.PG_PT_tone.draw(SimpleNamespace(layout=tone_sidebar), context)
        assert not any(enabled for _owner, _name, enabled
                       in tone_sidebar.property_states)
    finally:
        tree.nodes.remove(node)
        tree.nodes.active = previous_active
        if grade is not None and grade.users == 0:
            nodes.bpy.data.node_groups.remove(grade)


def check_stack_ui(nodes, tree):
    assert nodes.PGShaderGradeStack.bl_width_default == 320
    assert nodes.PGCompositorGradeStack.bl_width_default == 320
    previous_active = tree.nodes.active
    node = nodes.create_stack_node(tree)
    created_grades = []
    try:
        node.pg_stack_entries.add().key = "ui-first"
        node.pg_stack_entries.add().key = "ui-second"
        context = SimpleNamespace(pg_stack_node=node,
                                  space_data=SimpleNamespace(edit_tree=tree))
        layout = Layout()
        nodes._draw_stack_node(node, context, layout)
        assert nodes.PG_PT_tone.poll(context)
        empty_tone = Layout()
        nodes.PG_PT_tone.draw(SimpleNamespace(layout=empty_tone), context)
        assert not empty_tone.properties
        buttons = [properties for operator_id, properties in layout.operators
                   if operator_id == nodes.PG_OT_new_stack_grade.bl_idname]
        entries = tuple(node.pg_stack_entries)
        assert layout.templates == [
            (entry.as_pointer(), "grade", {}) for entry in entries
        ]
        assert len(layout.rows) == len(entries)
        assert all(row.alignment == "EXPAND" for row in layout.rows)
        assert all(entry.grade is None for entry in entries)
        assert layout.properties == [
            (entry.as_pointer(), "enabled") for entry in entries
        ]
        assert [button.index for button in buttons] == [0, 1]
        assert layout.context["pg_stack_node"] == node
        assert nodes.PG_OT_new_stack_grade.poll(context)

        select_buttons = [properties for operator_id, properties in layout.operators
                          if operator_id == nodes.PG_OT_stack_action.bl_idname
                          and properties.action == "SELECT"]
        assert [button.index for button in select_buttons] == [0, 1]
        select_states = [enabled for (operator_id, enabled), (_id, properties)
                         in zip(layout.operator_states, layout.operators)
                         if operator_id == nodes.PG_OT_stack_action.bl_idname
                         and properties.action == "SELECT"]
        assert select_states == [True, True]
        select_options = [(kwargs, enabled)
                          for (operator_id, kwargs, enabled), (_id, properties)
                          in zip(layout.operator_options, layout.operators)
                          if operator_id == nodes.PG_OT_stack_action.bl_idname
                          and properties.action == "SELECT"]
        assert [kwargs.get("icon") for kwargs, _enabled in select_options] == [
            "GREASEPENCIL", "GREASEPENCIL"
        ]
        assert [kwargs.get("depress") for kwargs, _enabled in select_options] == [
            True, False
        ]
        assert all(enabled for _kwargs, enabled in select_options)
        select_zero = next(button for button in select_buttons if button.index == 0)
        assert nodes.PG_OT_stack_action.execute(select_zero, context) == {"FINISHED"}
        assert node.pg_active_index == 0

        for button in reversed(buttons):
            assert nodes.PG_OT_new_stack_grade.execute(button, context) == {"FINISHED"}
            created_grades.append(node.pg_stack_entries[button.index].grade)
            assert node.pg_active_index == button.index
        assert all(grade is not None for grade in created_grades)
        assert created_grades[0] != created_grades[1]
        assert node.pg_stack_entries[1].grade == created_grades[0]
        assert node.pg_stack_entries[0].grade == created_grades[1]
        assert nodes.PG_OT_new_stack_grade.execute(
            SimpleNamespace(index=2), context) == {"CANCELLED"}

        populated_layout = Layout()
        nodes._draw_stack_node(node, context, populated_layout)
        assert populated_layout.templates == [
            (entry.as_pointer(), "grade", {}) for entry in node.pg_stack_entries
        ]
        assert len(populated_layout.rows) == len(node.pg_stack_entries)
        assert all(row.alignment == "EXPAND" for row in populated_layout.rows)
        assert all(entry.grade is not None for entry in node.pg_stack_entries)
        assert populated_layout.properties == [
            (entry.as_pointer(), "enabled") for entry in node.pg_stack_entries
        ]

        tree.nodes.active = node
        sidebar_context = SimpleNamespace(space_data=SimpleNamespace(edit_tree=tree))
        assert nodes.PG_PT_linear.poll(sidebar_context)
        sidebar = Layout()
        nodes.PG_PT_linear.draw(SimpleNamespace(layout=sidebar), sidebar_context)
        settings = nodes._stack_active_grade(node).pg_linear.as_pointer()
        assert all((settings, field) in sidebar.properties for field in nodes._LINEAR_FIELDS)
        assert all(enabled for owner, _field, enabled in sidebar.property_states
                   if owner == settings)

        tone_sidebar = Layout()
        nodes.PG_PT_tone.draw(SimpleNamespace(layout=tone_sidebar), sidebar_context)
        tone_settings = nodes._stack_active_grade(node).pg_tone.as_pointer()
        assert all((tone_settings, field) in tone_sidebar.properties
                   for field in nodes._TONE_FIELDS)
        assert all(enabled for owner, _field, enabled
                   in tone_sidebar.property_states if owner == tone_settings)
        assert tone_sidebar.operator_states == [(nodes.PG_OT_reset_tone.bl_idname, True)]
    finally:
        tree.nodes.remove(node)
        tree.nodes.active = previous_active
        for grade in created_grades:
            if grade.users == 0:
                nodes.bpy.data.node_groups.remove(grade)


def check_gesture_region_routing(nodes, tree, window_key):
    token = object()
    nodes._gesture_routers[window_key] = token
    router = SimpleNamespace(window_key=window_key, token=token,
                             gesture_token=None, dragging=False,
                             press_position=None)
    context = SimpleNamespace(
        area=SimpleNamespace(type="NODE_EDITOR"),
        region=SimpleNamespace(type="WINDOW"),
        space_data=SimpleNamespace(edit_tree=tree),
    )
    event = SimpleNamespace(type="LEFTMOUSE", value="PRESS", mouse_x=10, mouse_y=10)
    nodes.PG_OT_gesture_router.modal(router, context, event)
    assert router.gesture_token is None
    assert window_key not in nodes._armed_gestures

    context.region.type = "UI"
    nodes.PG_OT_gesture_router.modal(router, context, event)
    assert router.gesture_token is not None
    nodes._release_armed_gesture(window_key, router.gesture_token)
    nodes._gesture_routers.pop(window_key, None)

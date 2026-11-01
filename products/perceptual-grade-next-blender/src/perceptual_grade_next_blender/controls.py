"""Authored control metadata and Blender bindings for Perceptual Grade Next.

The core settings classes remain the source of validation.  This module only
describes the editable RNA surface and converts a property-group snapshot into
immutable core values.  Grade and Stack controls are deliberately static:
their effective RNA paths are tracked so callers can report unsupported
animation instead of silently preparing a timeline of textures.
"""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ControlSpec:
    path: str
    label: str
    default: object
    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""
    kind: str = "float"
    animatable: bool = False


TONE_FIT = (-2.0, 2.0)
COLOR_FIT = (-2.0, 6.0)
TONE_LEVEL_DEFAULTS = (0.0, 0.015507796089266005 * 203.0, 0.18 * 203.0, 203.0, 1000.0)

# Logical control schema, in the same shapes as the reference model.
GRADE_CONTROL_SPECS = (
    ControlSpec("linear.exposure", "Exposure", 0.0, -6.0, 6.0, "stops"),
    ControlSpec("linear.source_white_xy", "Source White", (0.3127, 0.3290), kind="vector"),
    ControlSpec("linear.balance", "Balance", (0.0, 0.0), -2.0, 2.0, kind="vector"),
    ControlSpec("linear.spread", "Spread", (0.0, 0.0), -100.0, 150.0, "%", "vector"),
    ControlSpec("linear.heading", "Heading", (0.0, 0.0), -180.0, 180.0, "degrees", "vector"),
    ControlSpec("tone.input_nits", "Tone Levels", TONE_LEVEL_DEFAULTS, 0.0, 10000.0, "nits", "vector"),
    ControlSpec("tone.fit", "Tone Fit", 0.0, *TONE_FIT),
    ControlSpec("tone.reference_nits", "Reference White", 203.0, 203.0, 203.0, "nits"),
    ControlSpec("tone.peak_nits", "Peak", 1000.0, 406.0, 10000.0, "nits"),
    ControlSpec("color.lightness", "Lightness", (0.0,) * 16, -50.0, 50.0, kind="vector"),
    ControlSpec("color.chroma", "Chroma", (0.0,) * 16, -4.0, 4.0, kind="vector"),
    ControlSpec("color.adaptance", "Adaptance", (0.0,) * 8, -1.0, 1.0, kind="vector"),
    ControlSpec("color.lightness_fit", "Lightness Fit", 0.0, *COLOR_FIT),
    ControlSpec("color.chroma_fit", "Chroma Fit", 0.0, *COLOR_FIT),
    ControlSpec("color.global_gain", "Global Gain", 0.0, -4.0, 4.0),
    ControlSpec("color.adaptance_half_saturation", "Adaptance Half Saturation", 0.25, 0.05, 1.0),
    ControlSpec("color.web.hue_degrees", "Web Hue", (0.0,) * 24, -180.0, 180.0, "degrees", "vector"),
    ControlSpec("color.web.log_chroma", "Web Chroma", (0.0,) * 24, -4.0, 4.0, kind="vector"),
    ControlSpec("color.web.log_scale", "Web Scale", (0.0,) * 24, -4.0, 4.0, kind="vector"),
    ControlSpec("grading_white", "Grading White", "D65", kind="enum"),
    ControlSpec("working_space", "Working Space", "Linear Rec.709", kind="enum"),
)


def control_paths() -> tuple[str, ...]:
    """Return effective RNA paths that are static for a Grade or Stack."""
    scalar = (
        "exposure", "source_x", "source_y", "balance_a", "balance_b",
        "spread_a", "spread_b", "heading_a", "heading_b", "tone_fit",
        "reference_nits", "peak_nits", "lightness_fit", "chroma_fit",
        "global_gain", "adaptance_half_saturation", "grading_white",
        "working_space",
    )
    matrix = tuple(
        f"{family}_{row}_{column}"
        for family, rows, columns in (
            ("lightness", 4, 4), ("chroma", 4, 4),
            ("adaptance", 4, 2), ("web_hue", 4, 6),
            ("web_chroma", 4, 6), ("web_scale", 4, 6),
        )
        for row in range(rows) for column in range(columns)
    )
    levels = tuple(f"input_nits_{index}" for index in range(5))
    return tuple("perceptual_grade_next_controls." + name
                 for name in scalar + levels + matrix)


def unsupported_node_animation_paths(animation_data, node_path: str) -> tuple[str, ...]:
    """Find channels targeting this node's controls in its owner NodeTree.

    ``node_path`` is the result of ``node.path_from_id()`` (for example
    ``nodes[\"Grade\"]``). Unrelated NodeTree animation remains supported.
    """
    if animation_data is None:
        return ()
    prefix = node_path + "."
    grade_paths = {prefix + path for path in control_paths()}
    field_names = tuple(path.split(".", 1)[1] for path in control_paths())
    stack_patterns = tuple(
        re.compile(
            re.escape(prefix + "perceptual_grade_next_stack_controls.entries")
            + r"\[\d+\]\.settings\." + re.escape(field)
        )
        for field in field_names
    )
    stack_metadata = re.compile(
        re.escape(prefix + "perceptual_grade_next_stack_controls.entries")
        + r"\[\d+\]\.(direction|enabled)"
    )

    def is_static_target(path):
        return (path in grade_paths or stack_metadata.fullmatch(path) is not None
                or any(pattern.fullmatch(path) is not None for pattern in stack_patterns))

    found = []
    def visit(owner):
        if owner is None:
            return
        for curve in getattr(owner, "fcurves", ()):
            if is_static_target(curve.data_path):
                found.append(curve.data_path)
    action = getattr(animation_data, "action", None)
    visit(action)
    for track in getattr(animation_data, "nla_tracks", ()):
        for strip in getattr(track, "strips", ()):
            visit(getattr(strip, "action", None))
    for driver in getattr(animation_data, "drivers", ()):
        if is_static_target(driver.data_path):
            found.append(driver.data_path)
    return tuple(dict.fromkeys(found))


def settings_from_controls(group):
    """Build a validated core ``GradeSettings`` snapshot from an RNA group."""
    from ..perceptual_grade_next_core import (
        ColorSettings, GradeSettings, LinearSettings, ToneSettings, WebSettings,
    )

    linear = LinearSettings(
        exposure=float(group.exposure),
        source_white_xy=(float(group.source_x), float(group.source_y)),
        balance=(float(group.balance_a), float(group.balance_b)),
        spread=(float(group.spread_a), float(group.spread_b)),
        heading=(float(group.heading_a), float(group.heading_b)),
    )
    tone = ToneSettings(
        input_nits=tuple(float(getattr(group, f"input_nits_{index}")) for index in range(5)),
        fit=float(group.tone_fit),
        reference_nits=203.0,
        peak_nits=float(group.peak_nits),
    )
    color = ColorSettings(
        lightness=tuple(tuple(float(getattr(group, f"lightness_{i}_{j}")) for j in range(4)) for i in range(4)),
        chroma=tuple(tuple(float(getattr(group, f"chroma_{i}_{j}")) for j in range(4)) for i in range(4)),
        adaptance=tuple(tuple(float(getattr(group, f"adaptance_{i}_{j}")) for j in range(2)) for i in range(4)),
        lightness_fit=float(group.lightness_fit),
        chroma_fit=float(group.chroma_fit),
        global_gain=float(group.global_gain),
        adaptance_half_saturation=float(group.adaptance_half_saturation),
        web=WebSettings(
            hue_degrees=tuple(tuple(float(getattr(group, f"web_hue_{i}_{j}")) for j in range(6)) for i in range(4)),
            log_chroma=tuple(tuple(float(getattr(group, f"web_chroma_{i}_{j}")) for j in range(6)) for i in range(4)),
            log_scale=tuple(tuple(float(getattr(group, f"web_scale_{i}_{j}")) for j in range(6)) for i in range(4)),
        ),
    )
    return GradeSettings(
        linear=linear, tone=tone, color=color,
        grading_white="D65", working_space=group.working_space,
    )


def _property_group_class(bpy):
    from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, PointerProperty
    from .updates import control_changed

    class PGNEXT_GradeControls(bpy.types.PropertyGroup):
        """Static authored controls shared by Grade and Stack entries."""

        perceptual_grade_next_ready: BoolProperty(default=False, options={"HIDDEN"})
        preparation_ledger: PointerProperty(
            type=bpy.types.NodeTree, options={"HIDDEN"},
        )

        exposure: FloatProperty(name="Exposure", default=0.0, min=-6.0, max=6.0, options=set(), update=control_changed)
        source_x: FloatProperty(name="Source White X", default=0.3127, min=0.0, max=0.9, precision=5, options=set(), update=control_changed)
        source_y: FloatProperty(name="Source White Y", default=0.3290, min=0.0, max=0.9, precision=5, options=set(), update=control_changed)
        balance_a: FloatProperty(name="Balance A", default=0.0, min=-2.0, max=2.0, options=set(), update=control_changed)
        balance_b: FloatProperty(name="Balance B", default=0.0, min=-2.0, max=2.0, options=set(), update=control_changed)
        spread_a: FloatProperty(name="Spread A", default=0.0, min=-100.0, max=150.0, options=set(), update=control_changed)
        spread_b: FloatProperty(name="Spread B", default=0.0, min=-100.0, max=150.0, options=set(), update=control_changed)
        heading_a: FloatProperty(name="Heading A", default=0.0, min=-180.0, max=180.0, options=set(), update=control_changed)
        heading_b: FloatProperty(name="Heading B", default=0.0, min=-180.0, max=180.0, options=set(), update=control_changed)
        tone_fit: FloatProperty(name="Tone Fit", default=0.0, min=-2.0, max=2.0, options=set(), update=control_changed)
        # A fixed min/max makes unsupported viewing contexts impossible to author.
        reference_nits: FloatProperty(name="Reference White", default=203.0, min=203.0, max=203.0, options=set(), update=control_changed)
        peak_nits: FloatProperty(name="Peak", default=1000.0, min=406.0, max=10000.0, options=set(), update=control_changed)
        lightness_fit: FloatProperty(name="Lightness Fit", default=0.0, min=-2.0, max=6.0, options=set(), update=control_changed)
        chroma_fit: FloatProperty(name="Chroma Fit", default=0.0, min=-2.0, max=6.0, options=set(), update=control_changed)
        global_gain: FloatProperty(name="Global Gain", default=0.0, min=-4.0, max=4.0, options=set(), update=control_changed)
        adaptance_half_saturation: FloatProperty(name="Adaptance Half Saturation", default=0.25, min=0.05, max=1.0, options=set(), update=control_changed)
        grading_white: EnumProperty(name="Grading White", items=(("D65", "D65", ""),), default="D65", options=set(), update=control_changed)
        working_space: EnumProperty(name="Working Space", items=tuple((x, x, "") for x in ("Linear Rec.709", "Linear Rec.2020", "ACEScg")), default="Linear Rec.709", options=set(), update=control_changed)

    for index, default in enumerate(TONE_LEVEL_DEFAULTS):
        PGNEXT_GradeControls.__annotations__[f"input_nits_{index}"] = FloatProperty(
            name=("Black", "Shadows", "Midtones", "White", "Highlights")[index],
            default=default, min=0.0, max=10000.0, precision=3, options=set(), update=control_changed,
        )
    groups = (
        ("lightness", 4, 4, -50.0, 50.0),
        ("chroma", 4, 4, -4.0, 4.0),
        ("adaptance", 4, 2, -1.0, 1.0),
        ("web_hue", 4, 6, -180.0, 180.0),
        ("web_chroma", 4, 6, -4.0, 4.0),
        ("web_scale", 4, 6, -4.0, 4.0),
    )
    for prefix, rows, columns, minimum, maximum in groups:
        for row in range(rows):
            for column in range(columns):
                name = f"{prefix}_{row}_{column}"
                PGNEXT_GradeControls.__annotations__[name] = FloatProperty(
                    name=f"{row + 1}.{column + 1}", default=0.0,
                    min=minimum, max=maximum, precision=2, options=set(), update=control_changed,
                )
    class PGNEXT_StackEntryControls(bpy.types.PropertyGroup):
        perceptual_grade_next_ready: BoolProperty(default=False, options={"HIDDEN"})
        direction: EnumProperty(
            name="Direction", items=(("FORWARD", "Forward", ""), ("INVERSE", "Inverse", "")),
            default="FORWARD", options=set(), update=control_changed,
        )
        enabled: BoolProperty(name="Enabled", default=True, options=set(), update=control_changed)
        settings: PointerProperty(type=PGNEXT_GradeControls)

    class PGNEXT_StackControls(bpy.types.PropertyGroup):
        perceptual_grade_next_ready: BoolProperty(default=False, options={"HIDDEN"})
        preparation_ledger: PointerProperty(
            type=bpy.types.NodeTree, options={"HIDDEN"},
        )
        entries: CollectionProperty(type=PGNEXT_StackEntryControls)

    return (PGNEXT_GradeControls, PGNEXT_StackEntryControls, PGNEXT_StackControls,
            PointerProperty(type=PGNEXT_GradeControls), PointerProperty(type=PGNEXT_StackControls))


def _draw_grade_controls(layout, controls):
    layout.prop(controls, "working_space")
    layout.label(text="Grading white: D65 / 203 nits")
    col = layout.column(align=True)
    col.label(text="Linear")
    for name in ("exposure", "source_x", "source_y", "balance_a", "balance_b",
                 "spread_a", "spread_b", "heading_a", "heading_b"):
        col.prop(controls, name)
    col = layout.column(align=True)
    col.label(text="Tone")
    row = col.row(align=True)
    for index in range(5):
        row.prop(controls, f"input_nits_{index}",
                 text=("Black", "Shadows", "Midtones", "White", "Highlights")[index])
    col.prop(controls, "tone_fit")
    col.prop(controls, "peak_nits")
    col = layout.column(align=True)
    col.label(text="Color")
    for name in ("lightness_fit", "chroma_fit", "global_gain", "adaptance_half_saturation"):
        col.prop(controls, name)
    for family, rows, columns, heading in (
        ("lightness", 4, 4, "Lightness Coefficients"),
        ("chroma", 4, 4, "Chroma Coefficients"),
        ("adaptance", 4, 2, "Compact Adaptance"),
        ("web_hue", 4, 6, "Web Hue"),
        ("web_chroma", 4, 6, "Web Chroma"),
        ("web_scale", 4, 6, "Web Scale"),
    ):
        box = layout.box()
        box.label(text=heading)
        for row_index in range(rows):
            row = box.row(align=True)
            for column_index in range(columns):
                row.prop(controls, f"{family}_{row_index}_{column_index}", text="")


_CLASSES = ()
_NODE_PROP = None
_PANEL = None


def register():
    """Register static controls and a compact Node Editor sidebar panel."""
    global _CLASSES, _NODE_PROP, _PANEL
    if _CLASSES:
        return
    import bpy
    group, entry, stack, pointer, stack_pointer = _property_group_class(bpy)
    bpy.utils.register_class(group)
    bpy.utils.register_class(entry)
    bpy.utils.register_class(stack)
    bpy.types.Node.perceptual_grade_next_controls = pointer
    bpy.types.Node.perceptual_grade_next_stack_controls = stack_pointer

    class PGNEXT_PT_controls(bpy.types.Panel):
        bl_idname = "PGNEXT_PT_controls"
        bl_label = "Perceptual Grade Next"
        bl_space_type = "NODE_EDITOR"
        bl_region_type = "UI"
        bl_category = "Perceptual Grade"

        @classmethod
        def poll(cls, context):
            node = getattr(getattr(context, "space_data", None), "edit_tree", None)
            active = getattr(getattr(node, "nodes", None), "active", None)
            return bool(active and active.get("perceptual_grade_next_backend") in {
                "native_grade_graph", "native_stack_lut"
            })

        def draw(self, context):
            node = context.space_data.edit_tree.nodes.active
            layout = self.layout
            layout.operator("node.pg_next_open_scope", text="Open Scope", icon="VIEWZOOM")
            if node.get("perceptual_grade_next_backend") == "native_stack_lut":
                stack_controls = node.perceptual_grade_next_stack_controls
                layout.label(text="Stack · static entries")
                for index, entry in enumerate(stack_controls.entries):
                    box = layout.box()
                    row = box.row(align=True)
                    row.label(text=str(index + 1))
                    row.prop(entry, "enabled", text="")
                    row.prop(entry, "direction", text="")
                    up_column = row.column()
                    up_column.enabled = index > 0
                    move_up = up_column.operator(
                        "node.pg_next_stack_move_entry", text="", icon="TRIA_UP",
                        emboss=False,
                    )
                    move_up.index = index
                    move_up.offset = -1
                    down_column = row.column()
                    down_column.enabled = index + 1 < len(stack_controls.entries)
                    move_down = down_column.operator(
                        "node.pg_next_stack_move_entry", text="", icon="TRIA_DOWN",
                        emboss=False,
                    )
                    move_down.index = index
                    move_down.offset = 1
                    remove = row.operator("node.pg_next_stack_remove_entry", text="", icon="X")
                    remove.index = index
                    _draw_grade_controls(box, entry.settings)
                layout.operator("node.pg_next_stack_add_entry", text="Add Grade", icon="ADD")
                quality = node.node_tree.get("perceptual_grade_next_stack_quality_tier", "")
                layout.label(text=("Final evaluator: 65³ LUT" if quality == "65^3"
                                   else "Preview evaluator: 33³ LUT"))
                state = node.get("perceptual_grade_next_preparation_state", "READY")
                layout.label(text=f"Preparation: {state.title()}")
                error = node.get("perceptual_grade_next_preparation_error", "")
                if error:
                    layout.label(text=error[:96], icon="ERROR")
                if state in {"FAILED", "UNAVAILABLE"}:
                    label = "Retry Preparation" if state == "FAILED" else "Retry After Removing Animation"
                    layout.operator("node.pg_next_retry_preparation", text=label, icon="FILE_REFRESH")
                return
            controls = node.perceptual_grade_next_controls
            _draw_grade_controls(layout, controls)
            state = node.get("perceptual_grade_next_preparation_state", "READY")
            layout.label(text=f"Preparation: {state.title()}")
            error = node.get("perceptual_grade_next_preparation_error", "")
            if error:
                layout.label(text=error[:96], icon="ERROR")
            if state in {"FAILED", "UNAVAILABLE"}:
                label = "Retry Preparation" if state == "FAILED" else "Retry After Removing Animation"
                layout.operator("node.pg_next_retry_preparation", text=label, icon="FILE_REFRESH")

    bpy.utils.register_class(PGNEXT_PT_controls)
    class PGNEXT_OT_stack_add_entry(bpy.types.Operator):
        bl_idname = "node.pg_next_stack_add_entry"
        bl_label = "Add Grade Stack Entry"
        bl_options = {"REGISTER", "UNDO"}

        def execute(self, context):
            node = context.space_data.edit_tree.nodes.active
            entries = node.perceptual_grade_next_stack_controls.entries
            item = entries.add()
            item.enabled = True
            item.direction = "FORWARD"
            from .updates import mark_node_dirty
            mark_node_dirty(node)
            return {"FINISHED"}

    class PGNEXT_OT_stack_remove_entry(bpy.types.Operator):
        bl_idname = "node.pg_next_stack_remove_entry"
        bl_label = "Remove Grade Stack Entry"
        bl_options = {"REGISTER", "UNDO"}
        index: bpy.props.IntProperty(default=0)

        def execute(self, context):
            node = context.space_data.edit_tree.nodes.active
            entries = node.perceptual_grade_next_stack_controls.entries
            if 0 <= self.index < len(entries):
                entries.remove(self.index)
                from .updates import mark_node_dirty
                mark_node_dirty(node)
            return {"FINISHED"}

    class PGNEXT_OT_stack_move_entry(bpy.types.Operator):
        bl_idname = "node.pg_next_stack_move_entry"
        bl_label = "Move Grade Stack Entry"
        bl_description = "Move this Grade earlier or later in the Stack"
        bl_options = {"INTERNAL", "UNDO"}
        index: bpy.props.IntProperty(default=0, min=0)
        offset: bpy.props.IntProperty(default=0, min=-1, max=1)

        def execute(self, context):
            node = context.space_data.edit_tree.nodes.active
            if not move_stack_entry(node, self.index, self.offset):
                return {"CANCELLED"}
            return {"FINISHED"}

    class PGNEXT_OT_retry_preparation(bpy.types.Operator):
        bl_idname = "node.pg_next_retry_preparation"
        bl_label = "Retry Perceptual Grade Preparation"
        bl_options = {"INTERNAL"}

        @classmethod
        def poll(cls, context):
            node = getattr(getattr(context, "space_data", None), "edit_tree", None)
            active = getattr(getattr(node, "nodes", None), "active", None)
            return bool(active and active.get("perceptual_grade_next_preparation_state")
                        in {"FAILED", "UNAVAILABLE"})

        def execute(self, context):
            from .updates import mark_node_dirty
            if not mark_node_dirty(context.space_data.edit_tree.nodes.active):
                self.report({"ERROR"}, "Could not retry this preparation")
                return {"CANCELLED"}
            return {"FINISHED"}

    bpy.utils.register_class(PGNEXT_OT_stack_add_entry)
    bpy.utils.register_class(PGNEXT_OT_stack_remove_entry)
    bpy.utils.register_class(PGNEXT_OT_stack_move_entry)
    bpy.utils.register_class(PGNEXT_OT_retry_preparation)
    _CLASSES = (group, entry, stack, PGNEXT_PT_controls,
                PGNEXT_OT_stack_add_entry, PGNEXT_OT_stack_remove_entry,
                PGNEXT_OT_stack_move_entry,
                PGNEXT_OT_retry_preparation)
    _NODE_PROP = pointer
    _PANEL = PGNEXT_PT_controls


def unregister():
    global _CLASSES, _NODE_PROP, _PANEL
    if not _CLASSES:
        return
    import bpy
    if hasattr(bpy.types.Node, "perceptual_grade_next_controls"):
        del bpy.types.Node.perceptual_grade_next_controls
    if hasattr(bpy.types.Node, "perceptual_grade_next_stack_controls"):
        del bpy.types.Node.perceptual_grade_next_stack_controls
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    _CLASSES = ()
    _NODE_PROP = _PANEL = None


def attach_controls(node, settings=None, *, group=None):
    """Populate a node's static control group from a core settings value."""
    if group is None:
        if not hasattr(node, "perceptual_grade_next_controls"):
            return
        group = node.perceptual_grade_next_controls
    if settings is None:
        return
    group.perceptual_grade_next_ready = False
    group.exposure = settings.linear.exposure
    group.source_x, group.source_y = settings.linear.source_white_xy
    group.balance_a, group.balance_b = settings.linear.balance
    group.spread_a, group.spread_b = settings.linear.spread
    group.heading_a, group.heading_b = settings.linear.heading
    for index, value in enumerate(settings.tone.input_nits):
        setattr(group, f"input_nits_{index}", value)
    group.tone_fit = settings.tone.fit
    group.peak_nits = settings.tone.peak_nits
    for family, values in (
        ("lightness", settings.color.lightness),
        ("chroma", settings.color.chroma),
        ("adaptance", settings.color.adaptance),
        ("web_hue", settings.color.web.hue_degrees),
        ("web_chroma", settings.color.web.log_chroma),
        ("web_scale", settings.color.web.log_scale),
    ):
        for row, values_row in enumerate(values):
            for column, value in enumerate(values_row):
                setattr(group, f"{family}_{row}_{column}", value)
    group.lightness_fit = settings.color.lightness_fit
    group.chroma_fit = settings.color.chroma_fit
    group.global_gain = settings.color.global_gain
    group.adaptance_half_saturation = settings.color.adaptance_half_saturation
    group.working_space = settings.working_space
    group.perceptual_grade_next_ready = True


def attach_stack_controls(node, settings=None):
    """Copy an immutable StackSettings sequence into static RNA entries."""
    if settings is None or not hasattr(node, "perceptual_grade_next_stack_controls"):
        return
    collection = node.perceptual_grade_next_stack_controls.entries
    collection.clear()
    for entry in settings.entries:
        item = collection.add()
        item.perceptual_grade_next_ready = False
        item.direction = entry.direction.value
        item.enabled = True
        attach_controls(node, entry.settings, group=item.settings)
        item.perceptual_grade_next_ready = True
    node.perceptual_grade_next_stack_controls.perceptual_grade_next_ready = True


def stack_settings_from_controls(node):
    """Build a validated Next StackSettings snapshot from the editor node."""
    from ..perceptual_grade_next_core import Direction, StackEntry, StackSettings
    entries = []
    for item in node.perceptual_grade_next_stack_controls.entries:
        if item.enabled:
            entries.append(StackEntry(
                settings=settings_from_controls(item.settings),
                direction=Direction(item.direction),
            ))
    return StackSettings(tuple(entries))


def move_stack_entry(node, index, offset, *, mark_dirty=None):
    """Move one authored Stack entry and queue preparation for its new order."""
    entries = node.perceptual_grade_next_stack_controls.entries
    if (type(index) is not int or type(offset) is not int or abs(offset) != 1
            or not 0 <= index < len(entries)):
        return False
    destination = index + offset
    if not 0 <= destination < len(entries):
        return False
    entries.move(index, destination)
    if mark_dirty is None:
        from .updates import mark_node_dirty as mark_dirty
    if mark_dirty(node):
        return True
    entries.move(destination, index)
    return False

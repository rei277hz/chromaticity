"""Editor settings and Blender context lookup for the Gizmo."""

from dataclasses import dataclass, field

import bpy

from ...kernel.tone_ui import TONE_LEVEL_FIELDS
from . import geometry


_PER_NODE_TYPES = {"PGShaderGradePerNode", "PGCompositorGradePerNode"}
_SHARED_TYPES = {"PGShaderGrade", "PGCompositorGrade"}
HOME = (24, 24)


@dataclass
class Preferences:
    stage: str = "LINEAR"
    position: tuple[float, float] = HOME
    sizes: dict[str, float | tuple[float, float]] = field(default_factory=dict)
    tone_anchor: int = TONE_LEVEL_FIELDS.index("input_white")


def key(window, area):
    return window.as_pointer(), area.as_pointer()


def selected(space):
    tree = getattr(space, "edit_tree", None)
    node = getattr(getattr(tree, "nodes", None), "active", None)
    if node is None or not node.select:
        return None
    if (node.bl_idname in _PER_NODE_TYPES
            or node.bl_idname in _SHARED_TYPES and node.pg_grade is not None):
        return node
    return None


def binding(node):
    grade = getattr(node, "pg_grade", None)
    return node.as_pointer(), None if grade is None else grade.as_pointer()


def is_node_editor(context):
    area = context.area
    return context.window is not None and area is not None and area.type == "NODE_EDITOR"


def layout(area, region, preferences):
    right = region.width
    if area.spaces.active.show_region_ui:
        right = min((panel.x - region.x for panel in area.regions
                     if panel.type == "UI" and panel.width > 1 and panel.x >= region.x),
                    default=right)
    return geometry.layout(preferences.stage, right, region.height,
                           bpy.context.preferences.system.ui_scale,
                           preferences.position,
                           preferences.sizes.get(preferences.stage))


def view_regions(area):
    return tuple(region for region in area.regions
                 if region.type == "WINDOW" and region.width > 0 and region.height > 0)


def frame_key(scene):
    return scene.as_pointer(), scene.frame_current, scene.frame_subframe

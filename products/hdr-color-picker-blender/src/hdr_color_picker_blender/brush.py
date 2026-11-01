"""Synchronous host borrows: capture values, reacquire on confirmation."""
from dataclasses import dataclass
import math


class BrushUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class BrushIdentity:
    scene: int
    object: int
    brush: int
    color: tuple
    mode: str


def _borrow(context):
    if context.mode != 'PAINT_GREASE_PENCIL' or context.object is None:
        raise BrushUnavailable('Use a Grease Pencil Draw brush in Paint mode')
    paint = context.tool_settings.gpencil_paint
    brush = paint.brush
    if brush is None or brush.gpencil_brush_type != 'DRAW':
        raise BrushUnavailable('Select a Grease Pencil Draw brush')
    if not brush.is_editable:
        raise BrushUnavailable('The active brush is not editable')
    if brush.gpencil_settings.pin_draw_mode or brush.gpencil_settings.use_material_pin:
        raise BrushUnavailable('Unpin the brush drawing mode and material first')
    if paint.color_mode != 'VERTEXCOLOR':
        raise BrushUnavailable('Select Color Attribute in the Grease Pencil color mode')
    return paint, brush


def capture(context):
    _, brush = _borrow(context)
    return BrushIdentity(context.scene.as_pointer(), context.object.as_pointer(),
                         brush.as_pointer(), tuple(brush.color), context.mode)


def current_acescg(context):
    from mathutils import Color
    _, brush = _borrow(context)
    color = Color(brush.color).from_scene_linear_to_acescg()
    return tuple(color)


def commit(context, identity, acescg):
    """Write once after checking context and concurrent brush color changes."""
    if capture(context) != identity:
        raise BrushUnavailable('The active brush or its color changed; reopen the picker')
    from mathutils import Color
    color = Color(acescg).from_acescg_to_scene_linear()
    if not all(math.isfinite(v) and v >= 0 for v in color):
        raise BrushUnavailable('This color cannot be stored by the active working space')
    _, brush = _borrow(context)
    brush.color = color

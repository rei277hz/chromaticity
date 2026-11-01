"""Feature availability for the native Next product surface."""

AVAILABLE = {
    "grade_bake": "Shader Image, Cycles UV, and private-process Compositor Image Bake through the native Grade graph and checked gateway.",
    "stack_bake": "Shader Image, Cycles UV, and private-process Compositor Image Bake through the accepted 65^3 Stack graph.",
    "grade_bake_gateway": "Shader Image, Cycles UV, and private-process Compositor Image Bake through the native Grade graph and checked gateway.",
    "stack_bake_gateway": "Shader Image, Cycles UV, and private-process Compositor Image Bake through the accepted 65^3 Stack graph.",
    "bake_operator": "A Shader/Compositor Bake operator for still Image and Cycles UV routes, with recoverable float32 Image publication.",
    "save_render_gate": "Owned Save/Render confirmation, readiness waiting, one-shot native invocation, and reversible matching user-keymap redirects when Blender exposes both keyconfigs.",
    "scope_gizmo": "One global scope actor with foreground display and Gizmo authority.",
}

UNAVAILABLE = {
    "grade_bake_ui": "Requires a ready native Grade owner and either a direct still Shader Image, an active-object Cycles UV route, or a uniquely selected Compositor owner in the active scene.",
    "stack_bake_ui": "Requires a ready Stack owner and accepted 65^3 LUT, plus a supported Shader Image/UV route or a uniquely selected Compositor owner in the active scene.",
    "animated_grade_controls": "Static Grade and Stack controls are required in this release.",
    "per_frame_texture_bank": "Per-frame derived texture banks are deferred.",
    "exact_lut_workflow": "The separate Exact LUT workflow is deferred.",
}


def unavailable_reason(feature):
    """Return the documented reason a capability is intentionally unavailable."""
    return UNAVAILABLE.get(feature)


def available_reason(feature):
    """Return the implementation boundary for an available capability."""
    return AVAILABLE.get(feature)

"""Non-destructive Blender viewport capture and scene-linear RGB analysis.

The native draw runs synchronously on Blender's main thread. It renders only
the owned View3D region into a temporary RGBA32F offscreen buffer, copies the
readback before freeing that buffer, and never uses the shared Render Result.
"""

from dataclasses import dataclass

import numpy as np

from .scope_runtime import context_owner


MAX_SCOPE_PIXELS = 16 * 1024 * 1024
HISTOGRAM_BINS = 64
WAVEFORM_WIDTH = 128
WAVEFORM_HEIGHT = 64
VECTORSCOPE_SIZE = 64
SCOPE_PAGES = ("histogram", "waveform", "vectorscope")
_PENDING_RELEASES = []


@dataclass(frozen=True)
class RGBStatistics:
    width: int
    height: int
    sample_count: int
    minimum: tuple[float, float, float]
    mean: tuple[float, float, float]
    maximum: tuple[float, float, float]


@dataclass(frozen=True)
class ScopeAnalysis:
    """Immutable bounded charts derived from one exact viewport capture."""

    statistics: RGBStatistics
    value_minimum: float
    value_maximum: float
    histogram_bins: int
    histogram_rgb: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]
    waveform_width: int
    waveform_height: int
    waveform_rgb: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]
    vectorscope_size: int
    vectorscope_axis_limit: float
    vectorscope_rg_bg: tuple[int, ...]


def _value_range(minimum, maximum):
    if maximum > minimum:
        return minimum, maximum
    padding = max(abs(minimum) * 0.01, 0.5)
    return minimum - padding, maximum + padding


def analyze_scene_linear_rgba(values):
    """Return bounded RGB charts from a finite float32 viewport."""
    rgba = np.asarray(values, dtype=np.float32)
    if rgba.ndim != 3 or rgba.shape[-1] != 4:
        raise ValueError("Scope capture must be an H × W × RGBA float32 array")
    height, width = rgba.shape[:2]
    if min(width, height) < 1 or width * height > MAX_SCOPE_PIXELS:
        raise ValueError("Scope viewport has an invalid or oversized pixel domain")
    if not np.isfinite(rgba).all():
        raise ValueError("Scope capture contains non-finite pixels")
    rgb = rgba[..., :3]
    statistics = RGBStatistics(
        width=width,
        height=height,
        sample_count=width * height,
        minimum=tuple(float(value) for value in np.min(rgb, axis=(0, 1))),
        mean=tuple(float(value) for value in np.mean(rgb, axis=(0, 1), dtype=np.float64)),
        maximum=tuple(float(value) for value in np.max(rgb, axis=(0, 1))),
    )
    value_minimum = float(np.min(rgb))
    value_maximum = float(np.max(rgb))
    value_minimum, value_maximum = _value_range(value_minimum, value_maximum)
    rows_per_chunk = max(1, min(height, 1_048_576 // width))
    x_bins = np.minimum(
        np.arange(width, dtype=np.int64) * WAVEFORM_WIDTH // width,
        WAVEFORM_WIDTH - 1,
    )
    histogram_counts = [np.zeros(HISTOGRAM_BINS, dtype=np.int64) for _ in range(3)]
    waveform_counts = [
        np.zeros(WAVEFORM_WIDTH * WAVEFORM_HEIGHT, dtype=np.int64) for _ in range(3)
    ]
    vectorscope_counts = np.zeros(VECTORSCOPE_SIZE * VECTORSCOPE_SIZE, dtype=np.int64)
    global_minimum = min(statistics.minimum)
    global_maximum = max(statistics.maximum)
    vector_limit = max(global_maximum - global_minimum, 0.5)
    value_range = value_maximum - value_minimum
    for start in range(0, height, rows_per_chunk):
        stop = min(start + rows_per_chunk, height)
        chunk = rgb[start:stop]
        for channel in range(3):
            values_channel = chunk[..., channel]
            histogram_counts[channel] += np.histogram(
                values_channel, bins=HISTOGRAM_BINS,
                range=(value_minimum, value_maximum),
            )[0]
            y_bins = np.minimum(
                ((values_channel.astype(np.float64) - value_minimum)
                 / value_range * WAVEFORM_HEIGHT).astype(np.int64),
                WAVEFORM_HEIGHT - 1,
            )
            waveform_counts[channel] += np.bincount(
                (x_bins[None, :] * WAVEFORM_HEIGHT + y_bins).ravel(),
                minlength=WAVEFORM_WIDTH * WAVEFORM_HEIGHT,
            )

        red, green, blue = (chunk[..., channel].astype(np.float64) for channel in range(3))
        opponent_x = red - green
        opponent_y = blue - green
        vector_range = vector_limit * 2.0
        vector_x = np.clip(
            ((opponent_x + vector_limit) / vector_range * VECTORSCOPE_SIZE)
            .astype(np.int64), 0, VECTORSCOPE_SIZE - 1,
        )
        vector_y = np.clip(
            ((opponent_y + vector_limit) / vector_range * VECTORSCOPE_SIZE)
            .astype(np.int64), 0, VECTORSCOPE_SIZE - 1,
        )
        vectorscope_counts += np.bincount(
            (vector_y * VECTORSCOPE_SIZE + vector_x).ravel(),
            minlength=VECTORSCOPE_SIZE * VECTORSCOPE_SIZE,
        )
    return ScopeAnalysis(
        statistics=statistics,
        value_minimum=value_minimum,
        value_maximum=value_maximum,
        histogram_bins=HISTOGRAM_BINS,
        histogram_rgb=tuple(tuple(int(value) for value in channel) for channel in histogram_counts),
        waveform_width=WAVEFORM_WIDTH,
        waveform_height=WAVEFORM_HEIGHT,
        waveform_rgb=tuple(tuple(int(value) for value in channel) for channel in waveform_counts),
        vectorscope_size=VECTORSCOPE_SIZE,
        vectorscope_axis_limit=vector_limit,
        vectorscope_rg_bg=tuple(int(value) for value in vectorscope_counts),
    )


def _identity_parts(identity):
    try:
        tree_id, node_id = (int(value) for value in identity.removeprefix("node:").split(":"))
    except (AttributeError, TypeError, ValueError):
        return None
    return tree_id, node_id


def _active_material_uses_owner(context, target_owner):
    """Require the selected owner to feed the active material output directly."""
    identity = _identity_parts(target_owner)
    obj = getattr(context, "active_object", None)
    material = getattr(obj, "active_material", None)
    tree = getattr(material, "node_tree", None)
    if identity is None or tree is None:
        return False
    tree_id, node_id = identity
    if int(tree.as_pointer()) != tree_id:
        return False
    owner = next((node for node in tree.nodes if int(node.as_pointer()) == node_id), None)
    if owner is None or owner.get("perceptual_grade_next_backend") not in {
        "native_grade_graph", "native_stack_lut",
    }:
        return False

    active_outputs = {
        int(node.as_pointer())
        for node in tree.nodes
        if node.bl_idname == "ShaderNodeOutputMaterial"
        and getattr(node, "is_active_output", True)
    }
    outgoing = {}
    for link in tree.links:
        outgoing.setdefault(int(link.from_node.as_pointer()), set()).add(
            int(link.to_node.as_pointer())
        )
    pending = [node_id]
    visited = set()
    while pending:
        current = pending.pop()
        if current in active_outputs:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(outgoing.get(current, ()))
    return False


def _owned_view_context(bpy_module, runtime):
    from .scope_runtime import _owned_view_context

    context = _owned_view_context(bpy_module)
    if context is None or context_owner(context) != runtime.view.owner:
        raise RuntimeError("The owning 3D View is no longer available")
    if not _active_material_uses_owner(context, runtime.target_owner):
        raise RuntimeError("The selected Grade is not connected to the active material output")
    area = context.area
    region = next((item for item in area.regions if item.type == "WINDOW"), None)
    space = getattr(area.spaces, "active", None)
    region_3d = getattr(space, "region_3d", None)
    if region is None or space is None or region_3d is None:
        raise RuntimeError("The owning 3D View has no drawable window region")
    width, height = int(region.width), int(region.height)
    if min(width, height) < 1 or width * height > MAX_SCOPE_PIXELS:
        raise RuntimeError("Scope viewport has an invalid or oversized pixel domain")
    return context, area, region, space, region_3d, width, height


def _fail_and_release(runtime, ticket, diagnostic, offscreen=None, lease=None):
    runtime.fail_capture(ticket, str(diagnostic))
    if runtime.actor.state.physical == "live":
        runtime.cancel_capture(ticket)
    if offscreen is None:
        runtime.retire_capture(ticket)
        if lease is not None:
            from .native_admission import release
            release(lease)
        return
    try:
        offscreen.free()
    except Exception:
        _PENDING_RELEASES.append((runtime, ticket, offscreen, lease))
        return
    runtime.retire_capture(ticket)
    if lease is not None:
        from .native_admission import release
        release(lease)


def service_pending_releases():
    """Retire synchronous capture tickets only after GPU release succeeds."""
    remaining = []
    for runtime, ticket, offscreen, lease in _PENDING_RELEASES:
        try:
            offscreen.free()
        except Exception:
            remaining.append((runtime, ticket, offscreen, lease))
            continue
        runtime.retire_capture(ticket)
        if lease is not None:
            from .native_admission import release
            release(lease)
    _PENDING_RELEASES[:] = remaining
    return len(remaining)


def capture_viewport(runtime, *, bpy_module=None):
    """Capture and adopt one current viewport result through ScopeRuntime.

    Returns the exact applied ``ScopeVisual`` or ``None`` when no fresh demand
    exists or the submitted result became obsolete before foreground adoption.
    Native failures are attached to the request and physically retired only
    after the temporary GPU resource is released.
    """
    state = runtime.state
    if (not runtime.visible or runtime.playing or not runtime.native_ready
            or state.phase != "healthy" or state.request <= state.begun_request):
        return None
    if bpy_module is None:
        import bpy as bpy_module
    from .native_admission import acquire_reader, release

    state = runtime.state
    lease = acquire_reader(
        "scope:%s:%s:%s" % (state.generation, state.request, state.submission + 1),
    )
    if lease is None:
        return None
    try:
        ticket = runtime.begin_capture()
    except BaseException:
        release(lease)
        raise
    if ticket is None:
        release(lease)
        return None

    offscreen = None
    try:
        import gpu

        context, area, region, space, region_3d, width, height = _owned_view_context(
            bpy_module, runtime,
        )
        if not context.view_layer or not context.scene:
            raise RuntimeError("The owning viewport has no scene evaluation context")
        offscreen = gpu.types.GPUOffScreen(width, height, format="RGBA32F")
        runtime.set_capture_rendering(True)
        try:
            with offscreen.bind():
                offscreen.draw_view3d(
                    context.scene, context.view_layer, space, region,
                    region_3d.view_matrix, region_3d.window_matrix,
                    do_color_management=False, draw_background=True,
                )
                framebuffer = gpu.state.active_framebuffer_get()
                pixels = np.array(
                    framebuffer.read_color(0, 0, width, height, 4, 0, "FLOAT"),
                    dtype=np.float32, copy=True,
                )
        finally:
            runtime.set_capture_rendering(False)
        offscreen.free()
        offscreen = None
    except Exception as error:
        _fail_and_release(runtime, ticket, error, offscreen, lease)
        return None

    release(lease)

    try:
        analysis = analyze_scene_linear_rgba(pixels)
    except Exception as error:
        _fail_and_release(runtime, ticket, error, lease=lease)
        return None

    if not runtime.complete_capture(ticket):
        return None
    visual = runtime.stage_display(payload=analysis)
    if visual is None or not runtime.apply_display(visual):
        return None
    return visual


__all__ = (
    "HISTOGRAM_BINS", "MAX_SCOPE_PIXELS", "RGBStatistics", "SCOPE_PAGES",
    "ScopeAnalysis", "VECTORSCOPE_SIZE", "WAVEFORM_HEIGHT", "WAVEFORM_WIDTH",
    "analyze_scene_linear_rgba", "capture_viewport", "service_pending_releases",
)

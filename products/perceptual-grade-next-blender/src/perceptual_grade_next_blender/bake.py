"""Native-evaluator-bound Bake adapters for Perceptual Grade Next.

The adapters deliberately do not contain a second analytic Grade evaluator.
Grade capture must be supplied by Blender's installed node-tree evaluator (or a
helper hosting that exact evaluator). Stack capture uses only the accepted
65^3 ``StackLUT`` object.
"""

from dataclasses import dataclass
import hashlib

import numpy as np


def _digest(value):
    array = np.asarray(value, dtype=np.float32)
    return hashlib.sha256(array.tobytes(order="C")).hexdigest()


@dataclass(frozen=True)
class BakeSource:
    backend: str
    evaluator: str
    evaluator_id: object
    manifest_id: object
    source_revision: int
    source_id: object
    input_digest: str
    route_id: object = ""

    def __post_init__(self):
        if self.backend not in {"grade", "stack"}:
            raise ValueError("BakeSource backend must be grade or stack")
        expected = "native_grade_graph" if self.backend == "grade" else "stack_65_lut"
        if self.evaluator != expected:
            raise ValueError("BakeSource evaluator does not match its backend")
        if self.source_revision <= 0 or not self.source_id:
            raise ValueError("BakeSource must bind a frozen source identity")
        if not self.evaluator_id or not self.manifest_id:
            raise ValueError("BakeSource must bind evaluator and manifest identities")


@dataclass(frozen=True)
class BakeRoute:
    """The native route that maps a frozen source domain to evaluator output."""

    route_id: object
    domain: str
    graph: str
    evaluator: str
    source_revision: int
    source_id: object

    def __post_init__(self):
        if not self.route_id:
            raise ValueError("Bake route requires an identity")
        if self.domain not in {"image", "uv"}:
            raise ValueError("Bake route domain must be image or uv")
        if self.graph not in {"shader", "compositor"}:
            raise ValueError("Bake route graph must be shader or compositor")
        if self.evaluator not in {"native_grade_graph", "stack_65_lut"}:
            raise ValueError("Bake route must name a native final evaluator")
        if self.source_revision <= 0 or not self.source_id:
            raise ValueError("Bake route must bind a source revision")


@dataclass(frozen=True)
class BakeRouteFacts:
    """Freshly observed Blender facts used at poll/click admission."""

    engine: str
    playback: bool = False
    native_reader: bool = False
    target_conflict: bool = False
    target_float32: bool = True
    image_requires_uv: bool = False
    shader_to_rgb: bool = False
    uv_layer_present: bool = False
    native_output_available: bool = True


@dataclass(frozen=True)
class BakeRouteVerdict:
    ready: bool
    reason: str = ""


def inspect_bake_route(route: BakeRoute, facts: BakeRouteFacts) -> BakeRouteVerdict:
    """Validate route eligibility from current bounded host observations."""
    if route.domain == "uv" and route.graph == "shader" and route.evaluator not in {
        "native_grade_graph", "stack_65_lut",
    }:
        return BakeRouteVerdict(False, "Unsupported native Shader Bake evaluator")
    if route.domain == "uv" and route.graph == "compositor" and route.evaluator not in {
        "native_grade_graph", "stack_65_lut",
    }:
        return BakeRouteVerdict(False, "Unsupported native Compositor Bake evaluator")
    if facts.playback:
        return BakeRouteVerdict(False, "Stop playback before baking")
    if facts.native_reader:
        return BakeRouteVerdict(False, "Wait for native evaluation to finish")
    if facts.target_conflict:
        return BakeRouteVerdict(False, "The selected Bake Image is in use")
    if not facts.target_float32:
        return BakeRouteVerdict(False, "Bake destination must use full-precision float pixels")
    if not facts.native_output_available:
        return BakeRouteVerdict(False, "Native Grade output capture is unavailable")
    if route.domain == "image" and facts.image_requires_uv:
        return BakeRouteVerdict(False, "This Image target requires a UV Bake route")
    if route.domain == "uv":
        if not facts.uv_layer_present:
            return BakeRouteVerdict(False, "The active object has no UV map")
        if facts.engine != "CYCLES":
            return BakeRouteVerdict(False, "UV Bake requires the Cycles render engine")
    if route.graph == "shader" and facts.shader_to_rgb:
        return BakeRouteVerdict(False, "Shader to RGB is unsupported for native Bake")
    return BakeRouteVerdict(True)


@dataclass(frozen=True)
class FrozenBakeInput:
    """Immutable full-precision source samples admitted for one Bake route."""

    route: BakeRoute
    rgba: np.ndarray
    input_digest: str

    def __post_init__(self):
        values = _rgba_input(self.rgba)
        values = np.array(values, dtype=np.float32, copy=True)
        values.flags.writeable = False
        object.__setattr__(self, "rgba", values)
        if _digest(values) != self.input_digest:
            raise ValueError("Frozen Bake input digest does not match its samples")


def freeze_bake_input(route: BakeRoute, facts: BakeRouteFacts, pixels) -> FrozenBakeInput:
    """Recheck route eligibility and detach the exact source samples."""
    verdict = inspect_bake_route(route, facts)
    if not verdict.ready:
        raise RuntimeError(verdict.reason)
    values = np.array(_rgba_input(pixels), dtype=np.float32, copy=True)
    values.flags.writeable = False
    return FrozenBakeInput(route, values, _digest(values))


@dataclass(frozen=True)
class BakeResult:
    source: BakeSource
    rgba: np.ndarray
    result_id: object

    def __post_init__(self):
        values = np.asarray(self.rgba, dtype=np.float32)
        if values.shape[-1:] != (4,) or not np.isfinite(values).all():
            raise ValueError("Bake result must contain finite RGBA pixels")
        values = np.array(values, dtype=np.float32, copy=True)
        values.flags.writeable = False
        object.__setattr__(self, "rgba", values)
        if not self.result_id:
            raise ValueError("Bake result requires a committed result identity")


def _rgba_input(pixels):
    values = np.asarray(pixels, dtype=np.float32)
    if values.shape[-1:] != (4,) or not np.isfinite(values).all():
        raise ValueError("Bake input must be finite RGBA pixels")
    return values


def capture_grade(*, native_evaluator, pixels=None, frozen_input=None,
                  source_revision=None, source_id=None, evaluator_id,
                  manifest_id=None, route_id="", result_id):
    """Capture output from the installed native Grade evaluator.

    ``native_evaluator`` is an adapter around Blender's actual graph output;
    it is intentionally required and is never replaced with ``GradeModel``.
    """
    if not callable(native_evaluator):
        raise TypeError("Grade Bake requires the installed native evaluator")
    if frozen_input is not None:
        if pixels is not None:
            raise TypeError("Pass frozen_input or pixels, not both")
        route = frozen_input.route
        if source_revision is not None and source_revision != route.source_revision:
            raise ValueError("Frozen source revision does not match capture request")
        source_revision, source_id, route_id = route.source_revision, route.source_id, route.route_id
        source_pixels = np.asarray(frozen_input.rgba, dtype=np.float32)
    else:
        route = None
        source_pixels = _rgba_input(pixels)
    if source_revision is None or source_id is None:
        raise ValueError("Grade capture requires a frozen source identity")
    output = _rgba_input(native_evaluator(source_pixels.copy()))
    if (output.shape != source_pixels.shape
            and (route is None or route.domain != "uv")):
        raise ValueError("Native Grade evaluator changed the bake pixel domain")
    # Alpha belongs to the native output contract; an adapter may change it,
    # but it must return the complete RGBA result rather than an RGB surrogate.
    source = BakeSource("grade", "native_grade_graph", evaluator_id,
                        evaluator_id if manifest_id is None else manifest_id,
                        source_revision, source_id, _digest(source_pixels), route_id)
    return BakeResult(source, output, result_id)


def capture_stack(*, lut, pixels=None, frozen_input=None, source_revision=None,
                  source_id=None, evaluator_id, manifest_id=None, route_id="", result_id):
    """Capture pixels through the accepted 65^3 Stack LUT only."""
    if lut is None or not hasattr(lut, "apply") or getattr(lut, "size", None) != 65:
        raise TypeError("Stack Bake requires the accepted 65^3 Stack LUT")
    if frozen_input is not None:
        if pixels is not None:
            raise TypeError("Pass frozen_input or pixels, not both")
        route = frozen_input.route
        if source_revision is not None and source_revision != route.source_revision:
            raise ValueError("Frozen source revision does not match capture request")
        source_revision, source_id, route_id = route.source_revision, route.source_id, route.route_id
        source_pixels = np.asarray(frozen_input.rgba, dtype=np.float32)
    else:
        route = None
        source_pixels = _rgba_input(pixels)
    if source_revision is None or source_id is None:
        raise ValueError("Stack capture requires a frozen source identity")
    if route is not None and route.domain == "uv":
        apply_rgba = getattr(lut, "apply_rgba", None)
        if not callable(apply_rgba):
            raise TypeError("UV Stack Bake requires a native RGBA route evaluator")
        output = _rgba_input(apply_rgba(source_pixels.copy()))
    else:
        rgb = np.asarray(lut.apply(source_pixels[..., :3]), dtype=np.float32)
        if rgb.shape != source_pixels[..., :3].shape or not np.isfinite(rgb).all():
            raise ValueError("Stack LUT returned an invalid RGB bake domain")
        output = np.empty_like(source_pixels)
        output[..., :3] = rgb
        output[..., 3] = source_pixels[..., 3]
    source = BakeSource("stack", "stack_65_lut", evaluator_id,
                        evaluator_id if manifest_id is None else manifest_id,
                        source_revision, source_id, _digest(source_pixels), route_id)
    return BakeResult(source, output, result_id)


__all__ = (
    "BakeResult", "BakeRoute", "BakeRouteFacts", "BakeRouteVerdict", "BakeSource",
    "FrozenBakeInput", "capture_grade", "capture_stack", "freeze_bake_input",
    "inspect_bake_route",
)

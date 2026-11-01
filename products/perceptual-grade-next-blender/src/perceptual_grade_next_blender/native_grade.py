"""Build the single native Grade graph used by the Next product."""

from dataclasses import asdict, dataclass, replace
import json


BACKEND_SCHEMA = 1
BACKEND_KEY = "perceptual_grade_next_backend"
GRADE_BACKEND = "native_grade_graph"


@dataclass(frozen=True)
class NativeGrade:
    """Caller-owned native group and its prepared persistent-field controller."""

    tree: object
    controller: object
    tree_type: str
    settings: object
    quality_tier: str = "native_graph"

    @property
    def images(self):
        return self.controller.images

    @property
    def stats(self):
        return self.controller.stats


def _native_settings(settings):
    from ..perceptual_grade_next_core import GradeSettings
    from ..perceptual_grade_nodes.settings import (
        ColorSettings as NativeColorSettings,
        LinearSettings as NativeLinearSettings,
        Settings as NativeSettings,
        ToneSettings as NativeToneSettings,
        WebSettings as NativeWebSettings,
    )

    if not isinstance(settings, GradeSettings):
        raise TypeError("settings must be a Next core GradeSettings value")
    linear = NativeLinearSettings(
        exposure=settings.linear.exposure,
        source_xy=settings.linear.source_white_xy,
        balance=settings.linear.balance,
        spread=settings.linear.spread,
        heading=settings.linear.heading,
        matrix=settings.linear.matrix,
    )
    tone = NativeToneSettings(
        input_nits=settings.tone.input_nits,
        fit=settings.tone.fit,
        reference_nits=settings.tone.reference_nits,
        peak_nits=settings.tone.peak_nits,
    )
    web = NativeWebSettings(
        log_chroma=settings.color.web.log_chroma,
        hue_degrees=settings.color.web.hue_degrees,
        log_scale=settings.color.web.log_scale,
    )
    color = NativeColorSettings(
        lightness=settings.color.lightness,
        chroma=settings.color.chroma,
        adaptance=settings.color.adaptance,
        lightness_fit=settings.color.lightness_fit,
        chroma_fit=settings.color.chroma_fit,
        global_gain=settings.color.global_gain,
        adaptance_half_saturation=settings.color.adaptance_half_saturation,
        web=web,
    )
    return NativeSettings(
        linear=linear,
        tone=tone,
        space=settings.working_space,
        color=color,
    )


def build_native_grade(settings=None, *, tree_type="ShaderNodeTree", name="Perceptual Grade Next"):
    """Create a complete forward Grade graph without a separate preview LUT.

    The caller owns native installation and excludes readers for any future
    controller updates. This adapter does not claim Save/Render or Bake
    readiness; those require the project workflow's matching receipts.
    """
    settings, prepared = prepare_native_grade(settings)
    return install_native_grade(settings, prepared, tree_type=tree_type, name=name)


def prepare_native_grade(settings=None, *, previous=None):
    """Generate immutable Grade fields without touching Blender data."""
    from ..perceptual_grade_next_core import GradeSettings
    from ..perceptual_grade_nodes import prepare
    settings = GradeSettings() if settings is None else settings
    native_settings = _native_settings(settings)
    prepared = prepare(
        native_settings.linear,
        native_settings.tone,
        native_settings.space,
        color=native_settings.color,
        full_fields=True,
        previous=previous,
    )
    return settings, prepared


def install_native_grade(settings, prepared, *, tree_type="ShaderNodeTree",
                         name="Perceptual Grade Next", candidate_owner="",
                         candidate_revision=0):
    """Install a precomputed Grade candidate into Blender native datablocks."""
    from ..perceptual_grade_nodes.persistent import build_persistent
    if tree_type not in {"ShaderNodeTree", "CompositorNodeTree"}:
        raise ValueError("Next Grade requires a ShaderNodeTree or CompositorNodeTree")
    controller = build_persistent(
        prepared, tree_type=tree_type, name=name,
        candidate_owner=candidate_owner,
        candidate_revision=candidate_revision,
    )
    tree = controller.tree
    try:
        tree[BACKEND_KEY] = GRADE_BACKEND
        tree["perceptual_grade_next_schema"] = BACKEND_SCHEMA
        tree["perceptual_grade_next_quality_tier"] = "native_graph"
        tree["perceptual_grade_next_has_preview_transform"] = False
        tree["perceptual_grade_next_settings"] = json.dumps(
            asdict(settings), sort_keys=True, separators=(",", ":")
        )
        if tree.get("perceptual_grade_nodes_persistent") is not True:
            raise RuntimeError("Native Grade graph did not report persistent preparation")
        return NativeGrade(tree, controller, tree_type, settings)
    except BaseException:
        controller.dispose(unlink=True)
        raise


def apply_native_grade(native, settings, prepared, *, expected_revision):
    """Apply a verified snapshot to one fixed native tree with rollback."""
    if not isinstance(native, NativeGrade):
        raise TypeError("in-place Grade update requires its accepted NativeGrade owner")
    if prepared is None or not native.controller.valid:
        raise ValueError("accepted Grade controller is unavailable")
    tree = native.tree
    key = "perceptual_grade_next_settings"
    previous_present = key in tree
    previous = tree.get(key)
    payload = json.dumps(asdict(settings), sort_keys=True, separators=(",", ":"))
    tree[key] = payload
    try:
        receipt = native.controller.apply(prepared, expected_revision=expected_revision)
    except BaseException as error:
        try:
            if previous_present:
                tree[key] = previous
            elif key in tree:
                del tree[key]
            if ((key in tree) != previous_present
                    or (previous_present and tree.get(key) != previous)):
                raise RuntimeError("Grade settings rollback readback failed")
        except BaseException as rollback_error:
            native.controller.valid = False
            raise RuntimeError("Grade update and settings rollback failed") from rollback_error
        raise
    return replace(native, settings=settings), receipt


__all__ = ("NativeGrade", "apply_native_grade", "build_native_grade",
           "install_native_grade", "prepare_native_grade")

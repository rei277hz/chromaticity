"""Immutable data for one complete Grade parameter bundle.

The fixed layout includes Tone endpoint jets, changing scalar parameters,
and four Color field roles. Preparing it never touches Blender or grants
permission to publish it to a native reader.
"""

from dataclasses import dataclass, field
import hashlib
import json
import math
from types import MappingProxyType
from typing import Optional

import numpy as np

from .layouts import TONE_CELLS, packed_shape
from .prepare import PreparedGrade
from .stage2_bindings import PARAMETER_IMAGE, PARAMETER_ROLE
from .tables import TEXTURE_WIDTH


PARAMETER_SCHEMA = 4
PARAMETER_SHAPE = (1, TEXTURE_WIDTH, 4)
PARAMETER_CONTENT_SIGNATURE = "_perceptual_grade_parameter_content_signature"
PARAMETER_BUNDLE_SIGNATURE = "_perceptual_grade_parameter_bundle_signature"
TONE_JET_COUNT = TONE_CELLS + 1
MATRIX_RED_SLOT = TONE_JET_COUNT
MATRIX_BLUE_SLOT = MATRIX_RED_SLOT + 1
MATRIX_NEUTRAL_SLOT = MATRIX_BLUE_SLOT + 1
TONE_SCALARS_SLOT = MATRIX_NEUTRAL_SLOT + 1
TONE_DOMAIN_SLOT = TONE_SCALARS_SLOT + 1
OUTPUT_MATRIX_ROW_0_SLOT = TONE_DOMAIN_SLOT + 1
OUTPUT_MATRIX_ROW_SLOTS = tuple(range(OUTPUT_MATRIX_ROW_0_SLOT,
                                       OUTPUT_MATRIX_ROW_0_SLOT + 3))
COLOR_FLAGS_SLOT = OUTPUT_MATRIX_ROW_SLOTS[-1] + 1
WEB_FLAGS_SLOT = COLOR_FLAGS_SLOT + 1
COLOR_SCALARS_SLOT = WEB_FLAGS_SLOT + 1
COLOR_BOUNDS_SLOT = COLOR_SCALARS_SLOT + 1
ADAPTANCE_BOUNDS_SLOT = COLOR_BOUNDS_SLOT + 1
ADAPTANCE_ANCHORS_SLOT = ADAPTANCE_BOUNDS_SLOT + 1
ADAPTANCE_SUPPORT_SLOT = ADAPTANCE_ANCHORS_SLOT + 1
LAST_PARAMETER_SLOT = ADAPTANCE_SUPPORT_SLOT
PARAMETER_ROLES = ('parameter', 'color', 'web', 'web_toe', 'adaptance')
COLOR_ROLE_FIELDS = MappingProxyType({
    'color': 'coefficient_table', 'web': 'web_table',
    'web_toe': 'web_toe_table', 'adaptance': 'adaptance_table',
})
PARAMETER_ROLE_SHAPES = MappingProxyType({
    'parameter': PARAMETER_SHAPE,
    'color': packed_shape('Color coefficients', 2),
    'web': packed_shape('Web parameters', 29),
    'web_toe': packed_shape('Web toes', 1),
    'adaptance': packed_shape('Adaptance parameters', 1),
})


@dataclass(frozen=True)
class PreparedParameters:
    """An owned snapshot whose float32 storage cannot be made writable."""

    pixels: np.ndarray
    schema: int = PARAMETER_SCHEMA
    fields: object = field(default_factory=dict)

    def __post_init__(self):
        if type(self.schema) is not int or self.schema != PARAMETER_SCHEMA:
            raise ValueError("Unsupported Stage 2 parameter schema")
        data = np.asarray(self.pixels)
        if data.shape != PARAMETER_SHAPE or data.dtype != np.float32:
            raise ValueError("Stage 2 parameters require a 1 by 512 RGBA32F image")
        if not np.isfinite(data).all():
            raise ValueError("Stage 2 parameters contain nonfinite values")
        if (not np.all(data[0, :TONE_SCALARS_SLOT, 3] == 1.)
                or not np.all(data[0, TONE_SCALARS_SLOT + 1:COLOR_FLAGS_SLOT, 3] == 1.)
                or not np.all(data[0, LAST_PARAMETER_SLOT + 1:, 3] == 1.)):
            raise ValueError("Stage 2 parameter alpha lane must be one")
        if (data[0, TONE_SCALARS_SLOT, 0] < 0
                or data[0, TONE_SCALARS_SLOT, 1] <= 0
                or data[0, TONE_SCALARS_SLOT, 2] <= 0
                or data[0, TONE_SCALARS_SLOT, 3] <= 0
                or data[0, TONE_DOMAIN_SLOT, 0] <= 0):
            raise ValueError("Stage 2 Tone parameters are outside their valid domain")
        if (np.any(data[0, TONE_DOMAIN_SLOT, 1:3] != 0.)
                or np.any(data[0, LAST_PARAMETER_SLOT + 1:, :3] != 0.)):
            raise ValueError("Stage 2 parameter reserved channels must be zero")
        if not np.all(data[0, OUTPUT_MATRIX_ROW_SLOTS, 3] == 1.):
            raise ValueError("Stage 2 output matrix alpha lane must be one")
        # An ndarray with writeable=False can otherwise be made writable again
        # when it owns its allocation. Immutable bytes also isolate the caller.
        owned = np.frombuffer(data.tobytes(), dtype=np.float32).reshape(PARAMETER_SHAPE)
        object.__setattr__(self, "pixels", owned)
        fields = dict(self.fields)
        if set(fields) != set(COLOR_ROLE_FIELDS):
            raise ValueError('Grade parameter bundle must contain every Color role')
        for role, values in fields.items():
            values = np.asarray(values)
            if (values.dtype != np.float32 or values.shape != PARAMETER_ROLE_SHAPES[role]
                    or not np.isfinite(values).all()):
                raise ValueError('Invalid Grade parameter field: ' + role)
            fields[role] = np.frombuffer(values.tobytes(), dtype=np.float32).reshape(values.shape)
        object.__setattr__(self, 'fields', MappingProxyType(fields))

    @property
    def roles(self):
        return MappingProxyType({'parameter': self.pixels, **self.fields})


def parameter_content_signature(pixels) -> str:
    """Identify the exact RGBA32F bytes stored in a parameter bank."""
    data = np.ascontiguousarray(pixels, dtype=np.float32)
    if data.shape not in PARAMETER_ROLE_SHAPES.values():
        raise ValueError("Grade content signatures require a declared role image")
    return hashlib.sha256(data.tobytes()).hexdigest()


def parameter_bundle_signature(role_signatures) -> str:
    """Correlate every role's content receipt in the fixed bundle order."""
    signatures = dict(role_signatures)
    if (set(signatures) != set(PARAMETER_ROLES)
            or any(not isinstance(value, str) or len(value) != 64
                   or any(character not in '0123456789abcdef' for character in value)
                   for value in signatures.values())):
        raise ValueError('Grade bundle receipts require every role content signature')
    payload = tuple((role, signatures[role]) for role in PARAMETER_ROLES)
    return hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode('ascii')).hexdigest()


def parameter_bank_images(image):
    """Resolve a persistent bank's five fixed Image identities."""
    from .stage2_bindings import PARAMETER_ROLE_BINDING
    return {'parameter': image, **{
        role: image.get(PARAMETER_ROLE_BINDING + role) for role in COLOR_ROLE_FIELDS
    }}


def set_parameter_bundle_signature(primary, signatures):
    """Stamp a staged bundle without changing its persistent Image bindings."""
    signatures = dict(signatures)
    receipt = parameter_bundle_signature(signatures)
    images = parameter_bank_images(primary)
    if (any(image is None for image in images.values())
            or len({image.as_pointer() for image in images.values()}) != len(PARAMETER_ROLES)
            or any(image.get(PARAMETER_IMAGE) != PARAMETER_SCHEMA
                   or image.get(PARAMETER_ROLE) != role
                   or tuple(image.size) != (PARAMETER_ROLE_SHAPES[role][1],
                                            PARAMETER_ROLE_SHAPES[role][0])
                   or image.get(PARAMETER_CONTENT_SIGNATURE) != signatures[role]
                   for role, image in images.items())):
        raise ValueError('Grade bundle contents do not match their role receipts')
    for image in images.values():
        image[PARAMETER_BUNDLE_SIGNATURE] = receipt
    return receipt


def _validated_parameter_bundles(primaries) -> Optional[tuple[dict[str, object], ...]]:
    try:
        pointers = set()
        bundles = []
        for primary in primaries:
            images = parameter_bank_images(primary)
            signatures = {}
            for role, image in images.items():
                pointer = image.as_pointer()
                height, width, _channels = PARAMETER_ROLE_SHAPES[role]
                if (not pointer or pointer in pointers
                        or image.get(PARAMETER_IMAGE) != PARAMETER_SCHEMA
                        or image.get(PARAMETER_ROLE) != role
                        or tuple(image.size) != (width, height)):
                    return None
                pointers.add(pointer)
                signatures[role] = image.get(PARAMETER_CONTENT_SIGNATURE)
            receipt = parameter_bundle_signature(signatures)
            if any(image.get(PARAMETER_BUNDLE_SIGNATURE) != receipt
                   for image in images.values()):
                return None
            bundles.append(images)
        return tuple(bundles)
    except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def parameter_bundle_receipt_matches(primary) -> bool:
    """Check correlated role receipts using metadata only, without pixel reads."""
    return _validated_parameter_bundles((primary,)) is not None


def parameter_bank_pair_images(banks) -> Optional[tuple[dict[str, object], ...]]:
    """Resolve two banks only when their receipts match and all role images are distinct."""
    try:
        if len(banks) != 2:
            return None
        return _validated_parameter_bundles(banks)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def bind_parameter_bank(images, signatures=None):
    """Attach immutable role identities and schema markers to a complete bank."""
    from .stage2_bindings import PARAMETER_IMAGE, PARAMETER_ROLE, PARAMETER_ROLE_BINDING
    images = dict(images)
    if set(images) != set(PARAMETER_ROLES) or any(value is None for value in images.values()):
        raise ValueError('Grade parameter banks require all five role images')
    if signatures is not None:
        signatures = dict(signatures)
        parameter_bundle_signature(signatures)
    if len({value.as_pointer() for value in images.values()}) != len(PARAMETER_ROLES):
        raise ValueError('Grade parameter bank roles require distinct Image identities')
    primary = images['parameter']
    for role, image in images.items():
        image[PARAMETER_IMAGE] = PARAMETER_SCHEMA
        image[PARAMETER_ROLE] = role
        if signatures is not None:
            image[PARAMETER_CONTENT_SIGNATURE] = signatures[role]
        if role != 'parameter':
            primary[PARAMETER_ROLE_BINDING + role] = image
    if signatures is None:
        signatures = {role: image.get(PARAMETER_CONTENT_SIGNATURE)
                      for role, image in images.items()}
    set_parameter_bundle_signature(primary, signatures)
    return primary


def parameter_image_matches(image, content_signature=None, *, bundle=True) -> bool:
    """Check a packed helper against its exact stored RGBA32F content receipt."""
    try:
        if (image.as_pointer() == 0 or image.is_dirty or image.packed_file is None
                or (content_signature is None
                    and image.get(PARAMETER_CONTENT_SIGNATURE) is None)):
            return False
        from .stage2_bindings import PARAMETER_IMAGE, PARAMETER_ROLE
        role = image.get(PARAMETER_ROLE, 'parameter')
        shape = PARAMETER_ROLE_SHAPES.get(role)
        if (shape is None or image.get(PARAMETER_IMAGE) != PARAMETER_SCHEMA
                or tuple(image.size) != (shape[1], shape[0])):
            return False
        pixels = np.empty(shape, dtype=np.float32)
        image.pixels.foreach_get(pixels.ravel())
        actual = parameter_content_signature(pixels)
        expected = (image.get(PARAMETER_CONTENT_SIGNATURE)
                    if content_signature is None else content_signature)
        if actual != expected:
            return False
        if bundle and role == 'parameter':
            images = parameter_bank_images(image)
            return (parameter_bundle_receipt_matches(image)
                    and all(parameter_image_matches(value, bundle=False)
                            for value in images.values()))
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def prepare_parameters(prepared: PreparedGrade) -> PreparedParameters:
    """Pack the complete snapshot without changing its numerical semantics."""
    if not isinstance(prepared, PreparedGrade):
        raise TypeError("Stage 2 parameters require a PreparedGrade")
    table = prepared.table
    if (table is None or table.cells != TONE_CELLS
            or table.pixels.shape != PARAMETER_SHAPE
            or table.jets.shape != (TONE_JET_COUNT, 3)
            or table.jets.dtype != np.float32):
        raise ValueError("Stage 2 parameters require the complete 256-cell Tone table")
    if (not np.isfinite(table.jets).all()
            or not np.array_equal(table.pixels[0, :TONE_JET_COUNT, :3], table.jets)):
        raise ValueError("Stage 2 Tone pixels and endpoint jets disagree")
    matrix = np.asarray(prepared.linear_to_cones)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("Stage 2 parameters require a finite 3 by 3 cone matrix")
    boundary = prepared.boundary
    if boundary is None:
        from .boundary import prepare_boundary
        boundary = prepare_boundary(prepared.fl, prepared.aw, prepared.gamma)
    output_matrix = np.asarray(prepared.from_cones) @ np.asarray(boundary.inverse)
    if output_matrix.shape != (3, 3) or not np.isfinite(output_matrix).all():
        raise ValueError("Stage 2 parameters require a finite output conversion matrix")

    pixels = np.zeros(PARAMETER_SHAPE, dtype=np.float32)
    pixels[..., 3] = 1.
    try:
        with np.errstate(over="raise", invalid="raise"):
            pixels[0, :TONE_JET_COUNT, :3] = table.jets
            pixels[0, MATRIX_RED_SLOT, :3] = matrix[:, 0]
            pixels[0, MATRIX_BLUE_SLOT, :3] = matrix[:, 2]
            # Match Graph.matrix's neutral-preserving arithmetic exactly.
            pixels[0, MATRIX_NEUTRAL_SLOT, :3] = tuple(
                math.fsum(float(value) for value in row) for row in matrix
            )
            tone = prepared.tone
            pixels[0, TONE_SCALARS_SLOT] = tone.black, tone.span, tone.slope, tone.high
            pixels[0, TONE_DOMAIN_SLOT, 0] = table.domain
            pixels[0, OUTPUT_MATRIX_ROW_SLOTS, :3] = output_matrix
            color = prepared.color
            if not color.full_fields:
                from .color_prepare import prepare_color
                color = prepare_color(color.settings, prepared.tone, full_fields=True,
                                      previous=color)
            settings = color.settings
            pixels[0, COLOR_FLAGS_SLOT] = (color.lightness_active, color.chroma_active,
                                           color.adaptance_active, color.web_active)
            pixels[0, WEB_FLAGS_SLOT] = tuple(
                any(value != 0 for row in getattr(settings.web, name) for value in row)
                for name in ('hue_degrees', 'log_chroma', 'log_scale')
            ) + (color.active,)
            pixels[0, COLOR_SCALARS_SLOT] = (settings.global_gain,
                settings.adaptance_half_saturation, color.high, color.coefficient_table.domain)
            pixels[0, COLOR_BOUNDS_SLOT] = (
                settings.global_gain + max(max(abs(row[0]), abs(row[1])) + math.hypot(*row[2:])
                                           for row in settings.chroma),
                max(0., math.log(2.) * max(value for row in settings.web.log_chroma for value in row) - math.log(.9)),
                max(0., math.log(2.) * max(value for row in settings.web.log_scale for value in row) - math.log(.9)),
                float(abs(color.adaptance_table.pixels[..., :3]).max()),
            )
            pixels[0, ADAPTANCE_BOUNDS_SLOT] = (
                max(0., float(color.adaptance_table.pixels[..., :3].max())),
                max(0., float(color.adaptance_table.pixels[..., 3].max())), 0., 0.,
            )
            pixels[0, ADAPTANCE_ANCHORS_SLOT] = color.anchors
            pixels[0, ADAPTANCE_SUPPORT_SLOT] = tuple(
                any(value != 0. for value in row) for row in settings.adaptance)
    except (FloatingPointError, OverflowError) as error:
        raise ValueError("Stage 2 parameters are not representable as float32") from error
    return PreparedParameters(pixels, fields={
        role: getattr(color, name).pixels for role, name in COLOR_ROLE_FIELDS.items()
    })

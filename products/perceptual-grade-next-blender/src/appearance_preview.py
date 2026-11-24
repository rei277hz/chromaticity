"""Bounded GPU evaluation of sampled final Grade appearance for the Tone scope."""

from collections import OrderedDict
from collections.abc import Mapping
import threading

import numpy as np

from .kernel.boundary import prepare_boundary
from .kernel.node_templates import shader_source
from .kernel.prepare import GAMMA, viewing
from .kernel.stage2_parameters import (
    PARAMETER_CONTENT_SIGNATURE,
    PARAMETER_ROLE_SHAPES,
    PARAMETER_ROLES,
    parameter_bundle_receipt_matches,
    parameter_bank_images,
    parameter_content_signature,
)


MAX_SAMPLES = 4096
_LOCAL_SIZE = 64
_ROLE_SAMPLERS = {
    "parameter": "grade_parameters",
    "web": "grade_web",
    "web_toe": "grade_web_toe",
    "adaptance": "grade_adaptance",
}


class AppearancePreview:
    """Evaluate a deterministic alpha-preserving sample with generated Grade GLSL.

    ``evaluate`` must run on Blender's main thread because it reads packed
    parameter Images and dispatches through Blender's GPU API.
    """

    def __init__(self):
        self._main_thread = threading.main_thread()
        self._gpu = None
        self._shader = None
        self._boundary_texture = None
        self._input_texture = None
        self._input_receipt = None
        self._sample_count = 0
        self._output_texture = None
        self._output_size = 0
        self._role_textures = {}
        self._verified_role_textures = {role: OrderedDict() for role in PARAMETER_ROLES}

    def warm(self):
        """Compile the generated appearance entry point and boundary sampler."""
        self._require_main_thread()
        if self._shader is not None:
            return

        import gpu

        gpu.init()
        if not gpu.capabilities.compute_shader_support_get():
            raise RuntimeError("Appearance preview requires GPU compute shader support")
        fl, aw = viewing(203.)
        boundary = prepare_boundary(fl, aw, GAMMA)
        source = shader_source(boundary=boundary)
        info = gpu.types.GPUShaderCreateInfo()
        info.local_group_size(_LOCAL_SIZE, 1, 1)
        samplers = ("input_values", "boundary_seed", *_ROLE_SAMPLERS.values())
        for binding, name in enumerate(samplers):
            info.sampler(binding, "FLOAT_2D", name)
        info.image(0, "RGBA32F", "FLOAT_2D", "output_values", qualifiers={"WRITE"})
        info.push_constant("INT", "sample_count")
        info.push_constant("INT", "grade_index")
        info.compute_source("#define SCOPE_PREVIEW\n" + source + _COMPUTE_SOURCE)
        shader = gpu.shader.create_from_info(info)
        boundary_texture = _texture(gpu, boundary.pixels)
        self._gpu = gpu
        self._shader = shader
        self._boundary_texture = boundary_texture

    def evaluate(self, rgba, role_images, *, input_receipt):
        """Return a ``(1, N, 4)`` array of ``(J_A, a, b, alpha)`` samples.

        ``role_images`` must contain the four Image identities from one
        receipt-validated active parameter bank. The caller remains responsible
        for checking that the bank belongs to the current Grade revision and
        that ``input_receipt`` identifies the supplied immutable samples.
        """
        self._require_main_thread()
        if not isinstance(input_receipt, str) or not input_receipt:
            raise ValueError("Appearance preview needs an input capture receipt")
        roles = _validated_roles(role_images)
        self.warm()
        self._bind_role_textures(roles)
        self._bind_input(rgba, input_receipt)
        count = self._sample_count
        self._ensure_output(count)

        shader = self._shader
        shader.bind()
        shader.uniform_sampler("input_values", self._input_texture)
        shader.uniform_sampler("boundary_seed", self._boundary_texture)
        for role, sampler in _ROLE_SAMPLERS.items():
            shader.uniform_sampler(sampler, self._role_textures[role][2])
        shader.uniform_int("sample_count", count)
        shader.uniform_int("grade_index", 0)
        shader.image("output_values", self._output_texture)
        self._gpu.compute.dispatch(shader, (count + _LOCAL_SIZE - 1) // _LOCAL_SIZE, 1, 1)

        pixels = np.asarray(self._output_texture.read(), dtype=np.float32).reshape(1, count, 4)
        if not np.isfinite(pixels).all():
            raise ArithmeticError("Appearance preview produced nonfinite samples")
        pixels.setflags(write=False)
        return pixels

    def _bind_role_textures(self, roles):
        for role in PARAMETER_ROLES:
            image = roles[role]
            signature = image.get(PARAMETER_CONTENT_SIGNATURE)
            pointer = int(image.as_pointer())
            previous = self._role_textures.get(role)
            receipt = pointer, signature
            verified = self._verified_role_textures[role]
            texture = verified.get(receipt)
            if texture is not None:
                verified.move_to_end(receipt)
            else:
                shape = PARAMETER_ROLE_SHAPES[role]
                pixels = np.empty(shape, dtype=np.float32)
                image.pixels.foreach_get(pixels.reshape(-1))
                actual = parameter_content_signature(pixels)
                if actual != signature or not np.isfinite(pixels).all():
                    raise ValueError(
                        "Appearance preview parameter content failed its receipt: " + role
                    )
                texture = (previous[2] if previous is not None and previous[0] == signature
                           else _texture(self._gpu, pixels))
                verified[receipt] = texture
                if len(verified) > 2:
                    verified.popitem(last=False)

            self._role_textures[role] = signature, pointer, texture

    def _bind_input(self, rgba, receipt):
        if self._input_receipt == receipt:
            return
        pixels = _sample_subset(rgba)
        self._input_texture = _texture(self._gpu, pixels)
        self._sample_count = pixels.shape[1]
        self._input_receipt = receipt

    def _ensure_output(self, sample_count):
        if self._output_texture is not None and self._output_size == sample_count:
            return
        self._output_texture = self._gpu.types.GPUTexture(
            (sample_count, 1), format="RGBA32F",
        )
        self._output_size = sample_count

    def _require_main_thread(self):
        if threading.current_thread() is not self._main_thread:
            raise RuntimeError("Appearance preview must run on Blender's main thread")

    def close(self):
        """Release local GPU and input resources on Blender's main thread."""
        self._require_main_thread()
        self._role_textures.clear()
        for receipts in self._verified_role_textures.values():
            receipts.clear()
        self._input_texture = self._output_texture = self._boundary_texture = None
        self._input_receipt = None
        self._sample_count = self._output_size = 0
        self._shader = self._gpu = None


def _validated_roles(role_images):
    if not isinstance(role_images, Mapping) or set(role_images) != set(PARAMETER_ROLES):
        raise ValueError("Appearance preview needs a complete Grade parameter bank")
    primary = role_images["parameter"]
    if not parameter_bundle_receipt_matches(primary):
        raise ValueError("Appearance preview parameter-bank receipt is invalid")
    roles = parameter_bank_images(primary)
    for role, image in roles.items():
        if (image != role_images[role] or image.is_dirty or image.packed_file is None
                or not image.is_float or image.channels != 4
                or image.colorspace_settings.name != "Non-Color"
                or image.alpha_mode != "CHANNEL_PACKED"):
            raise ValueError("Appearance preview parameter Image is invalid: " + role)
    return roles


def _texture(gpu, pixels):
    height, width, _channels = pixels.shape
    texture = gpu.types.GPUTexture(
        (width, height), format="RGBA32F",
        data=gpu.types.Buffer("FLOAT", pixels.shape, pixels),
    )
    texture.filter_mode(False)
    return texture


def _sample_subset(rgba):
    values = np.asarray(rgba, dtype=np.float32)
    if values.ndim != 3 or values.shape[-1] != 4 or min(values.shape[:2]) < 1:
        raise ValueError("Appearance preview input must be a nonempty RGBA image")
    flat = values.reshape(-1, 4)
    if len(flat) > MAX_SAMPLES:
        edges = np.arange(MAX_SAMPLES + 1, dtype=np.int64) * len(flat) // MAX_SAMPLES
        # Within each stratum, vary the offset to avoid sampling a fixed column pattern.
        indices = np.random.default_rng(0).integers(edges[:-1], edges[1:])
        flat = flat[indices]
    return np.ascontiguousarray(flat.reshape(1, -1, 4))


_COMPUTE_SOURCE = r"""
void main() {
    int index = int(gl_GlobalInvocationID.x);
    if (index >= sample_count) return;
    vec4 source = texelFetch(input_values, ivec2(index, 0), 0);
    if (any(isnan(source)) || any(isinf(source)) || source.a <= 0.0) {
        imageStore(output_values, ivec2(index, 0), vec4(0.0));
        return;
    }
    vec4 mapped = grade_scope_appearance(source.rgb);
    if (any(isnan(mapped)) || any(isinf(mapped)) || mapped.w <= 0.0) {
        imageStore(output_values, ivec2(index, 0), vec4(0.0));
        return;
    }
    imageStore(output_values, ivec2(index, 0),
               vec4(clamp(mapped.xyz, vec3(-65504.0), vec3(65504.0)), min(source.a, 1.0)));
}
"""


__all__ = ("AppearancePreview", "MAX_SAMPLES")

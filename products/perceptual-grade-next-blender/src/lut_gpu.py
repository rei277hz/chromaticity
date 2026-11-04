"""GPU-only ordered Stage 1/2 Stack baking in the private Blender helper."""

from dataclasses import asdict, dataclass
import hashlib
import json
from threading import current_thread, main_thread
import time
from typing import Optional

import numpy as np

from .kernel import lut
from .lut_shader import grade_source


DISPATCH_SAMPLES = 4096
_LOCAL_SIZE = 64
_PARAMETER_WIDTH = 512


@dataclass(frozen=True)
class PreparedStack:
    settings: tuple
    space: str
    cube: object
    diagnostics: Optional[object] = None


def _signature(settings, space):
    payload = ("stage-1-2-guarded-stack-v1", space, tuple(asdict(item) for item in settings))
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf8")).hexdigest()


def _parameters(prepared, from_lut):
    pixels = np.zeros((max(1, len(prepared)), _PARAMETER_WIDTH, 4), dtype=np.float32)
    for ordinal, grade in enumerate(prepared):
        if grade.table is None or grade.table.cells != 256 or grade.boundary is None:
            raise ValueError("Stack grading requires a complete Stage 2 preparation")
        pixels[ordinal, :3, :3] = grade.linear_to_cones @ from_lut
        tone = grade.tone
        pixels[ordinal, 3] = (tone.black, tone.span, tone.slope, tone.high)
        pixels[ordinal, 4, 0] = grade.table.domain
        pixels[ordinal, 5:262, :3] = grade.table.jets
    if not np.isfinite(pixels).all():
        raise ValueError("Stack grading parameters must be finite float32")
    return pixels


class StackGPUBackend:
    """Reuse programs; keep all textures and passes on the helper main thread."""

    def __init__(self):
        self._gpu = None
        self._shader = None
        self._edge_shader = None
        self._source = None

    def create_prepared(self, prepared, working_space, progressive, *, settings=()):
        _require_main_thread()
        prepared = tuple(prepared)
        if any(item.space != working_space for item in prepared):
            raise ValueError("Stack preparation belongs to another working space")
        boundary = prepared[0].boundary if prepared else None
        self._ensure_shader(boundary)
        return StackLUTBaker(self, prepared, working_space, progressive, tuple(settings))

    def _ensure_shader(self, boundary):
        import gpu

        _require_main_thread()
        gpu.init()
        if not gpu.capabilities.compute_shader_support_get():
            raise RuntimeError("Grade Stack LUT baking requires GPU compute shaders")
        source = grade_source(boundary) if boundary is not None else "vec3 grade_value(vec3 value) { return value; }"
        if self._source == source and self._shader is not None:
            return
        info = gpu.types.GPUShaderCreateInfo()
        info.local_group_size(_LOCAL_SIZE, 1, 1)
        for binding, name in enumerate(("axis_values", "input_values", "grade_parameters", "boundary_seed")):
            info.sampler(binding, "FLOAT_2D", name)
        info.image(0, "RGBA32F", "FLOAT_2D", "output_pixels", qualifiers={"WRITE"})
        for name in ("cube_size", "sample_start", "sample_count", "output_width", "grade_index", "first_grade"):
            info.push_constant("INT", name)
        info.compute_source(source + _VALUE_SHADER)
        self._shader = gpu.shader.create_from_info(info)
        if self._edge_shader is None:
            edge = gpu.types.GPUShaderCreateInfo()
            edge.local_group_size(_LOCAL_SIZE, 1, 1)
            edge.sampler(0, "FLOAT_2D", "input_values")
            edge.image(0, "RGBA32F", "FLOAT_2D", "output_pixels", qualifiers={"WRITE"})
            for name in ("cube_size", "sample_start", "sample_count", "output_width"):
                edge.push_constant("INT", name)
            edge.compute_source(_EDGE_SHADER)
            self._edge_shader = gpu.shader.create_from_info(edge)
        self._gpu = gpu
        self._source = source

    def close(self):
        _require_main_thread()
        self._shader = self._edge_shader = self._gpu = self._source = None


class StackLUTBaker:
    """Dispatch ordered complete grades, then derive actual grid edge vectors."""

    def __init__(self, backend, prepared, space, progressive, settings):
        self.backend = backend
        self.prepared = prepared
        self.to_lut, self.from_lut = lut.basis(space)
        self.signature = _signature(settings, space)
        self.space = space
        self.settings = settings
        self.progressive = bool(progressive)
        self.size = lut.PREVIEW_SIZE if progressive else lut.SIZE
        self.cursor = self._grade = 0
        self._edges = False
        self._output = self._values = self._axis_texture = None
        self._parameter_texture = self._boundary_texture = None
        self._readback_pending = self._closed = False
        self.texture_allocation_seconds = {"preview": 0.0, "full": 0.0}
        self.readback_seconds = {"preview": 0.0, "full": 0.0}
        self._create_resources()
        self._create_phase()

    @property
    def sample_count(self):
        return self.size**3

    def _texture(self, pixels):
        pixels = np.asarray(pixels, dtype=np.float32)
        height, width, _ = pixels.shape
        return self.backend._gpu.types.GPUTexture(
            (width, height), format="RGBA32F",
            data=self.backend._gpu.types.Buffer("FLOAT", pixels.shape, pixels),
        )

    def _create_resources(self):
        self._parameter_texture = self._texture(_parameters(self.prepared, self.from_lut))
        pixels = self.prepared[0].boundary.pixels if self.prepared else np.zeros((2, 2, 4), np.float32)
        self._boundary_texture = self._texture(pixels)

    def _create_phase(self):
        phase = "preview" if self.size == lut.PREVIEW_SIZE else "full"
        started = time.perf_counter()
        gpu = self.backend._gpu
        coordinates = lut.axis(lut.SIZE)
        if self.size == lut.PREVIEW_SIZE:
            coordinates = coordinates[::2]
        coordinates = np.asarray(coordinates, dtype=np.float32)
        self._axis_texture = gpu.types.GPUTexture(
            (self.size, 1), format="R32F",
            data=gpu.types.Buffer("FLOAT", (1, self.size), coordinates.reshape(1, self.size)),
        )
        height = (self.sample_count + lut.ATLAS_WIDTH - 1) // lut.ATLAS_WIDTH
        self._values = tuple(gpu.types.GPUTexture((lut.ATLAS_WIDTH, height), format="RGBA32F")
                             for _ in range(2))
        self._output = gpu.types.GPUTexture(
            (lut.ATLAS_WIDTH, lut.atlas_height(self.size)), format="RGBA32F",
        )
        self.texture_allocation_seconds[phase] += time.perf_counter() - started

    def advance(self):
        _require_main_thread()
        if self._closed:
            raise RuntimeError("Grade Stack LUT baker is closed")
        if self._readback_pending:
            cube = self._readback()
            if self.progressive:
                self.progressive = False
                self.size = lut.SIZE
                self.cursor = self._grade = 0
                self._edges = self._readback_pending = False
                self._create_phase()
                return "preview", PreparedStack(self.settings, self.space, cube)
            return "full", PreparedStack(self.settings, self.space, cube)

        count = min(DISPATCH_SAMPLES, self.sample_count - self.cursor)
        gpu = self.backend._gpu
        shader = self.backend._edge_shader if self._edges else self.backend._shader
        shader.bind()
        if self._edges:
            shader.uniform_sampler("input_values", self._values[(self._grade - 1) % 2])
            shader.image("output_pixels", self._output)
        else:
            shader.uniform_sampler("axis_values", self._axis_texture)
            shader.uniform_sampler("input_values", self._values[(self._grade + 1) % 2])
            shader.uniform_sampler("grade_parameters", self._parameter_texture)
            shader.uniform_sampler("boundary_seed", self._boundary_texture)
            if self.prepared:
                shader.uniform_int("grade_index", self._grade)
            shader.uniform_int("first_grade", int(self._grade == 0))
            shader.image("output_pixels", self._values[self._grade % 2])
        for name, value in (("cube_size", self.size), ("sample_start", self.cursor),
                            ("sample_count", count), ("output_width", lut.ATLAS_WIDTH)):
            shader.uniform_int(name, value)
        gpu.compute.dispatch(shader, (count + _LOCAL_SIZE - 1) // _LOCAL_SIZE, 1, 1)
        self.cursor += count
        if self.cursor == self.sample_count:
            self.cursor = 0
            if self._edges:
                self._readback_pending = True
            else:
                self._grade += 1
                self._edges = self._grade == max(1, len(self.prepared))
        return None

    def _readback(self):
        phase = "preview" if self.size == lut.PREVIEW_SIZE else "full"
        started = time.perf_counter()
        count, size = self.sample_count, self.size
        pixels = np.asarray(self._output.read(), dtype=np.float32).reshape(-1, 4)
        fields = pixels[:4 * count, :3].copy().reshape(4, size, size, size, 3)
        if not np.isfinite(fields).all():
            raise ArithmeticError("Stack GPU baking produced nonfinite values")
        for array in (fields, self.to_lut, self.from_lut):
            array.flags.writeable = False
        cube = lut.LinearCube(fields[0], fields[1:], self.signature, self.space,
                              self.to_lut, self.from_lut, size)
        self._output = self._values = self._axis_texture = None
        self.readback_seconds[phase] += time.perf_counter() - started
        return cube

    def close(self):
        _require_main_thread()
        self._output = self._values = self._axis_texture = None
        self._parameter_texture = self._boundary_texture = None
        self._closed = True


def _require_main_thread():
    if current_thread() is not main_thread():
        raise RuntimeError("Grade Stack GPU baking requires the current Blender process's main thread")


_VALUE_SHADER = r"""
void main() {
    int local_index = int(gl_GlobalInvocationID.x);
    if (local_index >= sample_count) return;
    int index = sample_start + local_index;
    ivec2 pixel = ivec2(index % output_width, index / output_width);
    vec3 value;
    if (first_grade != 0) {
        int blue = index % cube_size;
        int green = (index / cube_size) % cube_size;
        int red = index / (cube_size * cube_size);
        value = vec3(texelFetch(axis_values, ivec2(red, 0), 0).r,
                     texelFetch(axis_values, ivec2(green, 0), 0).r,
                     texelFetch(axis_values, ivec2(blue, 0), 0).r);
    } else {
        value = texelFetch(input_values, pixel, 0).xyz;
    }
    if (grade_index >= 0) value = grade_value(value);
    imageStore(output_pixels, pixel, vec4(value, 1.0));
}
"""

_EDGE_SHADER = r"""
vec3 value_at(int index) {
    return texelFetch(input_values, ivec2(index % output_width, index / output_width), 0).xyz;
}
void store_at(int index, vec3 value) {
    imageStore(output_pixels, ivec2(index % output_width, index / output_width), vec4(value, 1.0));
}
void main() {
    int local_index = int(gl_GlobalInvocationID.x);
    if (local_index >= sample_count) return;
    int index = sample_start + local_index;
    int count = cube_size * cube_size * cube_size;
    int blue = index % cube_size;
    int green = (index / cube_size) % cube_size;
    int red = index / (cube_size * cube_size);
    vec3 value = value_at(index);
    store_at(index, value);
    store_at(count + index, red < cube_size - 1 ? value_at(index + cube_size * cube_size) - value : vec3(0.0));
    store_at(2 * count + index, green < cube_size - 1 ? value_at(index + cube_size) - value : vec3(0.0));
    store_at(3 * count + index, blue < cube_size - 1 ? value_at(index + 1) - value : vec3(0.0));
}
"""


__all__ = ("DISPATCH_SAMPLES", "PreparedStack", "StackGPUBackend", "StackLUTBaker")

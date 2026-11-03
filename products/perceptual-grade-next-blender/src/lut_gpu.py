"""Blender main-thread GPU baker for forward Stage 1 Grade Stack LUTs."""

from dataclasses import dataclass
from threading import current_thread, main_thread

import numpy as np

from .kernel import lut
from .kernel.prepare import prepare_linear


DISPATCH_SAMPLES = 4096
_LOCAL_SIZE = 64


@dataclass(frozen=True)
class PreparedStack:
    settings: tuple
    space: str
    cube: object


class StackGPUBackend:
    """Own one immutable shader program and serialize its active bake on host."""

    def __init__(self):
        self._gpu = None
        self._shader = None

    def create_job(self, settings, working_space, progressive):
        _require_main_thread()
        matrices = tuple(prepare_linear(item, working_space).rgb_matrix
                         for item in settings)
        return self.create_matrices(
            matrices, working_space, progressive, settings=settings,
        )

    def create_matrices(self, matrices, working_space, progressive, *, settings=()):
        _require_main_thread()
        lut_matrix, to_lut, from_lut, signature = lut._stack_matrix(
            matrices, working_space
        )
        self._ensure_shader()
        return StackLUTBaker(
            self, lut_matrix, to_lut, from_lut, signature, working_space,
            progressive, tuple(settings),
        )

    def _ensure_shader(self):
        if self._shader is not None:
            return
        import gpu

        _require_main_thread()
        gpu.init()
        if not gpu.capabilities.compute_shader_support_get():
            raise RuntimeError("Grade Stack LUT baking requires GPU compute shaders")
        info = gpu.types.GPUShaderCreateInfo()
        info.local_group_size(_LOCAL_SIZE, 1, 1)
        info.sampler(0, "FLOAT_2D", "axis_values")
        info.image(0, "RGBA32F", "FLOAT_2D", "output_pixels",
                   qualifiers={"WRITE"})
        for name in ("matrix_r", "matrix_g", "matrix_b"):
            info.push_constant("VEC3", name)
        for name in ("cube_size", "sample_start", "sample_count", "output_width"):
            info.push_constant("INT", name)
        info.compute_source(_SHADER_SOURCE)
        self._gpu = gpu
        self._shader = gpu.shader.create_from_info(info)

    def close(self):
        _require_main_thread()
        self._shader = None
        self._gpu = None


class StackLUTBaker:
    """Incrementally dispatch one cube on the main thread, then read its texture."""

    def __init__(self, backend, matrix, to_lut, from_lut, signature, space,
                 progressive, settings):
        _require_main_thread()
        self.backend = backend
        self.matrix = np.asarray(matrix, dtype=np.float32)
        if self.matrix.shape != (3, 3) or not np.isfinite(self.matrix).all():
            raise ValueError("Composed Stage 1 matrix must be finite 3x3")
        self.to_lut = to_lut
        self.from_lut = from_lut
        self.signature = signature
        self.space = space
        self.settings = settings
        self.progressive = bool(progressive)
        self.size = lut.PREVIEW_SIZE if self.progressive else lut.SIZE
        self.cursor = 0
        self._output = None
        self._axis_texture = None
        self._readback_pending = False
        self._closed = False
        self._create_phase()

    @property
    def sample_count(self):
        return self.size**3

    def _create_phase(self):
        gpu = self.backend._gpu
        coordinates = lut.axis(lut.SIZE)
        if self.size == lut.PREVIEW_SIZE:
            coordinates = coordinates[::2]
        coordinates = np.asarray(coordinates, dtype=np.float32)
        axis_buffer = gpu.types.Buffer(
            "FLOAT", (1, self.size), coordinates.reshape(1, self.size),
        )
        self._axis_texture = gpu.types.GPUTexture(
            (self.size, 1), format="R32F", data=axis_buffer,
        )
        self._output = gpu.types.GPUTexture(
            (lut.ATLAS_WIDTH, lut.atlas_height(self.size)), format="RGBA32F",
        )

    def advance(self):
        """Dispatch one 4096-sample batch or collect a completed quality result."""
        _require_main_thread()
        if self._closed:
            raise RuntimeError("Grade Stack LUT baker is closed")
        if self._readback_pending:
            cube = self._readback()
            if self.progressive:
                self.progressive = False
                self.size = lut.SIZE
                self.cursor = 0
                self._readback_pending = False
                self._create_phase()
                return "preview", PreparedStack(self.settings, self.space, cube)
            return "full", PreparedStack(self.settings, self.space, cube)

        count = min(DISPATCH_SAMPLES, self.sample_count - self.cursor)
        shader = self.backend._shader
        shader.bind()
        shader.uniform_sampler("axis_values", self._axis_texture)
        shader.image("output_pixels", self._output)
        shader.uniform_float("matrix_r", self.matrix[:, 0])
        shader.uniform_float("matrix_g", self.matrix[:, 1])
        shader.uniform_float("matrix_b", self.matrix[:, 2])
        shader.uniform_int("cube_size", self.size)
        shader.uniform_int("sample_start", self.cursor)
        shader.uniform_int("sample_count", count)
        shader.uniform_int("output_width", lut.ATLAS_WIDTH)
        self.backend._gpu.compute.dispatch(
            shader, (count + _LOCAL_SIZE - 1) // _LOCAL_SIZE, 1, 1,
        )
        self.cursor += count
        if self.cursor == self.sample_count:
            self._readback_pending = True
        return None

    def _readback(self):
        _require_main_thread()
        count = self.sample_count
        size = self.size
        height = lut.atlas_height(size)
        pixels = np.asarray(self._output.read(), dtype=np.float32).reshape(
            height, lut.ATLAS_WIDTH, 4,
        ).reshape(-1, 4)
        fields = pixels[:4 * count, :3].copy().reshape(4, size, size, size, 3)
        values = fields[0]
        edges = fields[1:]
        values.flags.writeable = False
        edges.flags.writeable = False
        self.to_lut.flags.writeable = False
        self.from_lut.flags.writeable = False
        cube = lut.LinearCube(
            values, edges, self.signature, self.space,
            self.to_lut, self.from_lut, size,
        )
        self._output = None
        self._axis_texture = None
        return cube

    def close(self):
        _require_main_thread()
        self._output = None
        self._axis_texture = None
        self._closed = True


def _require_main_thread():
    if current_thread() is not main_thread():
        raise RuntimeError("Grade Stack GPU baking requires Blender's main thread")


_SHADER_SOURCE = r"""
float axis_at(int index) {
    return texelFetch(axis_values, ivec2(index, 0), 0).r;
}

void store_value(int index, vec3 value) {
    int row = index / output_width;
    int column = index - row * output_width;
    imageStore(output_pixels, ivec2(column, row), vec4(value, 1.0));
}

void main() {
    int local_index = int(gl_GlobalInvocationID.x);
    if (local_index >= sample_count) return;

    int index = sample_start + local_index;
    int plane_size = cube_size * cube_size * cube_size;
    int b = index % cube_size;
    int g = (index / cube_size) % cube_size;
    int r = index / (cube_size * cube_size);
    float red = axis_at(r);
    float green = axis_at(g);
    float blue = axis_at(b);
    store_value(index, matrix_r * red + matrix_g * green + matrix_b * blue);

    vec3 edge_r = r < cube_size - 1
        ? matrix_r * (axis_at(r + 1) - red) : vec3(0.0);
    vec3 edge_g = g < cube_size - 1
        ? matrix_g * (axis_at(g + 1) - green) : vec3(0.0);
    vec3 edge_b = b < cube_size - 1
        ? matrix_b * (axis_at(b + 1) - blue) : vec3(0.0);
    store_value(plane_size + index, edge_r);
    store_value(2 * plane_size + index, edge_g);
    store_value(3 * plane_size + index, edge_b);
}
"""


__all__ = ("DISPATCH_SAMPLES", "PreparedStack", "StackGPUBackend", "StackLUTBaker")

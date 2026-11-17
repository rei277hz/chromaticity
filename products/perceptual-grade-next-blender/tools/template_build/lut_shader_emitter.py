"""Emit the shared native full Grade equations as compute GLSL."""

from numbers import Real
from types import SimpleNamespace

from .graph import Graph
from .guard_graph import output_guard
from .parameter_color import ParameterColorGraph
from ..kernel.prepare import prepare
from ..kernel.stage2_parameters import (
    MATRIX_BLUE_SLOT, MATRIX_NEUTRAL_SLOT, MATRIX_RED_SLOT,
    PARAMETER_ROLE_SHAPES, TONE_DOMAIN_SLOT, TONE_SCALARS_SLOT,
)


class _Expression:
    __slots__ = ("code", "kind")

    def __init__(self, code, kind="float"):
        self.code = code
        self.kind = kind


def _code(value):
    if isinstance(value, _Expression):
        return value.code
    if isinstance(value, Real):
        return repr(float(value))
    return "vec3(" + ", ".join(_code(item) for item in value) + ")"


class _ComputeParameters:
    """Read the same role/scalar ABI as a native Grade without image banking."""

    def __init__(self, graph):
        self.graph = graph
        black, span, slope, high = self.scalar(TONE_SCALARS_SLOT)
        self.tone = SimpleNamespace(active=True, black=black, span=span,
                                    slope=slope, high=high)
        self.domain = self.scalar(TONE_DOMAIN_SLOT)[0]

    def scalar(self, slot):
        value = self.graph._emit("vec4", f"texelFetch(grade_parameters, ivec2({slot}, grade_index), 0)")
        return tuple(self.graph._emit("float", f"{value.code}.{channel}")
                     for channel in "xyzw")

    def sample(self, slot):
        values = self.scalar(slot)
        return self.graph.vector(values[:3]), values[3]

    def matrix(self, value):
        graph = self.graph
        red, green, blue = graph.split(value)
        red_delta = graph.vscale(self.sample(MATRIX_RED_SLOT)[0], graph.sub(red, green))
        blue_delta = graph.vscale(self.sample(MATRIX_BLUE_SLOT)[0], graph.sub(blue, green))
        neutral = graph.vscale(self.sample(MATRIX_NEUTRAL_SLOT)[0], green)
        return graph.vadd(graph.vadd(red_delta, blue_delta), neutral)

    def sample_field(self, role, table, coordinate, row):
        graph = self.graph
        height, width, _ = PARAMETER_ROLE_SHAPES[role]
        sampler = {"color": "grade_color", "web": "grade_web",
                   "web_toe": "grade_web_toe", "adaptance": "grade_adaptance"}[role]
        if table.segments > 1:
            segment = graph.minimum(table.segments-1,
                graph.op('FLOOR',graph.div(coordinate,table.segment_cells)))
            coordinate = graph.sub(coordinate,graph.mul(segment,table.segment_cells))
            row = graph.madd(row,table.segments,segment)
        position = graph._emit("float", f"clamp({_code(coordinate)}, 0.0, {float(width-1)})")
        left = graph._emit("int", f"min(int(floor({position.code})), {width-2})")
        fraction = graph._emit("float", f"{position.code} - float({left.code})")
        y = graph._emit("int", f"grade_index * {height} + int(clamp(floor({_code(row)} + 0.5), 0.0, {float(height-1)}))")
        value = graph._emit("vec4", (
            f"mix(texelFetch({sampler}, ivec2({left.code}, {y.code}), 0), "
            f"texelFetch({sampler}, ivec2({left.code} + 1, {y.code}), 0), {fraction.code})"))
        return tuple(graph._emit("float", f"{value.code}.{channel}")
                     for channel in "xyzw")

    def output_matrix(self, value):
        # Every grade exports directly into the fixed AP1 LUT basis. The final
        # native Stack lookup owns the separate conversion back to scene RGB.
        return value


class _ComputeGraph(ParameterColorGraph, Graph):
    """Compose Graph's existing equations with a GLSL arithmetic adapter."""

    def __init__(self, boundary):
        self.tree = SimpleNamespace(bl_idname="ShaderNodeTree")
        self.cache = {}
        self.boundary = boundary
        self.lines = []
        self._expressions = {}
        self.parameters = _ComputeParameters(self)
        # Only fixed layouts and field identities are needed from preparation;
        # all authored choices are read from each grade's uploaded role texels.
        defaults = prepare(boundary=boundary,full_fields=True)
        self.prepared = SimpleNamespace(
            fl=boundary.fl,
            aw=boundary.aw,
            gamma=boundary.gamma,
            # Stack values stay in the fixed AP1 LUT basis between grades.
            from_cones=boundary.matrix,
            boundary=boundary,
            tone=self.parameters.tone,
            table=SimpleNamespace(cells=256, domain=self.parameters.domain),
            color=defaults.color,
        )

    def _emit(self, kind, expression):
        key = kind, expression
        if key not in self._expressions:
            result = _Expression(f"v{len(self.lines)}", kind)
            self.lines.append(f"    {kind} {result.code} = {expression};")
            self._expressions[key] = result
        return self._expressions[key]

    def op(self, operation, *values):
        a = tuple(_code(value) for value in values) + ("", "", "")
        expression = {
            "ADD": f"({a[0]} + {a[1]})",
            "SUBTRACT": f"({a[0]} - {a[1]})",
            "MULTIPLY": f"({a[0]} * {a[1]})",
            "MULTIPLY_ADD": f"({a[0]} * {a[1]} + {a[2]})",
            "DIVIDE": f"safe_divide({a[0]}, {a[1]})",
            "ABSOLUTE": f"abs({a[0]})",
            "MAXIMUM": f"max({a[0]}, {a[1]})",
            "MINIMUM": f"min({a[0]}, {a[1]})",
            "SQRT": f"sqrt(max(0.0, {a[0]}))",
            "POWER": f"pow(max(0.0, {a[0]}), {a[1]})",
            "FLOOR": f"floor({a[0]})",
            "FLOORED_MODULO": f"mod({a[0]}, {a[1]})",
            "SINE": f"sin({a[0]})",
            "COSINE": f"cos({a[0]})",
            "SIGN": f"sign({a[0]})",
            "LESS_THAN": f"float({a[0]} < {a[1]})",
            "COMPARE": f"float(abs({a[0]} - {a[1]}) <= {a[2]})",
            "ARCTAN2": f"atan({a[0]}, {a[1]})",
            "EXPONENT": f"exp({a[0]})",
            "LOGARITHM": f"(log({a[0]}) / log({a[1]}))",
        }[operation]
        return self._emit("float", expression)

    def vop(self, operation, *values):
        a = tuple(_code(value) for value in values) + ("", "", "")
        expression = {
            "ADD": f"({a[0]} + {a[1]})",
            "SUBTRACT": f"({a[0]} - {a[1]})",
            "MULTIPLY": f"({a[0]} * {a[1]})",
            "MULTIPLY_ADD": f"({a[0]} * {a[1]} + {a[2]})",
            "DIVIDE": f"safe_divide({a[0]}, {a[1]})",
            "SCALE": f"({a[0]} * {a[1]})",
            "ABSOLUTE": f"abs({a[0]})",
            "MINIMUM": f"min({a[0]}, {a[1]})",
            "MAXIMUM": f"max({a[0]}, {a[1]})",
            "POWER": f"pow(max(vec3(0.0), {a[0]}), {a[1]})",
            "SIGN": f"sign({a[0]})",
        }[operation]
        return self._emit("vec3", expression)

    def select(self, condition, yes, no):
        if isinstance(condition,Real):
            return yes if condition else no
        return self._emit("float", f"({_code(condition)} > 0.0 ? {_code(yes)} : {_code(no)})")

    safe_select = select

    def vselect(self, condition, yes, no):
        if isinstance(condition,Real):
            return yes if condition else no
        return self._emit("vec3", f"({_code(condition)} > 0.0 ? {_code(yes)} : {_code(no)})")

    def vselect_components(self, condition, yes, no):
        return self._emit("vec3", f"mix({_code(no)}, {_code(yes)}, greaterThan({_code(condition)}, vec3(0.0)))")

    def clamp(self, value, low=0.0, high=1.0):
        return self._emit("float", f"clamp({_code(value)}, {_code(low)}, {_code(high)})")

    def vector(self, values):
        return self._emit("vec3", _code(values))

    def split(self, value):
        code = _code(value)
        return tuple(self._emit("float", f"({code}).{channel}") for channel in "xyz")

    def dot(self, value, row):
        return self._emit("float", f"dot({_code(value)}, {_code(row)})")

    def matrix(self, value, rows):
        return self.vector(tuple(self.dot(value, row) for row in rows))

    def sample_texture(self, pixels, u=None, v=None, *, pixel_coordinates=None, **_kwargs):
        if pixels is not self.boundary.pixels or pixel_coordinates is None:
            raise ValueError("The Grade shader only samples its prepared boundary seed here")
        x, y = pixel_coordinates
        value = self._emit("vec3", f"sample_boundary(vec2({_code(x)}, {_code(y)}))")
        return value, 1.0

    def _sample(self, index):
        code = _code(index)
        cell = self._emit("int", f"int(clamp(floor({code}), 0.0, 255.0))")
        left = self._emit("vec3", f"texelFetch(grade_parameters, ivec2({cell.code}, grade_index), 0).xyz")
        right = self._emit("vec3", f"texelFetch(grade_parameters, ivec2(1 + {cell.code}, grade_index), 0).xyz")
        return left, right

    def lookup(self, z):
        p = self.mul(self.minimum(1.0, self.maximum(0.0, z)), 256.0)
        cell = self.minimum(255.0, self.op("FLOOR", p))
        u = self.sub(p, cell)
        v = self.sub(1.0, u)
        u2, v2 = self.mul(u, u), self.mul(v, v)
        u3, v3 = self.mul(u2, u), self.mul(v2, v)
        blend = self.mul(u3, self.madd(u, self.madd(6.0, u, -15.0), 10.0))
        left, right = self._sample(cell)
        return self.add(
            self.dot(left, (self.sub(1.0, blend), self.mul(self.mul(u, v3), self.madd(3.0, u, 1.0)), self.mul(.5, self.mul(u2, v3)))),
            self.dot(right, (blend, self.mul(self.mul(u3, v), self.madd(3.0, u, -4.0)), self.mul(.5, self.mul(u3, v2)))),
        )


def grade_source(boundary):
    """Create the complete Grade shader using shared build-only equations."""
    graph = _ComputeGraph(boundary)
    input_color = _Expression("input_value", "vec3")
    cones = graph.parameters.matrix(input_color)
    toned = graph.tone(graph.encode_cones(cones))
    guarded = output_guard(graph, graph.color_and_guard(toned))
    native = guarded.native_color
    body = "\n".join((
        _PREAMBLE,
        "vec3 grade_value(vec3 input_value) {",
        *graph.lines,
        f"    return {_code(native)};",
        "}",
    ))
    return body


_PREAMBLE = r"""
float safe_divide(float a, float b) { return b == 0.0 ? 0.0 : a / b; }
vec3 safe_divide(vec3 a, vec3 b) {
    return vec3(safe_divide(a.x, b.x), safe_divide(a.y, b.y), safe_divide(a.z, b.z));
}
vec3 sample_boundary(vec2 coordinates) {
    ivec2 maximum = textureSize(boundary_seed, 0) - ivec2(1);
    vec2 position = clamp(coordinates, vec2(0.0), vec2(maximum));
    ivec2 low = min(ivec2(floor(position)), maximum - ivec2(1));
    vec2 fraction = position - vec2(low);
    vec3 bottom = mix(texelFetch(boundary_seed, low, 0).xyz,
                      texelFetch(boundary_seed, low + ivec2(1, 0), 0).xyz, fraction.x);
    vec3 top = mix(texelFetch(boundary_seed, low + ivec2(0, 1), 0).xyz,
                   texelFetch(boundary_seed, low + ivec2(1, 1), 0).xyz, fraction.x);
    return mix(bottom, top, fraction.y);
}
"""


__all__ = ("grade_source",)

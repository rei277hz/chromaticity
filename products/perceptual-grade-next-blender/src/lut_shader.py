"""Emit the current native Stage 2 and guard equations as compute GLSL."""

from numbers import Real
from types import MethodType, SimpleNamespace

from .kernel.graph import Graph
from .kernel.guard_graph import GuardedSockets, hk_guard, output_guard


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


class _ComputeGraph:
    """Compose Graph's existing equations with a GLSL arithmetic adapter."""

    _STAGES = (
        "add", "sub", "mul", "madd", "div", "abs", "sqrt", "power",
        "minimum", "maximum", "lt", "sign", "hypot", "saturate",
        "vscale", "vadd", "vsub", "vmul", "vdiv", "_eccentricity",
        "encode_cones", "remap", "tone",
    )

    def __init__(self, boundary):
        self.tree = SimpleNamespace(bl_idname="ShaderNodeTree")
        self.cache = {}
        self.boundary = boundary
        self.lines = []
        self._expressions = {}
        self.prepared = SimpleNamespace(
            fl=boundary.fl,
            aw=boundary.aw,
            gamma=boundary.gamma,
            # Stack values stay in the fixed AP1 LUT basis between grades.
            from_cones=boundary.matrix,
            boundary=boundary,
            tone=SimpleNamespace(
                active=True,
                black=self.parameter(3, "x"),
                span=self.parameter(3, "y"),
                slope=self.parameter(3, "z"),
                high=self.parameter(3, "w"),
            ),
            table=SimpleNamespace(cells=256, domain=self.parameter(4, "x")),
        )

    def __getattr__(self, name):
        if name in self._STAGES:
            return MethodType(getattr(Graph, name), self)
        raise AttributeError(name)

    def _emit(self, kind, expression):
        key = kind, expression
        if key not in self._expressions:
            result = _Expression(f"v{len(self.lines)}", kind)
            self.lines.append(f"    {kind} {result.code} = {expression};")
            self._expressions[key] = result
        return self._expressions[key]

    def parameter(self, field, channel=None):
        value = f"texelFetch(grade_parameters, ivec2({field}, grade_index), 0)"
        return self._emit("float", f"{value}.{channel}") if channel else self._emit("vec3", f"{value}.xyz")

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
        return self._emit("float", f"mix({_code(no)}, {_code(yes)}, clamp({_code(condition)}, 0.0, 1.0))")

    safe_select = select

    def vselect(self, condition, yes, no):
        return self._emit("vec3", f"mix({_code(no)}, {_code(yes)}, clamp({_code(condition)}, 0.0, 1.0))")

    def vselect_components(self, condition, yes, no):
        return self._emit("vec3", f"mix({_code(no)}, {_code(yes)}, clamp({_code(condition)}, vec3(0.0), vec3(1.0)))")

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
            raise ValueError("The Stage 2 shader only samples its prepared boundary seed")
        x, y = pixel_coordinates
        value = self._emit("vec3", f"sample_boundary(vec2({_code(x)}, {_code(y)}))")
        return value, 1.0

    def _sample(self, index):
        code = _code(index)
        cell = self._emit("int", f"int(clamp(floor({code}), 0.0, 255.0))")
        left = self._emit("vec3", f"texelFetch(grade_parameters, ivec2(5 + {cell.code}, grade_index), 0).xyz")
        right = self._emit("vec3", f"texelFetch(grade_parameters, ivec2(6 + {cell.code}, grade_index), 0).xyz")
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
    """Create Stage 2 shader using native Graph and guard implementations."""
    graph = _ComputeGraph(boundary)
    rows = tuple(graph.parameter(row) for row in range(3))
    input_color = _Expression("input_value", "vec3")
    cones = graph.matrix(input_color, rows)
    toned = graph.tone(graph.encode_cones(cones))
    energy = toned.energy
    state = GuardedSockets(graph, toned.H, toned.a, toned.b, energy, energy,
                           chroma_value=toned.chroma)
    guarded = output_guard(graph, hk_guard(graph, state))
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

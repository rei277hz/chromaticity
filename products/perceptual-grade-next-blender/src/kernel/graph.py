"""Synchronous, caller-owned native Shader/Compositor grading graphs.

Blender evaluates every pixel. Python prepares constants and coefficient images
only. Importing this module does not import bpy or register any Blender state.
"""
from dataclasses import dataclass
from functools import cached_property
import math
from numbers import Real
from .color_graph import ColorGraph
from .layouts import LAYOUT_SCHEMA
from .color_prepare import _validate_color_schema


FLOAT_MAX = 3.4028234663852886e38
RESPONSE_LIMIT = 400.0
SAFE_RESPONSE = 399.999969482421875  # The float32 predecessor of 400.
TREE_TYPES = ("ShaderNodeTree", "CompositorNodeTree")
INVERSE_OPPONENT = ((460/1403, 451/1403, 288/1403),
                    (460/1403, -891/1403, -261/1403),
                    (460/1403, -220/1403, -6300/1403))


def _socket(value):
    return hasattr(value, "as_pointer")


def _key(value):
    return value.as_pointer() if _socket(value) else ("constant", float(value))


@dataclass(frozen=True)
class AppearanceSockets:
    """A raw signed appearance handoff, with lazily emitted public sockets.

    J_A is the achromatic coordinate. H is signed H-K lightness, and ``energy``
    is J_A*abs(J_A). Retained response coordinates let Tone decode without a
    second hue computation. Read any desired properties before finalizing the
    caller's node graph; unused intermediate outputs consume no nodes.
    """
    graph: object
    J_A: object
    raw_a: object
    raw_b: object
    achromatic: object
    factor: object
    chroma: object

    @cached_property
    def a(self):
        return self.graph.mul(self.raw_a, self.factor)

    @cached_property
    def b(self):
        return self.graph.mul(self.raw_b, self.factor)

    @cached_property
    def magnitude(self):
        g = self.graph
        return g.sqrt(g.madd(self.J_A, self.J_A, g.mul(66, self.chroma)))

    @cached_property
    def H(self):
        g = self.graph
        base = g.sqrt(g.mul(66, self.chroma))
        return g.select(g.lt(self.J_A, 0), g.sub(g.mul(2, base), self.magnitude), self.magnitude)

    @cached_property
    def energy(self):
        return self.graph.mul(self.J_A, self.graph.abs(self.J_A))

    @cached_property
    def q(self):
        return self.graph.vector((self.H, self.a, self.b))

    @property
    def ja(self):
        return self.J_A


@dataclass(frozen=True)
class DecodeSockets:
    color: object
    valid: object
    pole_margin: object
    saturated: object = 0.


@dataclass(frozen=True)
class GraphStats:
    top_level_nodes: int
    expanded_nodes: int
    leaf_nodes: int
    texture_nodes: int
    texture_bytes: int


def count_nodes(tree, images=()):
    """Count every group occurrence, including group wrappers and interface nodes."""
    def visit(current, ancestors):
        pointer = current.as_pointer()
        if pointer in ancestors:
            raise ValueError("Recursive node groups cannot be counted")
        total = leaves = textures = 0
        for node in current.nodes:
            total += 1
            child = getattr(node, "node_tree", None)
            if child is not None:
                a, b, c = visit(child, ancestors | {pointer})
                total += a
                leaves += b
                textures += c
            else:
                leaves += 1
            textures += node.bl_idname in {"ShaderNodeTexImage", "CompositorNodeMapUV"}
        return total, leaves, textures
    expanded, leaves, textures = visit(tree, set())
    byte_count = sum(int(image.size[0]) * int(image.size[1]) * 16 for image in images)
    return GraphStats(len(tree.nodes), expanded, leaves, textures, byte_count)


@dataclass(frozen=True)
class BuiltGrade:
    tree: object
    images: tuple
    helper_groups: tuple
    prepared: object
    stats: GraphStats

    def dispose(self, *, unlink=False):
        """Release owned resources; reject live group users unless explicitly asked."""
        import bpy
        if self.tree.users and not unlink:
            raise ValueError("The grade group still has users")
        bpy.data.node_groups.remove(self.tree, do_unlink=unlink)
        for tree in self.helper_groups:
            if tree.users == 0:
                bpy.data.node_groups.remove(tree)
        for image in self.images:
            if image.users == 0:
                bpy.data.images.remove(image)


class Graph(ColorGraph):
    """Append reusable stages to a caller-supplied native tree.

    The caller owns ``tree`` and any images in ``images``. A Graph has no global
    cache and never changes existing nodes. Callers may connect the intermediate
    AppearanceSockets to a later Color stage without a round trip through RGB.
    """
    def __init__(self, tree, prepared):
        if tree.bl_idname not in TREE_TYPES:
            raise ValueError("Expected a ShaderNodeTree or CompositorNodeTree")
        self.tree = tree
        self.prepared = prepared
        self.cache = {}
        self.images = []
        self.helper_groups = []
        # Composed by the product's fixed Stage 2 builder. Generic immutable
        # graphs retain their existing constants and numerical optimizations.
        self.parameters = None

    def connect(self, value, target):
        if _socket(value):
            self.tree.links.new(value, target)
        else:
            target.default_value = value

    def node(self, kind, label=None):
        node = self.tree.nodes.new(kind)
        node.hide = True
        if label:
            node.label = label
        index = len(self.tree.nodes)
        node.location = ((index % 16) * 150, -(index // 16) * 90)
        return node

    def op(self, operation, *values):
        key = (operation, *map(_key, values))
        if key in self.cache:
            return self.cache[key]
        if all(isinstance(v, Real) for v in values):
            a = tuple(float(v) for v in values)
            constants = {
                "ADD": lambda: a[0] + a[1], "SUBTRACT": lambda: a[0] - a[1],
                "MULTIPLY": lambda: a[0] * a[1],
                "MULTIPLY_ADD": lambda: a[0] * a[1] + a[2],
                "DIVIDE": lambda: a[0] / a[1] if a[1] else 0.0,
                "ABSOLUTE": lambda: abs(a[0]), "MAXIMUM": lambda: max(a),
                "MINIMUM": lambda: min(a), "SQRT": lambda: math.sqrt(max(0, a[0])),
                "POWER": lambda: a[0] ** a[1], "FLOOR": lambda: math.floor(a[0]),
                "SIGN": lambda: float((a[0] > 0) - (a[0] < 0)),
                "LESS_THAN": lambda: float(a[0] < a[1]),
                "COMPARE": lambda: float(abs(a[0] - a[1]) <= a[2]),
                "SINE": lambda: math.sin(a[0]), "COSINE": lambda: math.cos(a[0]),
                "ARCTAN2": lambda: math.atan2(a[0], a[1]),
                "FLOORED_MODULO": lambda: a[0] % a[1] if a[1] else 0.,
                "EXPONENT": lambda: math.exp(a[0]),
                "LOGARITHM": lambda: math.log(a[0], a[1]) if a[0] > 0 and a[1] > 0 and a[1] != 1 else 0.,
            }
            if operation in constants:
                return constants[operation]()
        node = self.node("ShaderNodeMath", operation.title())
        node.operation = operation
        node.use_clamp = False
        for socket, value in zip(node.inputs, values):
            self.connect(value, socket)
        self.cache[key] = node.outputs[0]
        return node.outputs[0]

    def add(self, a, b):
        if isinstance(a, Real) and a == 0: return b
        if isinstance(b, Real) and b == 0: return a
        return self.op("ADD", a, b)

    def sub(self, a, b):
        if isinstance(b, Real) and b == 0: return a
        return self.op("SUBTRACT", a, b)

    def mul(self, a, b):
        if isinstance(a, Real):
            if a == 0: return 0.0
            if a == 1: return b
        if isinstance(b, Real):
            if b == 0: return 0.0
            if b == 1: return a
        return self.op("MULTIPLY", a, b)

    def madd(self, a, b, c):
        if isinstance(c, Real) and c == 0: return self.mul(a, b)
        return self.op("MULTIPLY_ADD", a, b, c)

    def div(self, a, b): return self.op("DIVIDE", a, b)
    def abs(self, a): return self.op("ABSOLUTE", a)
    def sqrt(self, a): return self.op("SQRT", a)
    def power(self, a, b): return self.op("POWER", a, b)
    def minimum(self, a, b): return self.op("MINIMUM", a, b)
    def maximum(self, a, b): return self.op("MAXIMUM", a, b)
    def lt(self, a, b): return self.op("LESS_THAN", a, b)
    def sign(self, a): return self.op("SIGN", a)

    def clamp(self, value, low=0., high=1.):
        if all(isinstance(v, Real) for v in (value, low, high)):
            return min(high, max(low, value))
        key = ('clamp', _key(value), _key(low), _key(high))
        if key not in self.cache:
            node = self.node('ShaderNodeClamp', 'Bound finite representation')
            node.clamp_type = 'MINMAX'
            for socket, item in zip(node.inputs, (value, low, high)):
                self.connect(item, socket)
            self.cache[key] = node.outputs[0]
        return self.cache[key]

    def select(self, condition, yes, no):
        if isinstance(condition, Real): return yes if condition else no
        key = ('select', _key(condition), _key(yes), _key(no))
        if key not in self.cache:
            node = self.node('ShaderNodeMix', 'Select scalar')
            node.data_type = 'FLOAT'
            node.clamp_factor = True
            self.connect(condition, node.inputs[0])
            self.connect(no, node.inputs[2])
            self.connect(yes, node.inputs[3])
            self.cache[key] = node.outputs[0]
        return self.cache[key]

    def safe_select(self, condition, yes, no):
        """Boolean selection without an overflowing difference of alternatives."""
        return self.select(condition, yes, no)

    def hypot(self, a, b):
        """A scaled norm; the squared operands never exceed one."""
        scale = self.maximum(self.abs(a), self.abs(b))
        x, y = self.div(a, scale), self.div(b, scale)
        return self.mul(scale, self.sqrt(self.madd(x, x, self.mul(y, y))))

    def saturate(self, value, inherited_flag=0.):
        """Signed representational saturation, distinct from decode validity.

        Callers must avoid undefined operations before this point. Infinities
        from an otherwise defined overflowing multiply/power are clamped before
        subsequent arithmetic; NaN is never silently assigned a replacement.
        """
        if isinstance(value, Real):
            if math.isnan(value):
                raise ValueError('NaN in native constant preparation')
            flag = float(abs(value) > FLOAT_MAX)
            return min(FLOAT_MAX, max(-FLOAT_MAX, value)), (flag if inherited_flag == 0. else self.maximum(inherited_flag, flag))
        flag = self.lt(FLOAT_MAX, self.abs(value))
        return (self.clamp(value, -FLOAT_MAX, FLOAT_MAX),
                flag if isinstance(inherited_flag, Real) and inherited_flag == 0. else self.maximum(inherited_flag, flag))

    def sat_mul(self, a, b, inherited_flag=0.):
        return self.saturate(self.mul(a, b), inherited_flag)

    def sat_add(self, a, b, inherited_flag=0.):
        return self.saturate(self.add(a, b), inherited_flag)

    def sat_div(self, a, b, inherited_flag=0.):
        """Finite quotient; a nonzero/zero limit saturates rather than returning zero."""
        value, flag = self.saturate(self.div(a, b), inherited_flag)
        zero_denominator = self.sub(1., self.lt(0., self.abs(b)))
        overflow = self.mul(zero_denominator, self.lt(0., self.abs(a)))
        return (self.safe_select(overflow, self.mul(self.sign(a), FLOAT_MAX), value),
                self.maximum(flag, overflow))

    def sat_power(self, a, b, inherited_flag=0.):
        if isinstance(a, Real) and isinstance(b, Real):
            try:
                value = math.pow(float(a), float(b))
            except OverflowError:
                odd = float(b).is_integer() and int(b) % 2 != 0
                value = -math.inf if a < 0 and odd else math.inf
            return self.saturate(value, inherited_flag)
        return self.saturate(self.power(a, b), inherited_flag)

    def vop(self, operation, *values):
        """Cached native vector arithmetic, including scalar SCALE operands."""
        def key(value):
            return _key(value) if _socket(value) or isinstance(value, Real) else tuple(map(float, value))
        cache_key = ('vector_math', operation, *map(key, values))
        if cache_key not in self.cache:
            node = self.node('ShaderNodeVectorMath', operation.title())
            node.operation = operation
            for index, value in enumerate(values):
                socket = node.inputs['Scale'] if operation == 'SCALE' and index == 1 else node.inputs[index]
                self.connect(value, socket)
            self.cache[cache_key] = node.outputs['Value' if operation in {'LENGTH', 'DISTANCE', 'DOT_PRODUCT'} else 'Vector']
        return self.cache[cache_key]

    def vscale(self, vector, scalar):
        if isinstance(scalar, Real) and scalar == 1.: return vector
        return self.vop('SCALE', vector, scalar)

    def vadd(self, a, b): return self.vop('ADD', a, b)
    def vsub(self, a, b): return self.vop('SUBTRACT', a, b)
    def vmul(self, a, b): return self.vop('MULTIPLY', a, b)
    def vdiv(self, a, b): return self.vop('DIVIDE', a, b)

    def vselect(self, condition, yes, no):
        if isinstance(condition, Real): return yes if condition else no
        def key(v): return _key(v) if _socket(v) else tuple(map(float, v))
        cache_key = ('vector_select', _key(condition), key(yes), key(no))
        if cache_key not in self.cache:
            node = self.node('ShaderNodeMix', 'Select vector')
            node.data_type = 'VECTOR'
            node.factor_mode = 'UNIFORM'
            node.clamp_factor = True
            self.connect(condition, node.inputs[0])
            self.connect(no, node.inputs[4])
            self.connect(yes, node.inputs[5])
            self.cache[cache_key] = node.outputs[1]
        return self.cache[cache_key]

    def vselect_components(self, condition, yes, no):
        """Select independent vector lanes with one native Mix node."""
        def key(v): return _key(v) if _socket(v) else tuple(map(float, v))
        cache_key = ('vector_select_components', key(condition), key(yes), key(no))
        if cache_key not in self.cache:
            node = self.node('ShaderNodeMix', 'Select vector components')
            node.data_type = 'VECTOR'
            node.factor_mode = 'NON_UNIFORM'
            node.clamp_factor = True
            self.connect(condition, node.inputs[1])
            self.connect(no, node.inputs[4])
            self.connect(yes, node.inputs[5])
            self.cache[cache_key] = node.outputs[1]
        return self.cache[cache_key]

    def vsaturate(self, vector, inherited_flag=0.):
        absolute = self.vop('ABSOLUTE', vector)
        values = self.split(absolute)
        flag = self.lt(FLOAT_MAX, self.maximum(values[0], self.maximum(values[1], values[2])))
        result = self.vop('MINIMUM', self.vop('MAXIMUM', vector, (-FLOAT_MAX,)*3), (FLOAT_MAX,)*3)
        return result, (flag if isinstance(inherited_flag, Real) and inherited_flag == 0. else self.maximum(flag, inherited_flag))

    def vector(self, values):
        key = ("vector", *map(_key, values))
        if key not in self.cache:
            node = self.node("ShaderNodeCombineXYZ")
            for socket, value in zip(node.inputs, values):
                self.connect(value, socket)
            self.cache[key] = node.outputs[0]
        return self.cache[key]

    def split(self, vector):
        key = ("split", _key(vector))
        if key not in self.cache:
            node = self.node("ShaderNodeSeparateXYZ")
            self.connect(vector, node.inputs[0])
            self.cache[key] = tuple(node.outputs)
            # Reassembling these same three lanes is an identity. Keep the
            # original RGB/vector socket so the unused separation can prune.
            self.cache[("vector", *map(_key, self.cache[key]))] = vector
        return self.cache[key]

    def dot(self, vector, row):
        rowkey = _key(row) if _socket(row) else tuple(float(x) for x in row)
        key = ("dot", _key(vector), rowkey)
        if key not in self.cache:
            node = self.node("ShaderNodeVectorMath", "Matrix row")
            node.operation = "DOT_PRODUCT"
            self.connect(vector, node.inputs[0])
            self.connect(row, node.inputs[1])
            self.cache[key] = node.outputs["Value"]
        return self.cache[key]

    def matrix(self, vector, matrix):
        if all(float(matrix[i][j]) == float(i == j) for i in range(3) for j in range(3)):
            return vector
        # Keep the neutral contribution separate. Rounded dot rows can tint an
        # exact neutral before appearance encoding; subtracting green first
        # makes equal channels exactly neutral when row sums round equally.
        red, green, blue = self.split(vector)
        red_delta = self.vscale(tuple(float(row[0]) for row in matrix), self.sub(red, green))
        blue_delta = self.vscale(tuple(float(row[2]) for row in matrix), self.sub(blue, green))
        neutral = self.vscale(tuple(math.fsum(float(x) for x in row) for row in matrix), green)
        return self.vadd(self.vadd(red_delta, blue_delta), neutral)

    def linear(self, rgb):
        return self.matrix(rgb, self.prepared.linear_rgb)

    def _cone_response(self, cone):
        p = self.power(self.mul(self.prepared.fl, self.abs(cone)), .42)
        denominator = self.add(27.13, p)
        value = self.mul(self.sign(cone), self.div(self.mul(400, p), denominator))
        return value, self.div(10852.0, denominator)

    def _eccentricity(self, a, b, *, robust=False):
        if robust:
            scale = self.maximum(self.abs(a), self.abs(b))
            an, bn = self.div(a, scale), self.div(b, scale)
            norm = self.sqrt(self.madd(an, an, self.mul(bn, bn)))
            # Derive hue before reconstructing a possibly overflowing radius.
            # Two finite float32 opponents can have a norm above FLOAT_MAX.
            c, s = self.div(an, norm), self.div(bn, norm)
            radius = self.mul(scale, norm)
        else:
            radius = self.sqrt(self.madd(a, a, self.mul(b, b)))
            c, s = self.div(a, radius), self.div(b, radius)
        p = self.madd(self.madd(self.madd(self.madd(.2312, c, -.5388), c, -.2828), c, .3459), c, 1.0547)
        q = self.madd(self.madd(self.madd(.0768, c, .154), c, -.1), c, -.186)
        return self.madd(s, q, p), radius

    def encode_cones(self, cones):
        # The same response law in three native vector lanes avoids repeating
        # scalar power/division nodes. Retain pole margins for stable opponents.
        p = self.vop('POWER', self.vscale(self.vop('ABSOLUTE', cones), self.prepared.fl), (.42,)*3)
        denominator = self.vadd(p, (27.13,)*3)
        responses = self.vmul(self.vop('SIGN', cones), self.vdiv(self.vscale(p, 400.), denominator))
        r = self.split(responses)
        margins = self.split(self.vdiv((10852.,)*3, denominator))
        ach = self.madd(2, r[0], self.madd(.05, r[2], r[1]))
        ja = self.mul(self.mul(100, self.sign(ach)), self.power(self.div(self.abs(ach), self.prepared.aw), self.prepared.gamma))

        # Same-sign responses near the pole retain opponent differences in
        # their small pole margins. Exact neutrals remain exactly achromatic.
        low = self.minimum(r[0], self.minimum(r[1], r[2]))
        high = self.maximum(r[0], self.maximum(r[1], r[2]))
        same_positive = self.sub(1, self.lt(low, 0))
        same_negative = self.sub(1, self.lt(0, high))
        near = self.mul(self.maximum(same_positive, same_negative), self.lt(200, self.maximum(self.abs(low), self.abs(high))))
        def difference(i, j):
            stable = self.mul(self.sign(ach), self.sub(margins[j], margins[i]))
            return self.select(near, stable, self.sub(r[i], r[j]))
        rg, bg, rb = difference(0, 1), difference(2, 1), difference(0, 2)
        a = self.madd(1/11, bg, rg)
        b = self.div(self.sub(rb, bg), 9)
        eccentricity, radius = self._eccentricity(a, b)
        factor = self.mul(1204 / self.prepared.aw, eccentricity)
        return AppearanceSockets(self, ja, a, b, ach, factor, self.mul(radius, factor))

    def encode(self, rgb):
        return self.encode_cones(self.matrix(rgb, self.prepared.to_cones))

    def _table_image(self):
        if self.parameters is not None:
            return self.parameters.image
        return self._packed_image(self.prepared.table.pixels, key=('tone', id(self.prepared.table)),
                                  label='Perceptual Grade tone coefficients')

    def _packed_image(self, pixels, *, key=None, label='Perceptual Grade coefficients'):
        """Create one caller-owned RGBA32F image per immutable table identity."""
        cache_key = ('packed_image', id(pixels) if key is None else key)
        if cache_key in self.cache:
            return self.cache[cache_key]
        import bpy
        height, width, channels = pixels.shape
        if channels != 4:
            raise ValueError('Packed coefficient data must have four channels')
        image = bpy.data.images.new(label, width=width, height=height, alpha=True, float_buffer=True)
        self.images.append(image)  # Retain before the first fallible native write.
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "CHANNEL_PACKED"
        image.use_half_precision = False
        image.pixels.foreach_set(pixels.ravel())
        image.update()
        image.pack()
        self.cache[cache_key] = image
        return image

    def _texture_mix(self, factor, low, high, *, vector=False):
        """Linear data interpolation, including a constant fractional factor."""
        if isinstance(factor, Real):
            if factor == 0.: return low
            if factor == 1.: return high
        else:
            return self.vselect(factor, high, low) if vector else self.select(factor, high, low)
        cache_key = ('texture_mix', vector, _key(factor), _key(low), _key(high))
        if cache_key not in self.cache:
            node = self.node('ShaderNodeMix', 'Interpolate parameter data')
            node.data_type = 'VECTOR' if vector else 'FLOAT'
            node.factor_mode = 'UNIFORM'
            node.clamp_factor = True
            self.connect(factor, node.inputs[0])
            self.connect(low, node.inputs[4 if vector else 2])
            self.connect(high, node.inputs[5 if vector else 3])
            self.cache[cache_key] = node.outputs[1 if vector else 0]
        return self.cache[cache_key]

    def _sample_shader_linear(self, pixels, x, y, *, key, label, interpolate_y=True):
        """Read level-zero texels: implicit GPU mipmaps corrupt parameter data."""
        height, width, _ = pixels.shape
        ix = self.op('FLOOR', x)
        tx = self.sub(x, ix)
        iy = self.op('FLOOR', y) if interpolate_y else y
        ty = self.sub(y, iy) if interpolate_y else 0.
        u0 = self.madd(1./width, ix, .5/width)
        v0 = self.madd(1./height, iy, .5/height)
        image = self._packed_image(pixels, key=key, label=label)
        origin = self.vector((u0, v0, 1.))
        def texel(dx, dy):
            uv = self.vadd(origin, (dx/width, dy/height, 0.)) if dx or dy else origin
            return self._sample_shader_uv(image, uv, 'Closest', label)
        def row(dy):
            left, right = texel(0, dy), texel(1, dy)
            return (self._texture_mix(tx, left[0], right[0], vector=True),
                    self._texture_mix(tx, left[1], right[1]))
        lower = row(0)
        if isinstance(ty, Real) and ty == 0.:
            return lower
        upper = row(1)
        return (self._texture_mix(ty, lower[0], upper[0], vector=True),
                self._texture_mix(ty, lower[1], upper[1]))

    def _sample_shader_uv(self, image, uv, interpolation, label):
        key = ('shader_texture_sample', image.as_pointer(), _key(uv), interpolation)
        if key not in self.cache:
            node = self.node('ShaderNodeTexImage', label)
            node.image = image
            node.interpolation = interpolation
            node.extension = 'EXTEND'
            self.connect(uv, node.inputs['Vector'])
            self.cache[key] = node.outputs['Color'], node.outputs['Alpha']
        return self.cache[key]

    def sample_texture(self, pixels, u=None, v=None, *, key=None, interpolation='Linear',
                       label='Perceptual Grade coefficients', pixel_coordinates=None):
        """Sample packed RGBA data at normalized UV or explicit pixel centers.

        Shader linear interpolation uses level-zero nearest texels explicitly;
        implicit image mipmaps would blend unrelated fields as pixels change.
        Compositor retains its native bilinear sampler. Pixel coordinates avoid
        a normalized-UV round trip when the caller already has table indices.
        """
        height, width, _ = pixels.shape
        if self.tree.bl_idname == 'ShaderNodeTree' and interpolation == 'Linear':
            x, y = (pixel_coordinates if pixel_coordinates is not None else
                    (self.madd(width, u, -.5), self.madd(height, v, -.5)))
            return self._sample_shader_linear(pixels, x, y, key=key, label=label)
        if pixel_coordinates is not None:
            x, y = pixel_coordinates
            u, v = self.madd(1./width, x, .5/width), self.madd(1./height, y, .5/height)
        image = self._packed_image(pixels, key=key, label=label)
        sampler_key = ('texture_sample', image.as_pointer(), _key(u), _key(v), interpolation)
        if sampler_key in self.cache:
            return self.cache[sampler_key]
        uv = self.vector((u, v, 1.))
        if self.tree.bl_idname == 'ShaderNodeTree':
            result = self._sample_shader_uv(image, uv, interpolation, label)
        else:
            source_key = ('coefficient_image', image.as_pointer())
            source = self.cache.get(source_key)
            if source is None:
                source = self.node('CompositorNodeImage', label)
                source.image = image
                self.cache[source_key] = source
            node = self.node('CompositorNodeMapUV', label)
            node.inputs['Interpolation'].default_value = 'Nearest' if interpolation == 'Closest' else 'Bilinear'
            node.inputs['Extension X'].default_value = 'Extend'
            node.inputs['Extension Y'].default_value = 'Extend'
            self.connect(source.outputs['Image'], node.inputs['Image'])
            self.connect(uv, node.inputs['UV'])
            separate = self.node('CompositorNodeSeparateColor', 'Coefficient alpha')
            separate.mode = 'RGB'
            self.connect(node.outputs['Image'], separate.inputs['Image'])
            result = node.outputs['Image'], separate.outputs['Alpha']
            self.cache[('sample_components', image.as_pointer(), _key(u), _key(v), interpolation)] = tuple(separate.outputs[name] for name in ('Red', 'Green', 'Blue', 'Alpha'))
        self.cache[sampler_key] = result
        return result

    def sample_field(self, table, coordinate, row, *, interpolation='Linear'):
        """Read an RGBA field using floating pixel coordinates (centers at integers)."""
        height, width, _ = table.pixels.shape
        segments = getattr(table, 'segments', 1)
        if segments > 1:
            cells = table.segment_cells
            segment = self.minimum(segments-1, self.op('FLOOR', self.div(coordinate, cells)))
            coordinate = self.sub(coordinate, self.mul(segment, cells))
            row = self.madd(row, segments, segment)
        if self.tree.bl_idname == 'ShaderNodeTree' and interpolation == 'Linear':
            color, alpha = self._sample_shader_linear(table.pixels, coordinate, row,
                key=('field', id(table)), label=getattr(table, 'name', 'Perceptual Grade fields'),
                interpolate_y=False)
            return (*self.split(color), alpha)
        u, v = self.madd(1./width, coordinate, .5/width), self.madd(1./height, row, .5/height)
        color, alpha = self.sample_texture(table.pixels, u, v,
            key=('field', id(table)), interpolation=interpolation)
        if self.tree.bl_idname == 'CompositorNodeTree':
            image = self.cache[('packed_image', ('field', id(table)))]
            return self.cache[('sample_components', image.as_pointer(), _key(u), _key(v), interpolation)]
        return (*self.split(color), alpha)

    def lookup_lut(self, cube, rgb):
        """Sample a baked linear Stack cube and return its native RGB result."""
        from .lut import append_lut_lookup
        return append_lut_lookup(self, cube, rgb)

    def _sample(self, index):
        image = self._table_image()
        width, height = image.size
        row = self.op("FLOOR", self.div(index, width))
        col = self.madd(-width, row, index)
        uv = self.vector((self.madd(1./width, col, .5/width), self.madd(1./height, row, .5/height), 1.0))
        if self.tree.bl_idname == "ShaderNodeTree":
            node = self.node("ShaderNodeTexImage", "Tone endpoint jet")
            node.image = image
            node.interpolation = "Closest"
            node.extension = "EXTEND"
            self.connect(uv, node.inputs["Vector"])
            return node.outputs["Color"]
        source_key = ('coefficient_image', image.as_pointer())
        source = self.cache.get(source_key)
        if source is None:
            source = self.node("CompositorNodeImage", "Tone endpoint jets")
            source.image = image
            self.cache[source_key] = source
        node = self.node("CompositorNodeMapUV", "Tone endpoint jet")
        node.inputs["Interpolation"].default_value = "Nearest"
        node.inputs["Extension X"].default_value = "Extend"
        node.inputs["Extension Y"].default_value = "Extend"
        self.connect(source.outputs["Image"], node.inputs["Image"])
        self.connect(uv, node.inputs["UV"])
        return node.outputs["Image"]

    def lookup(self, z):
        cells = self.prepared.table.cells
        p = self.mul(self.minimum(1, self.maximum(0, z)), cells)
        cell = self.minimum(cells - 1, self.op("FLOOR", p))
        u = self.sub(p, cell)
        v = self.sub(1, u)
        u2, v2 = self.mul(u, u), self.mul(v, v)
        u3, v3 = self.mul(u2, u), self.mul(v2, v)
        blend = self.mul(u3, self.madd(u, self.madd(6, u, -15), 10))
        left = self.vector((self.sub(1, blend), self.mul(self.mul(u, v3), self.madd(3, u, 1)), self.mul(.5, self.mul(u2, v3))))
        right = self.vector((blend, self.mul(self.mul(u3, v), self.madd(3, u, -4)), self.mul(.5, self.mul(u3, v2))))
        return self.add(self.dot(self._sample(cell), left), self.dot(self._sample(self.add(cell, 1)), right))

    def remap(self, magnitude, *, force=False):
        tone = self.prepared.tone if self.parameters is None else self.parameters.tone
        if not tone.active and not force:
            return magnitude
        t = self.maximum(0, self.div(self.sub(self.mul(.01, magnitude), tone.black), tone.span))
        # A uniform source-position grid keeps the accepted Fit range within
        # the scalar error gate. Beyond the prepared domain, lookup clamps to
        # the analytic residual asymptote while the linear tail keeps growing.
        domain = self.prepared.table.domain if self.parameters is None else self.parameters.domain
        z = self.div(t, domain)
        value = self.madd(tone.slope, t, self.lookup(z))
        value = self.select(self.op("COMPARE", t, 1, 0), tone.high, value)
        return self.mul(100, value)

    def tone(self, state, *, force=False):
        if state.graph is not self:
            raise ValueError("Appearance sockets belong to another Graph")
        if not self.prepared.tone.active and not force:
            return state
        h = state.magnitude
        target = self.remap(h, force=force)
        ratio = self.div(target, h)
        scale = self.maximum(1, ratio)
        rs = self.div(ratio, scale)
        x = self.mul(self.div(state.J_A, h), rs)
        y = self.div(self.div(self.div(self.mul(33, state.chroma), h), h), scale)
        maximum = self.maximum(self.abs(x), y)
        xn, yn = self.div(x, maximum), self.div(y, maximum)
        norm = self.mul(maximum, self.sqrt(self.madd(xn, xn, self.mul(yn, yn))))
        gain = self.mul(self.div(rs, self.add(norm, y)), ratio)
        return AppearanceSockets(self, self.mul(state.J_A, gain), self.mul(state.raw_a, gain), self.mul(state.raw_b, gain),
                                 self.mul(state.achromatic, self.power(gain, 1 / self.prepared.gamma)), state.factor, self.mul(state.chroma, gain))

    def guard_input(self, appearance):
        """Freeze post-Tone reference energy without adding a Color stage."""
        return self._color_input(appearance)

    def _decode_responses(self, achromatic, raw_a, raw_b):
        combined = self.vector((achromatic, raw_a, raw_b))
        responses = tuple(self.dot(combined, row) for row in INVERSE_OPPONENT)
        absolute = tuple(self.abs(r) for r in responses)
        maximum = self.maximum(absolute[0], self.maximum(absolute[1], absolute[2]))
        margin = self.sub(RESPONSE_LIMIT, maximum)
        valid = self.lt(maximum, RESPONSE_LIMIT)
        cones = []
        for response, a in zip(responses, absolute):
            # Bound only operands of the unused invalid inverse. The domain
            # mask above is derived from the original unmodified responses.
            safe = self.minimum(a, SAFE_RESPONSE)
            p = self.div(self.mul(27.13, safe), self.sub(400, safe))
            value = self.mul(self.sign(response), self.div(self.power(p, 1/.42), self.prepared.fl))
            cones.append(value)
        rgb = self.matrix(self.vector(cones), self.prepared.from_cones)
        components = self.split(rgb)
        for component in components:
            valid = self.mul(valid, self.lt(self.abs(component), FLOAT_MAX))
        safe_rgb = self.vector(tuple(self.mul(valid, self.minimum(FLOAT_MAX, self.maximum(-FLOAT_MAX, v))) for v in components))
        return DecodeSockets(safe_rgb, valid, margin)

    def decode(self, state):
        if state.graph is not self:
            raise ValueError("Appearance sockets belong to another Graph")
        return self._decode_responses(state.achromatic, state.raw_a, state.raw_b)

    def decode_coordinates(self, J_A, a, b):
        """Decode arbitrary later-stage coordinates without stale Tone shortcuts."""
        eccentricity, _ = self._eccentricity(a, b, robust=True)
        factor = self.mul(1204 / self.prepared.aw, eccentricity)
        achromatic = self.mul(self.mul(self.prepared.aw, self.sign(J_A)), self.power(self.mul(.01, self.abs(J_A)), 1/self.prepared.gamma))
        return self._decode_responses(achromatic, self.div(a, factor), self.div(b, factor))

    def hk_guard(self, state):
        from .guard_graph import hk_guard
        return hk_guard(self, state)

    def output_guard(self, state):
        from .guard_graph import output_guard
        return output_guard(self, state)


def _interface(tree, name, direction, kind):
    socket = tree.interface.new_socket(name=name, in_out=direction, socket_type=kind)
    if kind == "NodeSocketFloat":
        socket.min_value = -FLOAT_MAX
        socket.max_value = FLOAT_MAX
    return socket


def _prune_unused(tree, output):
    """Remove unused emitted intermediates from a newly owned wrapper only.

    Reusable stage builders retain every requested socket. The finalized RGB
    wrapper can discard intermediates that reach none of its public outputs.
    """
    inputs = {}
    for link in tree.links:
        inputs.setdefault(link.to_node.as_pointer(), []).append(link.from_node)
    needed, pending = set(), [output]
    while pending:
        node = pending.pop()
        pointer = node.as_pointer()
        if pointer not in needed:
            needed.add(pointer)
            pending.extend(inputs.get(pointer, ()))
    for node in tuple(tree.nodes):
        if node.as_pointer() not in needed:
            tree.nodes.remove(node)


def build_group(prepared, tree_type="ShaderNodeTree", *, name="Perceptual Grade Native", export=True):
    """Create a complete guarded grade, or an explicit raw appearance export.

    ``export=False`` bypasses both export guards; it never inserts input repair.
    With reset Color this retains the original Linear/Tone regression path.
    Full graphs temporarily permit 1000 or more expanded nodes while the 1D
    Web path is optimized; ``stats`` records the actual count for acceptance.
    """
    if tree_type not in TREE_TYPES:
        raise ValueError("Expected a ShaderNodeTree or CompositorNodeTree")
    _validate_color_schema(prepared.color)
    import bpy
    tree = bpy.data.node_groups.new(name, tree_type)
    graph = Graph(tree, prepared)
    try:
        color = _interface(tree, "Color", "INPUT", "NodeSocketColor")
        color.default_value = (0, 0, 0, 1)
        if tree_type == "ShaderNodeTree":
            _interface(tree, "Alpha", "INPUT", "NodeSocketFloat").default_value = 1
        _interface(tree, "Color", "OUTPUT", "NodeSocketColor")
        for socket_name in ("Alpha", "Decode Valid", "Pole Margin", "Saturated"):
            _interface(tree, socket_name, "OUTPUT", "NodeSocketFloat")
        source = graph.node("NodeGroupInput", "Scene-linear input")
        output = graph.node("NodeGroupOutput", "Scene-linear output")
        output.is_active_output = True

        if export or prepared.color.active:
            state = graph.encode_cones(graph.matrix(source.outputs['Color'], prepared.linear_to_cones))
            state = graph.color(graph.tone(state))
            if export:
                decoded = graph.output_guard(graph.hk_guard(state))
            else:
                raw = graph.decode_coordinates(state.J_A, state.a, state.b)
                decoded = DecodeSockets(raw.color, raw.valid, raw.pole_margin, state.saturated)
        elif prepared.tone.active:
            state = graph.encode_cones(graph.matrix(source.outputs["Color"], prepared.linear_to_cones))
            decoded = graph.decode(graph.tone(state))
        else:
            # Preserve signed input and exact Linear/reset behavior without
            # an unnecessary appearance round trip or coefficient image.
            linear_rgb = graph.linear(source.outputs["Color"])
            cones = graph.matrix(source.outputs["Color"], prepared.linear_to_cones)
            cone_values = graph.split(cones)
            amplitude = graph.maximum(graph.abs(cone_values[0]), graph.maximum(graph.abs(cone_values[1]), graph.abs(cone_values[2])))
            pole_margin = graph.div(10852.0, graph.add(27.13, graph.power(graph.mul(prepared.fl, amplitude), .42)))
            valid = 1.0
            for component in graph.split(linear_rgb):
                valid = graph.mul(valid, graph.lt(graph.abs(component), FLOAT_MAX))
            decoded = DecodeSockets(linear_rgb, valid, pole_margin)

        if tree_type == "CompositorNodeTree":
            separate = graph.node("CompositorNodeSeparateColor")
            separate.mode = "RGB"
            graph.connect(source.outputs["Color"], separate.inputs["Image"])
            alpha = separate.outputs["Alpha"]
            restore = graph.node("CompositorNodeSetAlpha")
            restore.inputs["Type"].default_value = "Replace Alpha"
            graph.connect(decoded.color, restore.inputs["Image"])
            graph.connect(alpha, restore.inputs["Alpha"])
            color_output = restore.outputs["Image"]
        else:
            alpha = source.outputs["Alpha"]
            color_output = decoded.color
        for value, socket_name in ((color_output, "Color"), (alpha, "Alpha"), (decoded.valid, "Decode Valid"), (decoded.pole_margin, "Pole Margin"), (decoded.saturated, 'Saturated')):
            graph.connect(value, output.inputs[socket_name])
        _prune_unused(tree, output)
        for image in tuple(graph.images):
            if image.users == 0:
                graph.images.remove(image)
                bpy.data.images.remove(image)
        tree["perceptual_grade_nodes_schema"] = LAYOUT_SCHEMA
        tree['perceptual_grade_nodes_export'] = bool(export)
        tree["perceptual_grade_nodes_space"] = prepared.space
        tree["perceptual_grade_nodes_cells"] = int(prepared.table.cells) if prepared.tone.active else 0
        stats = count_nodes(tree, graph.images)
        return BuiltGrade(tree, tuple(graph.images), tuple(graph.helper_groups), prepared, stats)
    except BaseException:
        bpy.data.node_groups.remove(tree, do_unlink=True)
        for helper in graph.helper_groups:
            if helper.users == 0:
                bpy.data.node_groups.remove(helper)
        for image in graph.images:
            if image.users == 0:
                bpy.data.images.remove(image)
        raise

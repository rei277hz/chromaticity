"""Small native regression for parameter sampling independent of image derivatives."""
from types import SimpleNamespace
import numpy as np


def _builder(pixels, dimensions):
    def build(prepared, tree_type):
        import bpy
        from color_tools.kernel.graph import Graph, BuiltGrade, count_nodes
        tree = bpy.data.node_groups.new('Parameter sampler regression', tree_type)
        graph = Graph(tree, prepared)
        for name, direction, kind in (
                ('Color', 'INPUT', 'NodeSocketColor'), ('Alpha', 'INPUT', 'NodeSocketFloat'),
                ('Color', 'OUTPUT', 'NodeSocketColor'), ('Alpha', 'OUTPUT', 'NodeSocketFloat'),
                ('Decode Valid', 'OUTPUT', 'NodeSocketFloat'), ('Pole Margin', 'OUTPUT', 'NodeSocketFloat'),
                ('Saturated', 'OUTPUT', 'NodeSocketFloat')):
            tree.interface.new_socket(name=name, in_out=direction, socket_type=kind)
        source, output = graph.node('NodeGroupInput'), graph.node('NodeGroupOutput')
        x, y, z = graph.split(source.outputs['Color'])
        valid, margin, saturated = 1., 1., 0.
        if dimensions == 0:
            overflow, flag = graph.sat_mul(x, 4.)
            quotient, margin = graph.sat_div(x, y)
            valid = graph.safe_select(z, flag, 0.)
            saturated = graph.maximum(valid, margin)
            color = graph.vector((graph.safe_select(z, x, y),
                                  graph.safe_select(z, overflow, .25), quotient))
            alpha = .75
        elif dimensions == 1:
            table = SimpleNamespace(pixels=pixels, segments=1, name='Independent RGBA rows')
            fields = graph.sample_field(table, x, y)
            color, alpha = graph.vector(fields[:3]), fields[3]
        else:
            color, alpha = graph.sample_texture(pixels, pixel_coordinates=(x, y))
        for value, name in ((color, 'Color'), (alpha, 'Alpha'),
                            (valid, 'Decode Valid'), (margin, 'Pole Margin'), (saturated, 'Saturated')):
            graph.connect(value, output.inputs[name])
        return BuiltGrade(tree, tuple(graph.images), tuple(graph.helper_groups), prepared,
                          count_nodes(tree, graph.images))
    return build


def run():
    """Compare dynamic, discontinuous UVs with independent float64 bilinear data."""
    from color_tools.kernel import prepare
    from .native import NativeFixture
    yy, xx = np.mgrid[:32, :17]
    pixels = np.stack((3*np.sin(.7*xx+yy), .125*(xx-8)**2+.01*yy,
                       .5*yy-xx, (xx+1)/(yy+1)), axis=-1).astype(np.float32)
    rows = []
    for dimensions in (1, 2):
        index = np.arange(256)
        x = ((13*index) % 21-2 + (index % 4)/4).astype(np.float32)
        y = ((17*index) % 32 + ((index+1) % 4)/4*(dimensions-1)).astype(np.float32)
        values = np.column_stack((x, y, np.zeros(256), np.ones(256))).astype(np.float32)
        ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
        tx, ty = (x-ix)[:, None], (y-iy)[:, None]
        def sample(dx, dy):
            return pixels[np.clip(iy+dy, 0, 31), np.clip(ix+dx, 0, 16)].astype(float)
        lower = sample(0, 0)*(1-tx)+sample(1, 0)*tx
        upper = sample(0, 1)*(1-tx)+sample(1, 1)*tx
        expected = lower*(1-ty)+upper*ty
        for context, engine, device in (('shader', 'BLENDER_EEVEE', 'CPU'),
                                        ('compositor', 'CYCLES', 'GPU')):
            fixture = NativeFixture(prepare(), values, context, engine=engine, device=device,
                                    builder=_builder(pixels, dimensions))
            try:
                actual = fixture.render()
            finally:
                fixture.close()
            actual = np.column_stack((actual['rgb'], actual['alpha']))
            error = np.max(abs(actual-expected)/(1+abs(expected)), axis=0)
            finite = bool(np.isfinite(actual).all())
            rows.append(dict(dimensions=dimensions, context=context, samples=len(values),
                             channel_max_normalized=error.tolist(), finite=finite,
                             passed=bool(finite and np.max(error) <= 1.e-5)))
    limit = float(np.finfo(np.float32).max)
    values = np.resize(np.array(((limit, limit, 0., 1.), (limit, -limit, 1., 1.),
        (-limit, limit, 1., 1.), (limit, .5, 1., 1.), (limit, .5, 0., 1.),
        (-limit, .5, 1., 1.), (0., 0., 0., 1.), (1., 0., 1., 1.)), np.float32), (256, 4))
    x, y, condition = values[:, :3].astype(float).T
    quotient = np.divide(x, y, out=np.zeros_like(x), where=y != 0)
    quotient = np.where((y == 0) & (x != 0), np.copysign(np.inf, x), quotient)
    overflow = 4*x
    expected = np.column_stack((np.where(condition != 0, x, y),
        np.where(condition != 0, np.clip(overflow, -limit, limit), .25),
        np.clip(quotient, -limit, limit)))
    flags = np.column_stack(((condition != 0) & (abs(overflow) > limit), abs(quotient) > limit))
    primitives = []
    for context, engine, device in (('shader', 'BLENDER_EEVEE', 'CPU'),
                                    ('compositor', 'CYCLES', 'GPU')):
        fixture = NativeFixture(prepare(), values, context, engine=engine, device=device,
                                builder=_builder(None, 0))
        try:
            actual = fixture.render()
        finally:
            fixture.close()
        error = float(np.max(abs(actual['rgb']-expected)/(1+abs(expected))))
        actual_flags = np.column_stack((actual['valid'], actual['margin']))
        flags_correct = bool(np.array_equal(actual_flags, flags.astype(float)) and
            np.array_equal(actual['saturated'], np.any(flags, axis=1).astype(float)))
        finite = bool(np.isfinite(actual['rgb']).all())
        primitives.append(dict(context=context, samples=len(values), max_normalized=error,
                               finite=finite, flags_correct=flags_correct,
                               passed=bool(finite and flags_correct and error <= 1.e-5)))
    return dict(schema=1, gate=1.e-5,
                passed=all(row['passed'] for row in rows+primitives), cases=rows, primitives=primitives)

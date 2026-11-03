"""Shared native local-Color fixtures and independent float32 handoffs."""
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import bpy
from color_tools.kernel.graph import Graph, BuiltGrade, count_nodes
from color_tools.perceptual_grade_reference.responses import State, requested_energy, signed_hk
from .native import _image


def stage_builder(prepared, tree_type, *, isolated=False, stage='color', local=False):
    tree = bpy.data.node_groups.new('Raw Color acceptance', tree_type)
    for name, direction, kind in (
            ('Color', 'INPUT', 'NodeSocketColor'), ('Alpha', 'INPUT', 'NodeSocketFloat'),
            ('Color', 'OUTPUT', 'NodeSocketColor'), ('Alpha', 'OUTPUT', 'NodeSocketFloat'),
            ('Decode Valid', 'OUTPUT', 'NodeSocketFloat'), ('Pole Margin', 'OUTPUT', 'NodeSocketFloat'),
            ('Saturated', 'OUTPUT', 'NodeSocketFloat')):
        tree.interface.new_socket(name=name, in_out=direction, socket_type=kind)
    if local:
        tree.interface.new_socket(name='Frozen', in_out='INPUT', socket_type='NodeSocketColor')
        tree.interface.new_socket(name='Scale', in_out='INPUT', socket_type='NodeSocketFloat')
    graph = Graph(tree, prepared)
    source, output = graph.node('NodeGroupInput'), graph.node('NodeGroupOutput')
    if isolated:
        h, a, b = graph.split(source.outputs['Color'])
        if tree_type == 'ShaderNodeTree':
            energy = source.outputs['Alpha']
        else:
            separate = graph.node('CompositorNodeSeparateColor')
            separate.mode = 'RGB'
            graph.connect(source.outputs['Color'], separate.inputs['Image'])
            energy = separate.outputs['Alpha']
        # These fixtures are post-Tone states, whose proven finite bounds use
        # the same direct magnitude algebra as the real appearance handoff.
        chroma = (graph._color_norm(a, b) if local else
                  graph.sqrt(graph.madd(a, a, graph.mul(b, b))))
        magnitude = (graph._color_magnitude(energy, chroma) if local else
                     graph.sqrt(graph.madd(66., chroma, graph.abs(energy))))
        appearance = SimpleNamespace(graph=graph, H=h, a=a, b=b, energy=energy,
                                     chroma=chroma, magnitude=magnitude)
    else:
        appearance = graph.tone(graph.encode_cones(
            graph.matrix(source.outputs['Color'], prepared.linear_to_cones)))
    scale = 1.
    if local:
        h0, c0, e0 = graph.split(source.outputs['Frozen'])
        state = replace(graph._color_input(appearance), tonal_h=h0,
                        source_chroma=c0, source_energy=e0, reference_energy=e0)
        if stage == 'terms':
            state = graph._color_terms(state)
        elif stage == 'web':
            state, scale, scale_flag = graph._color_web(state)
            state = replace(state, saturated=graph._color_flag(state.saturated, scale_flag))
        elif stage == 'adaptance':
            state = graph._color_adaptance(state)
        elif stage == 'scale':
            if tree_type == 'CompositorNodeTree':
                separate = graph.node('CompositorNodeSeparateColor')
                separate.mode = 'RGB'
                graph.connect(source.outputs['Frozen'], separate.inputs['Image'])
                scale = separate.outputs['Alpha']
            else:
                scale = source.outputs['Scale']
            state = graph._color_scale(state, scale)
        else:
            raise ValueError(stage)
    elif stage == 'color':
        state = graph.color(appearance)
    else:
        state = graph._color_terms(graph._color_input(appearance))
        if stage != 'terms':
            state, _, _ = graph._color_web(state)
        if stage == 'adaptance':
            state = graph._color_adaptance(state)
    for value, name in ((state.q, 'Color'), (state.chroma, 'Alpha'),
                        (state.energy, 'Decode Valid'), (scale if local else state.reference_energy, 'Pole Margin'),
                        (state.saturated, 'Saturated')):
        graph.connect(value, output.inputs[name])
    return BuiltGrade(tree, tuple(graph.images), tuple(graph.helper_groups), prepared,
                      count_nodes(tree, graph.images))


def connect_frozen(fixture, frozen):
    """Fixture-only second float image carrying frozen selectors and scale."""
    padded = np.zeros((fixture.width*fixture.height, 4), np.float32)
    padded[:fixture.count] = frozen
    image = _image(bpy, 'Frozen Color selectors', padded, fixture.width, fixture.height)
    if fixture.context == 'compositor':
        tree = fixture.comp
        sample = tree.nodes.new('CompositorNodeImage')
        sample.image = image
        color = sample.outputs['Image']
    else:
        tree = next(material.node_tree for material in bpy.data.materials
                    if material.use_nodes and any(getattr(node, 'node_tree', None) == fixture.built.tree
                    for node in material.node_tree.nodes))
        sample = tree.nodes.new('ShaderNodeTexImage')
        sample.image, sample.interpolation = image, 'Closest'
        coordinate = next(node for node in tree.nodes if node.bl_idname == 'ShaderNodeTexCoord')
        tree.links.new(coordinate.outputs['UV'], sample.inputs['Vector'])
        color = sample.outputs['Color']
    group = next(node for node in tree.nodes if getattr(node, 'node_tree', None) == fixture.built.tree)
    tree.links.new(color, group.inputs['Frozen'])
    if fixture.context == 'shader':
        tree.links.new(sample.outputs['Alpha'], group.inputs['Scale'])


def rounded_state(state):
    limit = np.finfo(np.float32).max
    inputs = np.column_stack((np.clip(state.q, -limit, limit),
                              np.clip(state.energy, -limit, limit))).astype(np.float32)
    return inputs, State(inputs[:, :3].astype(float), inputs[:, 3].astype(float))


def local_color_frames(reference, initial):
    """Independent equations with explicit float32 handoffs at every stage."""
    _, state = rounded_state(initial)
    c = np.hypot(state.q[:, 1], state.q[:, 2])
    frozen = np.column_stack((np.hypot(state.ja, np.sqrt(66*c)), c, state.energy,
                              np.ones_like(c))).astype(np.float32)
    h, c, e = frozen[:, :3].astype(float).T
    light, chroma = reference.terms(h)
    r = 35/75*np.sqrt(abs(e))
    denominator, visible = c*c+r*r, c*c/(c*c+4)
    low = np.divide(r*r, denominator, out=np.zeros_like(c), where=denominator != 0)
    high = np.divide(c*c, denominator, out=np.zeros_like(c), where=denominator != 0)
    drivers = np.column_stack((visible*low, visible*high, state.q[:, 1:]/np.hypot(c, 2)[:, None]))
    gain = np.exp2(reference.settings.global_gain+np.sum(chroma*drivers, axis=-1))
    q = np.column_stack((state.q[:, 0]+np.sum(light*drivers, axis=-1), state.q[:, 1:]*gain[:, None]))
    q = np.where((h == 0)[:, None], state.q, q)
    changed = np.any(q != state.q, axis=-1)
    energy = np.where(changed, requested_energy(q, state.q, state.ja), state.energy)
    expected = State(q, energy)
    yield 'terms', state, expected, frozen, None
    _, state = rounded_state(expected)
    captured = []
    def capture(q, energy):
        captured.append(State(q, energy))
        return q, energy
    final_q, _ = reference.web.apply(state.q, state.energy, h, transform=capture)
    expected = captured[0] if captured else state
    before = np.hypot(expected.q[:, 1], expected.q[:, 2])
    scale = np.divide(np.hypot(final_q[:, 1], final_q[:, 2]), before,
                      out=np.ones_like(before), where=before != 0)
    frozen[:, 3] = scale.astype(np.float32)
    yield 'web', state, expected, frozen, scale
    _, state = rounded_state(expected)
    q, energy = reference.adaptation.apply(state.q, state.energy, h, c, e)
    expected = State(q, energy)
    yield 'adaptance', state, expected, frozen, None
    _, state = rounded_state(expected)
    scale = frozen[:, 3].astype(float)
    ab = state.q[:, 1:]*scale[:, None]
    energy = state.energy*scale*scale
    height = signed_hk(np.sign(energy)*np.sqrt(abs(energy)), np.hypot(ab[:, 0], ab[:, 1]))
    height = np.where(scale == 1, state.q[:, 0], height)
    yield 'scale', state, State(np.column_stack((height, ab)), energy), frozen, None


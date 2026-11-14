"""Native fixtures shared by template correctness and timing acceptance."""

from dataclasses import replace
import hashlib
from types import SimpleNamespace

import numpy as np

from color_tools.kernel import LinearSettings, ToneSettings, prepare, prepare_tone
from color_tools.kernel.boundary import prepare_boundary
from color_tools.template_build.graph import BuiltGrade, count_nodes
from color_tools.kernel.lut import LinearCube, axis, basis


TREE_TYPES = ("ShaderNodeTree", "CompositorNodeTree")
SPACES = ("Linear Rec.709", "Linear Rec.2020", "ACEScg")


def complete_prepared(space="Linear Rec.709", *, adjusted=False):
    linear = LinearSettings(exposure=0.5 if adjusted else 0.0)
    tone = (ToneSettings(input_nits=(0., 5., 45., 230., 1300.), fit=0.25)
            if adjusted else ToneSettings())
    prepared = prepare(linear, tone, space)
    return replace(prepared, tone=prepare_tone(tone, full_fields=True),
                   boundary=prepare_boundary(prepared.fl, prepared.aw, prepared.gamma))


def stack_prepared(space="Linear Rec.709", size=65, *, scale=1.0):
    coordinates = axis(size)
    lattice = np.stack(np.meshgrid(coordinates, coordinates, coordinates,
                                   indexing="ij"), axis=-1)
    matrix = np.array(((scale, 0.05, 0.0), (0.0, scale, 0.02),
                       (0.01, 0.0, scale)), dtype=np.float64)
    values = (lattice @ matrix.T).astype(np.float32)
    edges = np.zeros((3, size, size, size, 3), dtype=np.float32)
    for direction in range(3):
        delta = np.zeros(size, dtype=np.float64)
        delta[:-1] = np.diff(coordinates)
        shape = [1, 1, 1, 1]
        shape[direction] = size
        edges[direction] = (
            delta.reshape(shape) * matrix[:, direction].reshape(1, 1, 1, 3)
        ).astype(np.float32)
    to_lut, from_lut = basis(space)
    signature = hashlib.sha256(matrix.tobytes() + space.encode()).hexdigest()
    cube = LinearCube(values, edges, signature, space, to_lut, from_lut, size)
    return SimpleNamespace(cube=cube, space=space)


def production_fixture_builder(builder):
    """Give the existing renderer diagnostics without changing product outputs.

    The fixture requires diagnostic sockets. The template artifact deliberately
    contains only the production interface, so tests add constant diagnostics
    and expose the production input alpha after instantiation.
    """
    def build(prepared, tree_type):
        built = builder(prepared, tree_type)
        if isinstance(built, tuple):
            tree, images = built
            borrowed = ()
        else:
            tree, images = built.tree, built.images
            borrowed = getattr(built, "borrowed_images", ())
        output = next(node for node in tree.nodes
                      if node.bl_idname == "NodeGroupOutput" and node.is_active_output)
        for name in ("Decode Valid", "Pole Margin"):
            tree.interface.new_socket(name=name, in_out="OUTPUT", socket_type="NodeSocketFloat")
            output.inputs[name].default_value = 1.0
        if tree_type == "CompositorNodeTree":
            tree.interface.new_socket(name="Alpha", in_out="OUTPUT", socket_type="NodeSocketFloat")
            source = next(node for node in tree.nodes if node.bl_idname == "NodeGroupInput")
            alpha = tree.nodes.new("CompositorNodeSeparateColor")
            alpha.mode = "RGB"
            tree.links.new(source.outputs["Color"], alpha.inputs["Image"])
            tree.links.new(alpha.outputs["Alpha"], output.inputs["Alpha"])
        return BuiltGrade(tree, tuple(images), (), prepared,
                          count_nodes(tree, images), tuple(borrowed))
    return build

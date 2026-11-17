"""Complete fixed Grade graphs driven by two five-role parameter banks."""

from dataclasses import replace
from types import SimpleNamespace

from .graph import Graph, BuiltGrade, TREE_TYPES, count_nodes
from .parameter_color import ParameterColorGraph
from .guard_graph import compositor_stage2_output_guard
from ..kernel.color_prepare import prepare_color
from ..kernel.stage2_parameters import (
    MATRIX_RED_SLOT, MATRIX_BLUE_SLOT, MATRIX_NEUTRAL_SLOT,
    TONE_SCALARS_SLOT, TONE_DOMAIN_SLOT, OUTPUT_MATRIX_ROW_SLOTS,
    PARAMETER_CONTENT_SIGNATURE,
    PARAMETER_SCHEMA, PARAMETER_SHAPE, parameter_content_signature,
    parameter_image_matches, prepare_parameters, parameter_bank_images,
    bind_parameter_bank, PARAMETER_ROLES,
)
from ..kernel.stage2_bindings import (
    PARAMETER_IMAGE, PARAMETER_BANK_BINDINGS, PARAMETER_BINDING,
    PARAMETER_ACTIVE_BANK, PARAMETER_GENERATION, PARAMETER_SELECTOR,
    PARAMETER_SAMPLE_SELECTOR, PARAMETER_SAMPLE_ID, PARAMETER_SAMPLE_KIND,
    PARAMETER_SAMPLE_BANK, PARAMETER_READER, PARAMETER_READER_BANK,
    PARAMETER_READER_ROLE, PARAMETER_SAMPLE_ROLE, PARAMETER_ROLE,
)


class ParameterGraph(ParameterColorGraph, Graph):
    pass


class ParameterBindings:
    """Compose fixed texel reads with Graph; no update edits any socket."""

    def __init__(self, graph, parameters, images=None, *, active_bank=0):
        self.graph = graph
        if active_bank not in (0, 1):
            raise ValueError("Stage 2 active bank must be 0 or 1")
        if images is None:
            banks = []
            for bank in (0, 1):
                bundle = {}
                for role, pixels in parameters.roles.items():
                    image = graph._packed_image(
                        pixels, key=('grade_parameters', bank, role),
                        label=f'Perceptual Grade {role} bank {bank}',
                    )
                    image[PARAMETER_IMAGE] = PARAMETER_SCHEMA
                    image[PARAMETER_ROLE] = role
                    image[PARAMETER_CONTENT_SIGNATURE] = parameter_content_signature(pixels)
                    bundle[role] = image
                banks.append(bind_parameter_bank(bundle))
            images = tuple(banks)
        else:
            images = tuple(images)
            if len(images) != 2 or images[0] == images[1]:
                raise ValueError("Stage 2 requires two distinct parameter images")
            for image in images:
                if (image.get(PARAMETER_IMAGE) != PARAMETER_SCHEMA
                        or tuple(image.size) != (PARAMETER_SHAPE[1], PARAMETER_SHAPE[0])):
                    raise ValueError("Invalid shared Stage 2 parameter image")
                for role_image in parameter_bank_images(image).values():
                    if role_image is not None and role_image not in graph.images:
                        graph.images.append(role_image)
        if len(images) != 2:
            raise ValueError("Stage 2 requires exactly two parameter banks")
        for image in images:
            if (image.get(PARAMETER_IMAGE) != PARAMETER_SCHEMA
                    or tuple(image.size) != (PARAMETER_SHAPE[1], PARAMETER_SHAPE[0])
                    or not parameter_image_matches(image)):
                raise ValueError("Invalid Stage 2 parameter bank")
        self.images = images
        self.bundles = tuple(parameter_bank_images(image) for image in images)
        self.active_bank = active_bank
        self.sample_id = 0
        selector_type = ("ShaderNodeValue" if graph.tree.bl_idname == "ShaderNodeTree"
                         else "ShaderNodeMath")
        self.selector_node = graph.node(selector_type, "Grade parameter bank selector")
        if graph.tree.bl_idname == "ShaderNodeTree":
            self.selector_node.outputs["Value"].default_value = float(active_bank)
        else:
            self.selector_node.operation = "ADD"
            self.selector_node.inputs[0].default_value = float(active_bank)
            self.selector_node.inputs[1].default_value = 0.0
        self.selector = self.selector_node.outputs["Value"]
        if graph.tree.bl_idname == "CompositorNodeTree":
            self.sources = {}
            for role in PARAMETER_ROLES:
                self.sources[role] = []
                for bank, bundle in enumerate(self.bundles):
                    source = graph.node('CompositorNodeImage', f'Grade {role} bank {bank}')
                    source.image = bundle[role]
                    self._tag_reader(source, bank, role)
                    self.sources[role].append(source)
        self.selector_node[PARAMETER_SELECTOR] = True
        scalars, high = self.sample(TONE_SCALARS_SLOT)
        black, span, slope = graph.split(scalars)
        self.tone = SimpleNamespace(active=True, black=black, span=span,
                                    slope=slope, high=high)
        self.domain = graph.split(self.sample(TONE_DOMAIN_SLOT)[0])[0]

    def sample(self, slot):
        uv = self.graph.vector(((slot + .5) / PARAMETER_SHAPE[1], .5, 1.))
        return self.sample_uv(uv, label=f"Grade parameter slot {slot}")

    @staticmethod
    def _tag_reader(node, bank, role):
        node[PARAMETER_READER] = True
        node[PARAMETER_READER_BANK] = bank
        node[PARAMETER_READER_ROLE] = role

    def sample_uv(self, uv, *, label="Grade parameter texel", role='parameter'):
        graph = self.graph
        sample_id = self.sample_id
        self.sample_id += 1
        if graph.tree.bl_idname == "ShaderNodeTree":
            branches = []
            for bank, bundle in enumerate(self.bundles):
                branch = graph._sample_shader_uv(
                    bundle[role], uv, 'Closest', f'{label} bank {bank}',
                )
                branches.append(branch)
            low, high = branches
            selected = (graph.vselect(self.selector, high[0], low[0]),
                        graph.select(self.selector, high[1], low[1]))
            for value, kind in zip(selected, ("vector", "alpha")):
                value.node[PARAMETER_SAMPLE_SELECTOR] = True
                value.node[PARAMETER_SAMPLE_ID] = sample_id
                value.node[PARAMETER_SAMPLE_KIND] = kind
                value.node[PARAMETER_SAMPLE_ROLE] = role
            return selected

        samples = []
        for bank, source in enumerate(self.sources[role]):
            sample = graph.node(
                "CompositorNodeMapUV", f"{label} bank {bank}",
            )
            sample.inputs["Interpolation"].default_value = "Nearest"
            sample.inputs["Extension X"].default_value = "Extend"
            sample.inputs["Extension Y"].default_value = "Extend"
            graph.connect(source.outputs["Image"], sample.inputs["Image"])
            graph.connect(uv, sample.inputs["UV"])
            sample[PARAMETER_SAMPLE_ID] = sample_id
            sample[PARAMETER_SAMPLE_BANK] = bank
            sample[PARAMETER_SAMPLE_ROLE] = role
            separate = graph.node(
                "CompositorNodeSeparateColor", f"{label} bank {bank} channels",
            )
            separate.mode = "RGB"
            graph.connect(sample.outputs["Image"], separate.inputs["Image"])
            separate[PARAMETER_SAMPLE_ID] = sample_id
            separate[PARAMETER_SAMPLE_BANK] = bank
            separate[PARAMETER_SAMPLE_ROLE] = role
            samples.append(tuple(separate.outputs[name]
                                 for name in ("Red", "Green", "Blue", "Alpha")))

        inactive_weight = graph.sub(1., self.selector)
        selected = tuple(graph.add(
            graph.mul(samples[0][channel], inactive_weight),
            graph.mul(samples[1][channel], self.selector),
        ) for channel in range(4))
        combine = graph.node("CompositorNodeCombineColor", "Select sampled parameter RGB")
        combine.mode = "RGB"
        for value, name in zip(selected[:3], ("Red", "Green", "Blue")):
            graph.connect(value, combine.inputs[name])
        set_alpha = graph.node("CompositorNodeSetAlpha", "Select sampled parameter alpha")
        set_alpha.inputs["Type"].default_value = "Replace Alpha"
        graph.connect(combine.outputs["Image"], set_alpha.inputs["Image"])
        graph.connect(selected[3], set_alpha.inputs["Alpha"])
        set_alpha[PARAMETER_SAMPLE_SELECTOR] = True
        set_alpha[PARAMETER_SAMPLE_ID] = sample_id
        set_alpha[PARAMETER_SAMPLE_ROLE] = role
        return set_alpha.outputs["Image"], selected[3]

    def sample_field(self, role, table, coordinate, row):
        """Interpolate nearest level-zero texels along the field's scalar axis."""
        graph = self.graph
        height, width, _ = table.pixels.shape
        if table.segments > 1:
            segment = graph.minimum(table.segments - 1,
                graph.op('FLOOR', graph.div(coordinate, table.segment_cells)))
            coordinate = graph.sub(coordinate, graph.mul(segment, table.segment_cells))
            row = graph.madd(row, table.segments, segment)
        coordinate = graph.clamp(coordinate, 0., width - 1.)
        low = graph.op('FLOOR', coordinate)
        high = graph.minimum(width - 1., graph.add(low, 1.))
        fraction = graph.sub(coordinate, low)

        def sample(x):
            uv = graph.vector((graph.madd(1. / width, x, .5 / width),
                               graph.madd(1. / height, row, .5 / height), 1.))
            color, alpha = self.sample_uv(uv, role=role, label='Grade ' + role)
            return (*graph.split(color), alpha)

        left, right = sample(low), sample(high)
        return tuple(graph.madd(fraction, graph.sub(b, a), a)
                     for a, b in zip(left, right))

    @property
    def image(self):
        """Compatibility view for graph helpers that expect one tone image."""
        return self.images[self.active_bank]

    def matrix(self, rgb):
        graph = self.graph
        red, green, blue = graph.split(rgb)
        red_delta = graph.vscale(self.sample(MATRIX_RED_SLOT)[0], graph.sub(red, green))
        blue_delta = graph.vscale(self.sample(MATRIX_BLUE_SLOT)[0], graph.sub(blue, green))
        neutral = graph.vscale(self.sample(MATRIX_NEUTRAL_SLOT)[0], green)
        return graph.vadd(graph.vadd(red_delta, blue_delta), neutral)

    def output_matrix(self, vector):
        return self.graph.vector(tuple(
            self.graph.dot(vector, self.sample(slot)[0])
            for slot in OUTPUT_MATRIX_ROW_SLOTS
        ))


def build_stage2_group(prepared, tree_type="ShaderNodeTree", *,
                       name="Perceptual Grade", diagnostics=False,
                       parameter_images=None, parameter_image=None,
                       active_bank=0, generation=0):
    """Build every Tone and guard path, including an exact reset's paths."""
    if tree_type not in TREE_TYPES:
        raise ValueError("Grade nodes require a Shader or Compositor tree")
    if prepared.table is None or prepared.boundary is None:
        raise ValueError("Grade requires a complete Tone table and boundary")
    if not prepared.color.full_fields:
        prepared = replace(prepared, color=prepare_color(
            prepared.color.settings, prepared.tone, full_fields=True,
            previous=prepared.color), full_fields=True)
    parameters = prepared.parameters or prepare_parameters(prepared)
    if parameter_image is not None:
        if parameter_images is not None:
            raise ValueError("Pass parameter_images or parameter_image, not both")
        raise ValueError("Grade requires two complete five-role parameter banks")
    elif parameter_images is not None:
        parameter_images = tuple(parameter_images)
    import bpy

    tree = bpy.data.node_groups.new(name, tree_type)
    graph = ParameterGraph(tree, prepared)
    borrowed_images = ()
    try:
        if parameter_images is not None:
            borrowed_images = tuple(image for bank in parameter_images
                                    for image in parameter_bank_images(bank).values())
        graph.parameters = ParameterBindings(
            graph, parameters, parameter_images, active_bank=active_bank,
        )
        for key, image in zip(PARAMETER_BANK_BINDINGS, graph.parameters.images):
            tree[key] = image
        tree[PARAMETER_ACTIVE_BANK] = active_bank
        tree[PARAMETER_GENERATION] = int(generation)
        color_input = tree.interface.new_socket(
            name="Color", in_out="INPUT", socket_type="NodeSocketColor",
        )
        color_input.default_value = (0., 0., 0., 1.)
        if tree_type == "ShaderNodeTree":
            tree.interface.new_socket(
                name="Alpha", in_out="INPUT", socket_type="NodeSocketFloat",
            ).default_value = 1.
        tree.interface.new_socket(
            name="Color", in_out="OUTPUT", socket_type="NodeSocketColor",
        )
        if tree_type == "ShaderNodeTree" or diagnostics:
            tree.interface.new_socket(
                name="Alpha", in_out="OUTPUT", socket_type="NodeSocketFloat",
            )
        if diagnostics:
            for socket_name in ("Decode Valid", "Pole Margin", "Saturated"):
                tree.interface.new_socket(
                    name=socket_name, in_out="OUTPUT", socket_type="NodeSocketFloat",
                )

        source = tree.nodes.new("NodeGroupInput")
        output = tree.nodes.new("NodeGroupOutput")
        output.is_active_output = True
        appearance = graph.encode_cones(graph.parameters.matrix(source.outputs["Color"]))
        toned = graph.tone(appearance, force=True)
        guarded = graph.color_and_guard(toned)
        decoded = (compositor_stage2_output_guard(graph, guarded, source=source.outputs["Color"],
                                                 retained_tone=toned)
                   if tree_type == "CompositorNodeTree" else graph.output_guard(guarded))
        if tree_type == "ShaderNodeTree":
            color, alpha = decoded.color, source.outputs["Alpha"]
        else:
            separate = graph.node("CompositorNodeSeparateColor")
            separate.mode = "RGB"
            graph.connect(source.outputs["Color"], separate.inputs["Image"])
            alpha = separate.outputs["Alpha"]
            restore = graph.node("CompositorNodeSetAlpha")
            restore.inputs["Type"].default_value = "Replace Alpha"
            graph.connect(decoded.color, restore.inputs["Image"])
            graph.connect(alpha, restore.inputs["Alpha"])
            color = restore.outputs["Image"]
        graph.connect(color, output.inputs["Color"])
        if tree_type == "ShaderNodeTree" or diagnostics:
            graph.connect(alpha, output.inputs["Alpha"])
        if diagnostics:
            for value, socket_name in (
                (decoded.valid, "Decode Valid"),
                (decoded.pole_margin, "Pole Margin"),
                (decoded.saturated, "Saturated"),
            ):
                graph.connect(value, output.inputs[socket_name])
        for node in tree.nodes:
            image = getattr(node, 'image', None)
            if image is None:
                continue
            for bank, bundle in enumerate(graph.parameters.bundles):
                for role, candidate in bundle.items():
                    if image == candidate:
                        graph.parameters._tag_reader(node, bank, role)
                        break
        tree["_perceptual_grade_stage2_complete"] = True
        return BuiltGrade(tree, tuple(graph.images), tuple(graph.helper_groups),
                          prepared, count_nodes(tree, graph.images),
                          borrowed_images)
    except BaseException:
        bpy.data.node_groups.remove(tree, do_unlink=True)
        for helper in graph.helper_groups:
            if helper.users == 0:
                bpy.data.node_groups.remove(helper)
        for image in graph.images:
            if image not in borrowed_images and image.users == 0:
                bpy.data.images.remove(image)
        raise

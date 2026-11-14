"""Complete fixed Linear/Tone graphs driven by two parameter image banks."""

from types import SimpleNamespace

from .graph import Graph, BuiltGrade, TREE_TYPES, count_nodes
from .guard_graph import compositor_stage2_output_guard
from ..kernel.stage2_parameters import (
    MATRIX_RED_SLOT, MATRIX_BLUE_SLOT, MATRIX_NEUTRAL_SLOT,
    TONE_SCALARS_SLOT, TONE_DOMAIN_SLOT, PARAMETER_CONTENT_SIGNATURE,
    PARAMETER_SCHEMA, PARAMETER_SHAPE, parameter_content_signature,
    parameter_image_matches, prepare_parameters,
)
from ..kernel.stage2_bindings import (
    PARAMETER_IMAGE, PARAMETER_BANK_BINDINGS, PARAMETER_BINDING,
    PARAMETER_ACTIVE_BANK, PARAMETER_GENERATION, PARAMETER_SELECTOR,
    PARAMETER_SAMPLE_SELECTOR, PARAMETER_SAMPLE_ID, PARAMETER_SAMPLE_KIND,
    PARAMETER_SAMPLE_BANK, PARAMETER_READER, PARAMETER_READER_BANK,
)


class ParameterBindings:
    """Compose fixed texel reads with Graph; no update edits any socket."""

    def __init__(self, graph, parameters, images=None, *, active_bank=0):
        self.graph = graph
        if active_bank not in (0, 1):
            raise ValueError("Stage 2 active bank must be 0 or 1")
        if images is None:
            images = tuple(graph._packed_image(
                parameters.pixels, key=("stage2_parameters", bank),
                label=f"Perceptual Grade parameters bank {bank}",
            ) for bank in (0, 1))
            for image in images:
                image[PARAMETER_IMAGE] = PARAMETER_SCHEMA
                image[PARAMETER_CONTENT_SIGNATURE] = parameter_content_signature(
                    parameters.pixels,
                )
        else:
            images = tuple(images)
            if len(images) != 2 or images[0] == images[1]:
                raise ValueError("Stage 2 requires two distinct parameter images")
            for image in images:
                if (image.get(PARAMETER_IMAGE) != PARAMETER_SCHEMA
                        or tuple(image.size) != (PARAMETER_SHAPE[1], PARAMETER_SHAPE[0])):
                    raise ValueError("Invalid shared Stage 2 parameter image")
                if image not in graph.images:
                    graph.images.append(image)
        if len(images) != 2:
            raise ValueError("Stage 2 requires exactly two parameter banks")
        for image in images:
            if (image.get(PARAMETER_IMAGE) != PARAMETER_SCHEMA
                    or tuple(image.size) != (PARAMETER_SHAPE[1], PARAMETER_SHAPE[0])
                    or not parameter_image_matches(image)):
                raise ValueError("Invalid Stage 2 parameter bank")
        self.images = images
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
            self.sources = []
            for bank, image in enumerate(self.images):
                source = graph.node("CompositorNodeImage", f"Grade parameters bank {bank}")
                source.image = image
                source[PARAMETER_READER] = True
                source[PARAMETER_READER_BANK] = bank
                self.sources.append(source)
        self.selector_node[PARAMETER_SELECTOR] = True
        scalars, high = self.sample(TONE_SCALARS_SLOT)
        black, span, slope = graph.split(scalars)
        self.tone = SimpleNamespace(active=True, black=black, span=span,
                                    slope=slope, high=high)
        self.domain = graph.split(self.sample(TONE_DOMAIN_SLOT)[0])[0]

    def sample(self, slot):
        uv = self.graph.vector(((slot + .5) / PARAMETER_SHAPE[1], .5, 1.))
        return self.sample_uv(uv, label=f"Grade parameter slot {slot}")

    def sample_uv(self, uv, *, label="Grade parameter texel"):
        graph = self.graph
        sample_id = self.sample_id
        self.sample_id += 1
        if graph.tree.bl_idname == "ShaderNodeTree":
            branches = [graph._sample_shader_uv(
                image, uv, "Closest", f"{label} bank {bank}"
            ) for bank, image in enumerate(self.images)]
            low, high = branches
            selected = (graph.vselect(self.selector, high[0], low[0]),
                        graph.select(self.selector, high[1], low[1]))
            for value, kind in zip(selected, ("vector", "alpha")):
                value.node[PARAMETER_SAMPLE_SELECTOR] = True
                value.node[PARAMETER_SAMPLE_ID] = sample_id
                value.node[PARAMETER_SAMPLE_KIND] = kind
            return selected

        samples = []
        for bank, source in enumerate(self.sources):
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
            separate = graph.node(
                "CompositorNodeSeparateColor", f"{label} bank {bank} channels",
            )
            separate.mode = "RGB"
            graph.connect(sample.outputs["Image"], separate.inputs["Image"])
            separate[PARAMETER_SAMPLE_ID] = sample_id
            separate[PARAMETER_SAMPLE_BANK] = bank
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
        return set_alpha.outputs["Image"], selected[3]

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


def build_stage2_group(prepared, tree_type="ShaderNodeTree", *,
                       name="Perceptual Grade", diagnostics=False,
                       parameter_images=None, parameter_image=None,
                       active_bank=0, generation=0):
    """Build every Tone and guard path, including an exact reset's paths."""
    if tree_type not in TREE_TYPES:
        raise ValueError("Grade nodes require a Shader or Compositor tree")
    if prepared.table is None or prepared.boundary is None:
        raise ValueError("Stage 2 requires a complete Tone table and boundary")
    if prepared.color.active:
        raise ValueError("Stage 2 does not support Color adjustments")
    parameters = prepared.parameters or prepare_parameters(prepared)
    if parameter_image is not None:
        if parameter_images is not None:
            raise ValueError("Pass parameter_images or parameter_image, not both")
        parameter_images = (parameter_image,)
    elif parameter_images is not None:
        parameter_images = tuple(parameter_images)
    import bpy

    tree = bpy.data.node_groups.new(name, tree_type)
    graph = Graph(tree, prepared)
    borrowed_images = ()
    try:
        if parameter_images is not None and len(parameter_images) == 1:
            # Preserve the old builder seam for callers migrating from one image.
            # The second bank is owned by this graph and initialized from the same
            # complete parameter snapshot.
            borrowed_image, = parameter_images
            expected = parameter_content_signature(parameters.pixels)
            if not parameter_image_matches(borrowed_image, expected):
                raise ValueError("Borrowed Stage 2 parameter image does not match the prepared values")
            borrowed_image[PARAMETER_CONTENT_SIGNATURE] = expected
            parameter_images = (borrowed_image, graph._packed_image(
                parameters.pixels, key=("stage2_parameters", 1),
                label="Perceptual Grade parameters bank 1",
            ))
            borrowed_images = (borrowed_image,)
            parameter_images[1][PARAMETER_IMAGE] = PARAMETER_SCHEMA
            parameter_images[1][PARAMETER_CONTENT_SIGNATURE] = expected
        elif parameter_images is not None:
            borrowed_images = tuple(parameter_images)
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
        if tree_type == "CompositorNodeTree":
            # Without Color adjustments, positive energy needs no H-K repair;
            # nonpositive energy already exports black. Carry signed J_A to
            # avoid squared-energy overflow in interactive half-float images.
            decoded = compositor_stage2_output_guard(graph, toned)
        else:
            decoded = graph.output_guard(graph.hk_guard(graph.guard_input(toned)))
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
            image = getattr(node, "image", None)
            if image in graph.parameters.images:
                bank = next(index for index, candidate in enumerate(graph.parameters.images)
                            if candidate == image)
                node[PARAMETER_READER] = True
                node[PARAMETER_READER_BANK] = bank
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

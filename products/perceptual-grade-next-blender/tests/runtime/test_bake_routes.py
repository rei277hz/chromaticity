"""Bake-domain discovery against value-only Blender stand-ins."""

import importlib
from importlib.resources import files
from itertools import count
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile


_identities = count(1)


class Collection(list):
    active = None

    def get(self, name, default=None):
        return next((value for value in self if value.name == name), default)


class ID(dict):
    def __init__(self, name, **kwargs):
        super().__init__()
        self.name = name
        self.session_uid = next(_identities)
        self.__dict__.update(kwargs)

    def as_pointer(self):
        return self.session_uid


class Pixels:
    def __init__(self, values):
        self.values = list(values)
        self.reads = 0

    def foreach_get(self, destination):
        self.reads += 1
        for index, value in enumerate(self.values):
            destination[index] = value


class Image(ID):
    def __init__(self, name="Source", size=(3, 2), **kwargs):
        super().__init__(name, size=size, source="GENERATED", type="IMAGE",
                         is_tiled=False, use_multiview=False, is_dirty=True,
                         is_float=True, channels=4, has_data=True, filepath="",
                         alpha_mode="STRAIGHT", library=None, packed_file=None,
                         colorspace_settings=SimpleNamespace(name="Non-Color"),
                         pixels=Pixels((.2, .3, .4, .5) * (size[0] * size[1])))
        self.__dict__.update(kwargs)


class Socket(ID):
    def __init__(self, node, name, default=None):
        super().__init__(name, node=node, identifier=name, default_value=default,
                         links=Collection(), is_multi_input=False)


class Tree(ID):
    def __init__(self, name="Graph", kind="ShaderNodeTree"):
        super().__init__(name, bl_idname=kind, nodes=Collection())


class Node(ID):
    def __init__(self, tree, kind, name=None, inputs=(), outputs=(), **kwargs):
        super().__init__(name or kind, bl_idname=kind, id_data=tree, node_tree=None,
                         mute=False, internal_links=(), location=(0., 0.),
                         select=False, label="", operation="ADD",
                         bl_rna=SimpleNamespace(properties=(SimpleNamespace(
                             identifier="operation", is_readonly=False, type="ENUM"),)))
        self.inputs = Collection(Socket(self, name, default) for name, default in inputs)
        self.outputs = Collection(Socket(self, name, default) for name, default in outputs)
        self.__dict__.update(kwargs)
        tree.nodes.append(self)


def link(source, output, target, input_):
    origin, destination = source.outputs.get(output), target.inputs.get(input_)
    value = SimpleNamespace(from_node=source, from_socket=origin, to_node=target,
                            to_socket=destination, is_muted=False, is_valid=True)
    origin.links.append(value)
    destination.links.append(value)
    return value


def settings():
    return SimpleNamespace(
        pg_linear=SimpleNamespace(exposure=0., source_x=.3127, source_y=.329,
                                  cr_balance=0., yb_balance=0., cr_spread=0.,
                                  yb_spread=0., cr_heading=0., yb_heading=0.),
        pg_tone=SimpleNamespace(input_black=0., input_shadows=1., input_midtones=36.54,
                                input_white=203., input_highlights=1000., fit=0., peak_nits="1000"))


class BakeRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="grade-bake-routes-")
        root = Path(cls.directory.name)
        package = root / "grade_bake_routes_test"
        package.mkdir()
        with zipfile.ZipFile(files("tests.perceptual_grade_blender") / "extension.zip") as archive:
            archive.extractall(package)
        sys.path.insert(0, str(root))
        cls.module = importlib.import_module("grade_bake_routes_test.runtime.bake_routes")
        cls.color_ui = importlib.import_module("grade_bake_routes_test.kernel.color_ui")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.directory.name)
        for name in tuple(sys.modules):
            if name == "grade_bake_routes_test" or name.startswith("grade_bake_routes_test."):
                del sys.modules[name]
        cls.directory.cleanup()

    def setUp(self):
        self.tree = Tree()
        self.material = ID("Material", node_tree=self.tree)
        self.scene = ID("Scene", frame_current=7, frame_subframe=.25, world=None,
                        compositing_node_group=None, objects=Collection(),
                        cycles=SimpleNamespace(device="CPU"),
                        eevee=SimpleNamespace(taa_render_samples=64),
                        render=SimpleNamespace(engine="CYCLES", resolution_x=100,
                                               resolution_y=80, resolution_percentage=50))
        self.context = SimpleNamespace(scene=self.scene, object=None,
                                       space_data=SimpleNamespace(id=self.material, node_tree=self.tree, path=()))
        self.host = SimpleNamespace(
            context=self.context,
            path=SimpleNamespace(abspath=lambda path, library=None: path),
            data=SimpleNamespace(scenes=Collection((self.scene,)), materials=Collection((self.material,)),
                                 worlds=Collection(), objects=Collection(), colorspace=None))
        self.bpy_patch = patch.dict(sys.modules, {"bpy": self.host})
        self.bpy_patch.start()
        self.addCleanup(self.bpy_patch.stop)
        self.grade = self.make_grade(self.tree)

    def make_grade(self, tree, name="Grade", kind=None):
        owner = settings()
        owner.pg_color = SimpleNamespace(**self.color_ui.COLOR_DEFAULTS)
        return Node(tree, kind or ("PGCompositorGrade" if tree.bl_idname == "CompositorNodeTree" else "PGShaderGrade"),
                    name, inputs=(("Color", (.1, .2, .3, 1.)), ("Alpha", 1.), ("Vector", (0., 0., 0.))),
                    outputs=(("Color", None), ("Alpha", None)), pg_grade=owner,
                    pg_bake_image=None, pg_use_bake=False, pg_bake_width=32, pg_bake_height=16)

    def texture(self, tree=None, name="Texture", image=None):
        return Node(tree or self.tree, "ShaderNodeTexImage", name,
                    inputs=(("Vector", (0., 0., 0.)),), outputs=(("Color", None), ("Alpha", None)),
                    image=Image() if image is None else image, interpolation="Linear", extension="REPEAT")

    def mesh(self, *, coordinates=None, triangles=None, modifiers=()):
        coordinates = coordinates or ((0., 0.), (1., 0.), (1., 1.), (0., 1.))
        triangles = triangles or ((0, 1, 2), (0, 2, 3))
        uv = SimpleNamespace(name="BakeUV", active_render=True,
                             data=[SimpleNamespace(uv=value) for value in coordinates])
        mesh = ID("Mesh", uv_layers=[uv], loops=[SimpleNamespace(vertex_index=i) for i in range(len(coordinates))],
                  vertices=[SimpleNamespace(co=(u, v, 0.)) for u, v in coordinates],
                  polygons=[SimpleNamespace(loop_start=0, loop_total=len(coordinates), material_index=0)],
                  loop_triangles=[SimpleNamespace(loops=value) for value in triangles],
                  calc_loop_triangles=lambda: None, shape_keys=None)
        obj = ID("Object", type="MESH", data=mesh, hide_render=False, modifiers=list(modifiers), constraints=[],
                 matrix_world=((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.)),
                 material_slots=[SimpleNamespace(material=self.material)], active_material_index=0,
                 active_material=self.material)
        self.scene.objects.append(obj)
        self.host.data.objects.append(obj)
        self.context.object = obj
        return obj

    def mapped_texture(self):
        texture = self.texture()
        coordinate = Node(self.tree, "ShaderNodeUVMap", outputs=(("UV", None),))
        link(coordinate, "UV", texture, "Vector")
        link(texture, "Color", self.grade, "Color")
        return texture

    def blocked(self, code, node=None, context=None):
        with self.assertRaises(self.module.RouteBlocked) as caught:
            self.module.describe(self.grade if node is None else node, context or self.context)
        self.assertEqual(caught.exception.code, code)

    def test_constant_image_route_is_one_pixel_and_value_only(self):
        route = self.module.describe(self.grade, self.context)
        self.assertEqual((route["domain"], route["width"], route["height"]), ("IMAGE", 1, 1))
        self.assertEqual(route["shader_backend"], "CYCLES_CPU")
        self.assertEqual((route["frame"], route["subframe"]), (7, .25))
        self.assertEqual(len(route["signature"]), 64)
        self.assertIsNone(route["object_name"])
        self.assertEqual(self.module.describe(self.grade, route)["signature"], route["signature"])

    def test_shader_backend_always_uses_private_cycles_cpu(self):
        cases = (
            ("CYCLES", "CPU"),
            ("CYCLES", "GPU"),
            ("BLENDER_EEVEE", "CPU"),
            ("BLENDER_EEVEE_NEXT", "GPU"),
            ("BLENDER_WORKBENCH", "GPU"),
            ("UNKNOWN_RENDER_ENGINE", "GPU"),
        )
        for engine, device in cases:
            with self.subTest(engine=engine, device=device):
                self.scene.render.engine = engine
                self.scene.cycles.device = device
                route = self.module.describe(self.grade, self.context)
                self.assertEqual(route["shader_backend"], "CYCLES_CPU")
                self.assertEqual(route["render_engine"], "CYCLES")
                self.assertEqual(route["cycles_device"], "CPU")

    def test_render_engine_and_cycles_device_do_not_change_shader_identity(self):
        texture = self.texture()
        link(texture, "Color", self.grade, "Color")
        first = self.module.describe(self.grade, self.context)
        self.scene.cycles.device = "GPU"
        changed = self.module.describe(self.grade, self.context)
        self.assertEqual(first["signature"], changed["signature"])
        self.assertEqual(first["receipt_signature"], changed["receipt_signature"])
        self.scene.render.engine = "BLENDER_EEVEE"
        eevee = self.module.describe(self.grade, self.context)
        self.assertEqual(first["signature"], eevee["signature"])
        self.assertEqual(first["receipt_signature"], eevee["receipt_signature"])

    def test_uv_backend_uses_cycles_cpu_in_any_scene_engine(self):
        self.mapped_texture()
        self.mesh()
        self.scene.render.engine = "BLENDER_EEVEE"
        self.scene.cycles.device = "GPU"
        route = self.module.describe(self.grade, self.context)
        self.assertEqual((route["domain"], route["shader_backend"]),
                         ("UV", "CYCLES_CPU"))

    def test_engine_and_gpu_compute_backend_changes_do_not_invalidate_shader_identity(self):
        first = self.module.describe(self.grade, self.context)
        self.scene.render.engine = "BLENDER_EEVEE"
        eevee = self.module.describe(self.grade, self.context)
        for key in ("signature", "receipt_signature", "observation_signature"):
            self.assertEqual(first[key], eevee[key])
        self.scene.render.engine = "CYCLES"
        self.scene.cycles.device = "GPU"
        changed = self.module.describe(self.grade, self.context)
        for key in ("signature", "receipt_signature", "observation_signature"):
            self.assertEqual(first[key], changed[key])

    def test_per_node_grade_is_not_a_bake_target(self):
        self.grade.bl_idname = "PGShaderGradePerNode"
        self.blocked("target")
        self.assertFalse(self.module.is_bake_target(self.grade))

    def test_stack_uses_semantic_entries(self):
        self.grade.bl_idname = "PGShaderGradeStack"
        self.grade.pg_stack_entries = [SimpleNamespace(grade=self.grade.pg_grade, enabled=True)]
        first = self.module.describe(self.grade, self.context)["signature"]
        self.grade.pg_stack_entries[0].grade.pg_tone.fit = .5
        self.assertNotEqual(first, self.module.describe(self.grade, self.context)["signature"])

    def test_stack_composition_revision_applies_to_multiple_enabled_entries(self):
        self.grade.bl_idname = "PGShaderGradeStack"
        self.grade.pg_stack_entries = [SimpleNamespace(grade=self.grade.pg_grade, enabled=True),
                                       SimpleNamespace(grade=self.grade.pg_grade, enabled=False)]

        for enabled in (False, True):
            with self.subTest(second_enabled=enabled):
                self.grade.pg_stack_entries[1].enabled = enabled
                first = self.module.describe(self.grade, self.context)
                with patch.object(self.module, "STACK_COMPOSITION_SCHEMA",
                                  self.module.STACK_COMPOSITION_SCHEMA + 1):
                    revised = self.module.describe(self.grade, self.context)
                for key in ("signature", "receipt_signature", "observation_signature"):
                    self.assertEqual(first[key] != revised[key], enabled, key)

    def test_upstream_stack_composition_revision_changes_bake_identity(self):
        upstream = self.make_grade(self.tree, name="Upstream Stack",
                                   kind="PGShaderGradeStack")
        upstream.pg_stack_entries = [SimpleNamespace(grade=upstream.pg_grade, enabled=True)
                                     for _ in range(2)]
        link(upstream, "Color", self.grade, "Color")
        first = self.module.describe(self.grade, self.context)
        with patch.object(self.module, "STACK_COMPOSITION_SCHEMA",
                          self.module.STACK_COMPOSITION_SCHEMA + 1):
            revised = self.module.describe(self.grade, self.context)
        for key in ("signature", "receipt_signature", "observation_signature"):
            self.assertNotEqual(first[key], revised[key], key)

    def test_stack_bake_identity_tracks_directions_of_enabled_entries_in_order(self):
        self.grade.bl_idname = "PGShaderGradeStack"
        first = SimpleNamespace(grade=self.grade.pg_grade, enabled=True, direction="FORWARD")
        second = SimpleNamespace(grade=self.grade.pg_grade, enabled=False, direction="FORWARD")
        empty = SimpleNamespace(grade=None, enabled=True, direction="FORWARD")
        self.grade.pg_stack_entries = [first, second, empty]
        single_forward = self.module.describe(self.grade, self.context)
        second.direction = empty.direction = "INVERSE"
        self.assertEqual(single_forward, self.module.describe(self.grade, self.context))

        first.direction = "INVERSE"
        single_inverse = self.module.describe(self.grade, self.context)
        with patch.object(self.module, "STACK_INVERSE_SCHEMA", self.module.STACK_INVERSE_SCHEMA + 1):
            revised = self.module.describe(self.grade, self.context)
            first.direction = "FORWARD"
            self.assertEqual(single_forward, self.module.describe(self.grade, self.context))
        first.direction = "INVERSE"
        for key in ("signature", "receipt_signature", "observation_signature"):
            self.assertNotEqual(single_inverse[key], revised[key], key)
        second.enabled = True
        two_inverse = self.module.describe(self.grade, self.context)
        first.direction = "FORWARD"
        forward_inverse = self.module.describe(self.grade, self.context)
        self.grade.pg_stack_entries = [second, first, empty]
        inverse_forward = self.module.describe(self.grade, self.context)
        for key in ("signature", "receipt_signature", "observation_signature"):
            self.assertEqual(len({item[key] for item in (
                single_forward, single_inverse, two_inverse, forward_inverse, inverse_forward,
            )}), 5, key)

    def test_upstream_stack_direction_is_observed_while_using_live_output(self):
        upstream = self.make_grade(self.tree, name="Upstream Stack",
                                   kind="PGShaderGradeStack")
        entry = SimpleNamespace(grade=upstream.pg_grade, enabled=True, direction="FORWARD")
        upstream.pg_stack_entries = [entry]
        link(upstream, "Color", self.grade, "Color")
        forward = self.module.describe(self.grade, self.context)
        entry.direction = "INVERSE"
        inverse = self.module.describe(self.grade, self.context)
        for key in ("signature", "receipt_signature", "observation_signature"):
            self.assertNotEqual(forward[key], inverse[key], key)

        upstream.pg_use_bake = True
        upstream.pg_bake_image = Image("Stored bake")
        upstream.pg_bake_image[self.module.BAKE_DOMAIN] = "IMAGE"
        baked = self.module.describe(self.grade, self.context)
        entry.direction = "FORWARD"
        self.assertEqual(baked, self.module.describe(self.grade, self.context))

    def assert_color_edit_invalidates(self, controls, names):
        baseline = self.module.describe(self.grade, self.context)
        for name in names:
            with self.subTest(field=name):
                previous = getattr(controls, name)
                setattr(controls, name, previous + .125)
                try:
                    changed = self.module.describe(self.grade, self.context)
                    for key in ("signature", "receipt_signature", "observation_signature"):
                        self.assertNotEqual(baseline[key], changed[key], key)
                    preview = self.module.preview(self.grade, self.context)
                    self.assertEqual(preview["receipt_signature"], changed["receipt_signature"])
                    self.assertEqual(self.module.observe(self.grade, self.context)["signature"],
                                     changed["observation_signature"])
                finally:
                    setattr(controls, name, previous)
        self.assertEqual(self.module.describe(self.grade, self.context)["receipt_signature"],
                         baseline["receipt_signature"])

    def test_every_color_control_changes_request_and_persisted_bake_receipt(self):
        self.assert_color_edit_invalidates(self.grade.pg_grade.pg_color,
                                          self.color_ui.COLOR_FIELDS)

    def test_upstream_and_stack_color_edits_change_bake_identity(self):
        names = ("j_a_1", "c_high_2", "lightness_fit", "chroma_fit", "global_gain",
                 "adaptance_half_saturation", "adaptance_b_3",
                 "web_chroma_0_0", "web_hue_1_2", "web_scale_3_5")
        for kind in ("PGShaderGrade", "PGShaderGradePerNode", "PGShaderGradeStack"):
            with self.subTest(upstream=kind):
                self.grade.inputs.get("Color").links.clear()
                upstream = self.make_grade(self.tree, name=kind)
                owner = upstream.pg_grade
                upstream.bl_idname = kind
                if kind in self.module.PER_NODE_TYPES:
                    upstream.pg_grade = None
                    upstream.__dict__.update(vars(owner.pg_linear))
                    upstream.__dict__.update(vars(owner.pg_tone))
                    upstream.__dict__.update(vars(owner.pg_color))
                    controls = upstream
                else:
                    controls = owner.pg_color
                if kind in self.module.STACK_TYPES:
                    upstream.pg_stack_entries = [SimpleNamespace(grade=owner, enabled=True)]
                link(upstream, "Color", self.grade, "Color")
                self.assert_color_edit_invalidates(controls, names)

        self.grade.inputs.get("Color").links.clear()
        self.grade.bl_idname = "PGShaderGradeStack"
        entry = SimpleNamespace(grade=self.grade.pg_grade, enabled=True)
        self.grade.pg_stack_entries = [entry]
        self.assert_color_edit_invalidates(entry.grade.pg_color, names)
        entry.enabled = False
        baseline = self.module.describe(self.grade, self.context)["receipt_signature"]
        entry.grade.pg_color.web_hue_1_2 = 12.
        self.assertEqual(self.module.describe(self.grade, self.context)["receipt_signature"],
                         baseline)

    def test_grade_interface_receipt_uses_public_socket_names(self):
        texture = self.texture()
        link(texture, "Color", self.grade, "Color")
        link(texture, "Alpha", self.grade, "Alpha")
        first = self.module.describe(self.grade, self.context)["receipt_signature"]
        self.grade.inputs.get("Color").identifier = "Socket_7"
        self.grade.inputs.get("Alpha").identifier = "Socket_9"
        second = self.module.describe(self.grade, self.context)["receipt_signature"]
        self.assertEqual(first, second)

    def test_still_image_route_uses_full_native_dimensions(self):
        texture = self.texture()
        mix = Node(self.tree, "ShaderNodeMath", inputs=(("Value", .2),), outputs=(("Value", None),))
        link(texture, "Color", mix, "Value")
        link(mix, "Value", self.grade, "Color")
        route = self.module.describe(self.grade, self.context)
        self.assertEqual((route["domain"], route["width"], route["height"]), ("IMAGE", 3, 2))
        self.assertEqual(route["images"][0]["image_key"], (texture.image.name, None))
        self.assertEqual(texture.image.pixels.reads, 0)

    def test_keeps_library_image_identity_in_the_sampler_descriptor(self):
        texture = self.texture()
        texture.image.library = SimpleNamespace(filepath="/tmp/bake-assets/library.blend")
        link(texture, "Color", self.grade, "Color")
        route = self.module.describe(self.grade, self.context)
        self.assertEqual(route["images"][0]["image_key"],
                         (texture.image.name, "/tmp/bake-assets/library.blend"))
        self.assertEqual(route["images"][0]["owner"], ("material", ("Material", None)))
        self.assertEqual(route["images"][0]["reader_path"], ())

    def test_explicit_uv_link_selects_uv_and_saved_context_keeps_the_object(self):
        self.mapped_texture()
        obj = self.mesh()
        route = self.module.describe(self.grade, self.context)
        self.assertEqual((route["domain"], route["width"], route["height"]), ("UV", 32, 16))
        self.assertEqual(route["object_name"], obj.name)
        self.assertEqual(route["uv_map"], "BakeUV")
        self.assertIn("linked_coordinates", route["reasons"])
        self.context.object = None
        self.assertEqual(self.module.describe(self.grade, route)["signature"], route["signature"])

    def test_multiple_images_select_uv_even_with_the_same_image_data(self):
        first = self.texture(name="First")
        second = self.texture(name="Second", image=first.image)
        mix = Node(self.tree, "ShaderNodeMixRGB", inputs=(("A", None), ("B", None)), outputs=(("Color", None),))
        link(first, "Color", mix, "A")
        link(second, "Color", mix, "B")
        link(mix, "Color", self.grade, "Color")
        self.mesh()
        route = self.module.describe(self.grade, self.context)
        self.assertEqual(route["domain"], "UV")
        self.assertIn("multiple_images", route["reasons"])

    def test_image_metadata_is_read_once_and_dependencies_are_deduplicated(self):
        first = self.texture(name="First")
        second = self.texture(name="Second", image=first.image)
        mix = Node(self.tree, "ShaderNodeMixRGB", inputs=(("A", None), ("B", None)),
                   outputs=(("Color", None),))
        link(first, "Color", mix, "A")
        link(second, "Color", mix, "B")
        link(mix, "Color", self.grade, "Color")
        link(first, "Alpha", self.grade, "Alpha")
        obj = self.mesh()
        dependencies = []
        with patch.object(self.module, "_image_state", wraps=self.module._image_state) as image_state:
            route = self.module.describe(self.grade, self.context, dependencies=dependencies)
        self.assertEqual(image_state.call_count, 1)
        self.assertEqual([item.session_uid for item in dependencies],
                         [first.image.session_uid, obj.session_uid, obj.data.session_uid])
        json.dumps(route)
        self.assertEqual(first.image.pixels.reads, 0)

    def test_preview_and_observe_collect_live_dependencies_outside_value_only_route(self):
        texture = self.texture()
        link(texture, "Color", self.grade, "Color")
        for operation in (self.module.preview, self.module.observe):
            with self.subTest(operation=operation.__name__):
                dependencies = [texture.image]
                route = operation(self.grade, self.context, dependencies=dependencies)
                self.assertEqual(len(dependencies), 1)
                self.assertIs(dependencies[0], texture.image)
                json.dumps(route)

    def test_receipt_is_stable_across_full_and_passive_routes_and_dirty_restore(self):
        texture = self.mapped_texture()
        self.mesh()
        request = self.module.describe(self.grade, self.context)
        with patch.object(self.module, "_geometry_state",
                          side_effect=AssertionError("Full geometry work")):
            passive = self.module.preview(self.grade, self.context)
            texture.image.is_dirty = False
            restored = self.module.observe(self.grade, self.context)["route"]
        self.assertEqual(request["receipt_signature"], passive["receipt_signature"])
        self.assertEqual(request["receipt_signature"], restored["receipt_signature"])
        self.assertNotEqual(request["observation_signature"], restored["observation_signature"])

    def test_image_metadata_changes_both_request_and_passive_identity(self):
        texture = self.texture()
        link(texture, "Color", self.grade, "Color")
        changes = (
            (texture.image, "size", (4, 2)),
            (texture.image, "channels", 3),
            (texture.image, "is_float", False),
            (texture.image, "alpha_mode", "PREMUL"),
            (texture.image.colorspace_settings, "name", "sRGB"),
            (texture.image, "packed_file", SimpleNamespace(size=5)),
        )
        for owner, field, value in changes:
            with self.subTest(field=field):
                first = self.module.describe(self.grade, self.context)
                previous = getattr(owner, field)
                setattr(owner, field, value)
                second = self.module.describe(self.grade, self.context)
                self.assertNotEqual(first["signature"], second["signature"])
                self.assertNotEqual(first["receipt_signature"], second["receipt_signature"])
                self.assertNotEqual(first["observation_signature"], second["observation_signature"])
                self.assertEqual(second["observation_signature"],
                                 self.module.observe(self.grade, self.context)["signature"])
                setattr(owner, field, previous)

    def test_packed_payload_is_never_accessed_and_dirty_state_is_not_durable(self):
        class Packed:
            size = 13

            @property
            def data(self):
                raise AssertionError("Packed Image contents were read")

        texture = self.texture()
        texture.image.source = "FILE"
        texture.image.packed_file = Packed()
        link(texture, "Color", self.grade, "Color")
        with patch.object(texture.image.pixels, "foreach_get",
                          side_effect=AssertionError("Image pixels were read")):
            first = self.module.describe(self.grade, self.context)
            texture.image.is_dirty = False
            second = self.module.describe(self.grade, self.context)
            self.module.preview(self.grade, self.context)
        self.assertEqual(first["signature"], second["signature"])
        self.assertEqual(first["receipt_signature"], second["receipt_signature"])
        self.assertNotEqual(first["observation_signature"], second["observation_signature"])

    def test_save_as_path_remapping_keeps_canonical_image_identity(self):
        texture = self.texture()
        texture.image.source = "FILE"
        texture.image.filepath = "//assets/source.exr"
        texture.image.library = SimpleNamespace(filepath="//assets/library.blend")
        texture.image.packed_file = SimpleNamespace(size=13)
        texture.bl_rna.properties = (SimpleNamespace(
            identifier="image", is_readonly=False, type="POINTER"),)
        self.host.path.abspath = lambda path, library=None: str(Path("/tmp/bake-project") / path[2:]) if path.startswith("//") else path
        link(texture, "Color", self.grade, "Color")
        first = self.module.describe(self.grade, self.context)
        texture.image.filepath = "/tmp/bake-project/assets/source.exr"
        texture.image.library.filepath = "/tmp/bake-project/assets/library.blend"
        second = self.module.describe(self.grade, self.context)
        self.assertEqual(first["signature"], second["signature"])
        self.assertEqual(first["receipt_signature"], second["receipt_signature"])
        self.assertEqual(first["observation_signature"], second["observation_signature"])

    def test_uv_binding_is_sticky_and_image_binding_rejects_uv_transition(self):
        self.mesh()
        destination = Image("Destination", size=(7, 5))
        destination[self.module.BAKE_DOMAIN] = "UV"
        destination["_pg_next_bake_width"], destination["_pg_next_bake_height"] = 7, 5
        self.grade.pg_bake_image = destination
        route = self.module.describe(self.grade, self.context)
        self.assertEqual((route["domain"], route["width"], route["height"]), ("UV", 7, 5))
        destination[self.module.BAKE_DOMAIN] = "IMAGE"
        self.mapped_texture()
        self.blocked("destination_domain")

    def test_preview_does_not_read_source_pixels_or_test_uv_overlap(self):
        texture = self.mapped_texture()
        self.mesh()
        with patch.object(self.module, "_validate_nonoverlap", side_effect=AssertionError("UV work")):
            route = self.module.preview(self.grade, self.context)
            self.assertEqual(route["domain"], "UV")
            self.assertIsNone(route["signature"])
            self.assertEqual(self.module.observe(self.grade, self.context)["state"], "ready")
        self.assertEqual(texture.image.pixels.reads, 0)

    def test_unsupported_image_sources_are_rejected_on_alpha_too(self):
        texture = self.texture()
        link(texture, "Alpha", self.grade, "Alpha")
        for changes, code in (({"source": "TILED"}, "source_udim"),
                              ({"source": "SEQUENCE"}, "source_sequence"),
                              ({"use_multiview": True}, "source_multiview"),
                              ({"type": "MULTILAYER"}, "source_multilayer")):
            with self.subTest(code=code):
                previous = {name: getattr(texture.image, name) for name in changes}
                texture.image.__dict__.update(changes)
                self.blocked(code)
                texture.image.__dict__.update(previous)

    def test_udim_is_not_reinterpreted_as_uv_bake(self):
        texture = self.mapped_texture()
        texture.image.source = "TILED"
        self.mesh()
        self.blocked("source_udim")

    def test_cache_geometry_overlap_and_multitile_uvs_are_rejected(self):
        self.mapped_texture()
        obj = self.mesh(modifiers=(SimpleNamespace(type="MESH_SEQUENCE_CACHE", cache_file=None),))
        self.blocked("mesh_cache")
        obj.modifiers.clear()
        obj.data.uv_layers[0].data[0].uv = (-1., 0.)
        self.blocked("uv_tile")
        obj.data.uv_layers[0].data[0].uv = (0., 0.)
        obj.data.loop_triangles = [SimpleNamespace(loops=(0, 1, 2)), SimpleNamespace(loops=(0, 1, 2))]
        self.blocked("uv_overlap")

    def test_shader_to_rgb_is_rejected_and_eevee_uv_bakes_are_allowed(self):
        source = Node(self.tree, "ShaderNodeShaderToRGB", outputs=(("Color", None),))
        link(source, "Color", self.grade, "Color")
        self.blocked("shader_to_rgb")
        self.grade.inputs.get("Color").links.clear()
        self.mapped_texture()
        self.mesh()
        self.scene.render.engine = "BLENDER_EEVEE"
        self.assertEqual(self.module.describe(self.grade, self.context)["domain"], "UV")

    def test_uv_rejects_render_modifiers_that_can_duplicate_or_change_uvs(self):
        self.mapped_texture()
        obj = self.mesh()
        for kind in ("ARRAY", "MIRROR", "SOLIDIFY", "SUBSURF", "NODES", "UV_PROJECT",
                     "ARMATURE", "CURVE", "LATTICE", "DISPLACE"):
            with self.subTest(kind=kind):
                obj.modifiers[:] = [SimpleNamespace(type=kind, show_render=True,
                                                    show_viewport=False, cache_file=None)]
                self.blocked("uv_modifier")
        obj.modifiers[:] = [SimpleNamespace(type="SMOOTH", show_render=True,
                                            cache_file=None)]
        self.assertEqual(self.module.describe(self.grade, self.context)["domain"], "UV")
        obj.modifiers[:] = [SimpleNamespace(type="ARRAY", show_render=False,
                                            cache_file=None)]
        self.assertEqual(self.module.describe(self.grade, self.context)["domain"], "UV")

    def test_coordinate_object_transform_changes_bake_identity(self):
        texture = self.texture()
        self.mesh()
        reference = ID("Coordinate Object", type="EMPTY", data=None,
                       matrix_world=((1., 0., 0., 0.), (0., 1., 0., 0.),
                                     (0., 0., 1., 0.), (0., 0., 0., 1.)))
        coordinate = Node(self.tree, "ShaderNodeTexCoord", outputs=(("Object", None),),
                          object=reference)
        coordinate.bl_rna.properties = (SimpleNamespace(
            identifier="object", is_readonly=False, type="POINTER"),)
        link(coordinate, "Object", texture, "Vector")
        link(texture, "Color", self.grade, "Color")
        dependencies = []
        first = self.module.describe(self.grade, self.context, dependencies=dependencies)["signature"]
        self.assertIn(reference.session_uid, [item.session_uid for item in dependencies])
        reference.matrix_world = ((1., 0., 0., 2.), (0., 1., 0., 0.),
                                  (0., 0., 1., 0.), (0., 0., 0., 1.))
        self.assertNotEqual(first, self.module.describe(self.grade, self.context)["signature"])

    def test_semantic_signature_ignores_ui_and_derived_kernels(self):
        texture = self.texture()
        upstream = self.make_grade(self.tree, name="Upstream")
        link(texture, "Color", upstream, "Color")
        link(upstream, "Color", self.grade, "Color")
        first = self.module.describe(self.grade, self.context)["signature"]
        upstream.location = (500., 300.)
        upstream.select = True
        upstream.node_tree = Tree("Different generated kernel")
        self.assertEqual(first, self.module.describe(self.grade, self.context)["signature"])
        upstream.pg_grade.pg_linear.exposure = 1.
        self.assertNotEqual(first, self.module.describe(self.grade, self.context)["signature"])

    def test_native_node_rename_changes_the_persisted_locator(self):
        texture = self.texture()
        link(texture, "Color", self.grade, "Color")
        first = self.module.describe(self.grade, self.context)["signature"]
        texture.name = "Renamed texture"
        self.assertNotEqual(first, self.module.describe(self.grade, self.context)["signature"])

    def test_signature_is_stable_when_runtime_session_ids_change(self):
        texture = self.texture()
        link(texture, "Color", self.grade, "Color")
        first = self.module.describe(self.grade, self.context)["signature"]
        texture.session_uid += 10000
        self.grade.session_uid += 10000
        self.scene.session_uid += 10000
        self.material.session_uid += 10000
        self.tree.session_uid += 10000
        texture.image.session_uid += 10000
        self.assertEqual(first, self.module.describe(self.grade, self.context)["signature"])

    def test_packed_metadata_changes_identity_without_reading_contents(self):
        texture = self.texture()
        texture.image.source = "FILE"
        texture.image.is_dirty = False
        texture.image.filepath = "/tmp/packed-source.exr"
        texture.image.packed_file = SimpleNamespace(size=12, data=b"first pixels")
        link(texture, "Color", self.grade, "Color")
        first = self.module.describe(self.grade, self.context)["signature"]
        texture.image.packed_file.data = b"other pixels"
        self.assertEqual(first, self.module.describe(self.grade, self.context)["signature"])
        texture.image.packed_file.size = 13
        self.assertNotEqual(first, self.module.describe(self.grade, self.context)["signature"])
        self.assertEqual(texture.image.pixels.reads, 0)

    def test_destination_image_cannot_be_an_effective_source(self):
        texture = self.texture()
        destination = texture.image
        self.grade.pg_bake_image = destination
        link(texture, "Color", self.grade, "Color")
        self.blocked("destination_feedback")

    def test_full_and_passive_observation_keys_match_without_pixel_work(self):
        texture = self.texture()
        link(texture, "Color", self.grade, "Color")
        route = self.module.describe(self.grade, self.context)
        with patch.object(Path, "open", side_effect=AssertionError("File content read")):
            passive = self.module.observe(self.grade, self.context)
        self.assertEqual(route["observation_signature"], passive["signature"])
        self.assertEqual(texture.image.pixels.reads, 0)

    def test_silent_pixel_edits_require_caller_invalidation(self):
        texture = self.texture()
        texture.image.source = "FILE"
        texture.image.is_dirty = False
        texture.image.filepath = "/tmp/still-source.exr"
        link(texture, "Color", self.grade, "Color")
        with patch.object(Path, "open", side_effect=AssertionError("File content read")):
            first = self.module.describe(self.grade, self.context)["signature"]
            texture.image.pixels.values[0] = .7
            self.assertEqual(first, self.module.describe(self.grade, self.context)["signature"])
        self.assertEqual(texture.image.pixels.reads, 0)

    def test_file_and_sidecar_contents_are_not_opened_by_any_route_scan(self):
        texture = self.texture()
        texture.image.source = "FILE"
        texture.image.is_dirty = False
        link(texture, "Color", self.grade, "Color")
        with tempfile.TemporaryDirectory(prefix="bake-file-observation-") as directory:
            path = Path(directory) / "source.exr"
            path.write_bytes(b"image contents")
            Path(str(path) + ".sidecar").write_bytes(b"color profile")
            texture.image.filepath = str(path)
            with patch.object(Path, "open", side_effect=AssertionError("File content read")):
                request = self.module.describe(self.grade, self.context)
                preview = self.module.preview(self.grade, self.context)
                observed = self.module.observe(self.grade, self.context)
            self.assertEqual(request["observation_signature"], preview["observation_signature"])
            self.assertEqual(request["observation_signature"], observed["signature"])
        self.assertEqual(texture.image.pixels.reads, 0)

    def test_passive_file_observation_detects_source_and_sidecar_changes_without_content_reads(self):
        texture = self.texture()
        texture.image.source = "FILE"
        texture.image.is_dirty = False
        link(texture, "Color", self.grade, "Color")
        with tempfile.TemporaryDirectory(prefix="bake-file-observation-") as directory:
            path = Path(directory) / "source.exr"
            path.write_bytes(b"pixels")
            texture.image.filepath = str(path)
            sidecar = Path(str(path) + ".sidecar")
            first = self.module.observe(self.grade, self.context)["signature"]
            path.write_bytes(b"changed pixels")
            changed = self.module.observe(self.grade, self.context)["signature"]
            self.assertNotEqual(first, changed)
            sidecar.write_bytes(b"color profile")
            created = self.module.observe(self.grade, self.context)["signature"]
            self.assertNotEqual(changed, created)
            sidecar.write_bytes(b"updated color profile")
            updated = self.module.observe(self.grade, self.context)["signature"]
            self.assertNotEqual(created, updated)
            sidecar.unlink()
            removed = self.module.observe(self.grade, self.context)["signature"]
            self.assertNotEqual(updated, removed)
            path.unlink()
            missing = self.module.observe(self.grade, self.context)["signature"]
            self.assertNotEqual(removed, missing)
            self.assertEqual(texture.image.pixels.reads, 0)

    def test_file_timestamps_conservatively_change_request_and_observation(self):
        texture = self.texture()
        texture.image.source = "FILE"
        texture.image.is_dirty = False
        link(texture, "Color", self.grade, "Color")
        with tempfile.TemporaryDirectory(prefix="bake-file-observation-") as directory:
            path = Path(directory) / "source.exr"
            path.write_bytes(b"unchanged pixels")
            texture.image.filepath = str(path)
            first = self.module.describe(self.grade, self.context)
            stat = path.stat()
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
            second = self.module.describe(self.grade, self.context)
            passive = self.module.observe(self.grade, self.context)
            self.assertNotEqual(first["signature"], second["signature"])
            self.assertNotEqual(first["receipt_signature"], second["receipt_signature"])
            self.assertNotEqual(first["observation_signature"], second["observation_signature"])
            self.assertEqual(second["observation_signature"], passive["signature"])

    def test_file_identity_and_change_timestamps_are_conservative_evidence(self):
        texture = self.texture()
        texture.image.source = "FILE"
        texture.image.filepath = "/tmp/stat-source.exr"
        link(texture, "Color", self.grade, "Color")
        fields = dict(st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4, st_ctime_ns=5)
        with patch.object(Path, "stat", return_value=SimpleNamespace(**fields)):
            first = self.module.describe(self.grade, self.context)
        for field in fields:
            with self.subTest(field=field):
                changed = dict(fields)
                changed[field] += 1
                with patch.object(Path, "stat", return_value=SimpleNamespace(**changed)):
                    second = self.module.describe(self.grade, self.context)
                    passive = self.module.preview(self.grade, self.context)
                self.assertNotEqual(first["signature"], second["signature"])
                self.assertNotEqual(first["receipt_signature"], second["receipt_signature"])
                self.assertEqual(second["receipt_signature"], passive["receipt_signature"])

    def test_dirty_state_is_transient_but_native_defaults_change_identity(self):
        texture = self.texture()
        link(texture, "Color", self.grade, "Color")
        first = self.module.describe(self.grade, self.context)["signature"]
        texture.image.pixels.values[0] = .8
        texture.image.is_dirty = False
        second = self.module.describe(self.grade, self.context)["signature"]
        self.assertEqual(first, second)
        self.grade.inputs.get("Alpha").default_value = .4
        self.assertNotEqual(second, self.module.describe(self.grade, self.context)["signature"])

    def test_upstream_baked_reader_ignores_live_grade_and_observes_image(self):
        upstream = self.make_grade(self.tree, name="Baked upstream")
        upstream.pg_use_bake = True
        upstream.pg_bake_image = Image("Stored bake")
        upstream.pg_bake_image[self.module.BAKE_DOMAIN] = "IMAGE"
        link(upstream, "Color", self.grade, "Color")
        upstream.node_tree = Tree("Managed upstream bake")
        upstream.node_tree[self.module.bake_graph.WRAPPER] = 1
        reader = Node(upstream.node_tree, "ShaderNodeTexImage", "Baked Image",
                      image=upstream.pg_bake_image)
        reader[self.module.bake_graph.READER] = 1
        upstream_grades = []
        first = self.module.describe(self.grade, self.context, upstream_grades=upstream_grades)
        self.assertEqual(first["images"][0]["reader_path"], ("Baked Image",))
        upstream.pg_grade.pg_linear.exposure = 1.
        upstream.pg_grade.pg_color.web_hue_1_2 = 12.
        self.assertEqual(first["signature"], self.module.describe(self.grade, self.context)["signature"])
        self.assertFalse(upstream_grades)
        upstream.pg_bake_image["_pg_next_bake_operation"] = "rebake"
        self.assertNotEqual(first["signature"], self.module.describe(self.grade, self.context)["signature"])
        reader.image = Image("Different Image")
        self.blocked("baked_sampler")

    def test_upstream_grades_use_exact_nodes_across_linked_group_occurrences(self):
        source_tree = Tree("Shared group")
        source_tree.library = SimpleNamespace(filepath="/libraries/source.blend")
        source_grade = self.make_grade(source_tree)
        source_output = Node(source_tree, "NodeGroupOutput", inputs=(("Color", None),))
        link(source_grade, "Color", source_output, "Color")
        decoy_tree = Tree(source_tree.name)
        decoy_tree.library = SimpleNamespace(filepath="/libraries/decoy.blend")
        decoy_grade = self.make_grade(decoy_tree)
        decoy_output = Node(decoy_tree, "NodeGroupOutput", inputs=(("Color", None),))
        link(decoy_grade, "Color", decoy_output, "Color")

        instances = tuple(
            Node(self.tree, "ShaderNodeGroup", name, outputs=(("Color", None),), node_tree=tree)
            for name, tree in (("First", source_tree), ("Second", source_tree), ("Decoy", decoy_tree))
        )
        link(instances[0], "Color", self.grade, "Color")
        link(instances[1], "Color", self.grade, "Alpha")
        upstream_grades = []
        route = self.module.describe(self.grade, self.context, upstream_grades=upstream_grades)
        self.assertEqual(len(upstream_grades), 1)
        self.assertIs(upstream_grades[0], source_grade)
        self.assertNotIn("upstream", route)
        json.dumps(route)

        self.grade.inputs.get("Alpha").links.clear()
        link(instances[2], "Color", self.grade, "Alpha")
        self.module.describe(self.grade, self.context, upstream_grades=upstream_grades)
        self.assertEqual(len(upstream_grades), 2)
        self.assertIs(upstream_grades[1], decoy_grade)

    def test_upstream_uv_bake_forces_surface_route_and_private_cycles(self):
        self.mesh()
        upstream = self.make_grade(self.tree, name="UV baked upstream")
        upstream.pg_use_bake = True
        upstream.pg_bake_image = Image("Stored UV bake")
        upstream.pg_bake_image[self.module.BAKE_DOMAIN] = "UV"
        link(upstream, "Color", self.grade, "Color")

        self.scene.render.engine = "BLENDER_EEVEE"
        route = self.module.describe(self.grade, self.context)
        self.assertEqual(route["domain"], "UV")
        self.assertIn("upstream_uv_bake", route["reasons"])
        self.assertEqual(route["shader_backend"], "CYCLES_CPU")

    def test_target_baked_vector_does_not_change_live_bake_identity(self):
        first = self.module.describe(self.grade, self.context)["signature"]
        uv = Node(self.tree, "ShaderNodeUVMap", outputs=(("UV", None),))
        link(uv, "UV", self.grade, "Vector")
        self.grade.pg_use_bake = True
        self.grade.pg_bake_image = Image("Own bake destination")
        self.grade.pg_bake_image[self.module.BAKE_DOMAIN] = "IMAGE"
        self.assertEqual(first, self.module.describe(self.grade, self.context)["signature"])

    def test_reused_group_requires_exact_occurrence_and_resolves_parent_input(self):
        child = Tree("Nested")
        target = self.make_grade(child)
        group_input = Node(child, "NodeGroupInput", outputs=(("Color", None),))
        link(group_input, "Color", target, "Color")
        first = Node(self.tree, "ShaderNodeGroup", "First", inputs=(("Color", (.1, .1, .1, 1.)),),
                     outputs=(("Color", None),), node_tree=child)
        second = Node(self.tree, "ShaderNodeGroup", "Second", inputs=(("Color", (.2, .2, .2, 1.)),),
                      outputs=(("Color", None),), node_tree=child)
        self.blocked("occurrence", node=target)
        self.tree.nodes.active = second
        self.context.space_data.path = (SimpleNamespace(node_tree=self.tree), SimpleNamespace(node_tree=child))
        route = self.module.describe(target, self.context)
        self.assertEqual(route["group_path"], ("Second",))
        self.tree.nodes.active = first
        self.assertEqual(self.module.describe(target, route)["signature"], route["signature"])
        second.inputs.get("Color").default_value = (.8, .2, .2, 1.)
        self.assertNotEqual(self.module.describe(target, route)["signature"], route["signature"])

    def test_compositor_constant_uses_canvas_and_image_uses_native_domain(self):
        tree = Tree("Compositor", "CompositorNodeTree")
        self.scene.compositing_node_group = tree
        target = self.make_grade(tree)
        context = SimpleNamespace(scene=self.scene, object=None,
                                  space_data=SimpleNamespace(id=self.scene, node_tree=tree, path=()))
        constant = self.module.describe(target, context)
        self.assertEqual((constant["domain"], constant["width"], constant["height"]), ("COMPOSITOR", 50, 40))
        source = Node(tree, "CompositorNodeImage", outputs=(("Image", None),), image=Image(size=(5, 3)))
        link(source, "Image", target, "Color")
        route = self.module.describe(target, context)
        self.assertEqual((route["width"], route["height"]), (5, 3))
        transform = Node(tree, "CompositorNodeScale", inputs=(("Image", None),), outputs=(("Image", None),))
        target.inputs.get("Color").links.clear()
        link(source, "Image", transform, "Image")
        link(transform, "Image", target, "Color")
        route = self.module.describe(target, context)
        self.assertIsNone(route["width"])
        self.assertIsNone(route["height"])

    def test_compositor_pointwise_constants_use_canvas_but_spatial_nodes_do_not(self):
        tree = Tree("Compositor", "CompositorNodeTree")
        self.scene.compositing_node_group = tree
        target = self.make_grade(tree)
        context = SimpleNamespace(scene=self.scene, object=None,
                                  space_data=SimpleNamespace(id=self.scene, node_tree=tree, path=()))
        math_node = Node(tree, "CompositorNodeMath", inputs=(("Value", 0.25), ("Value_001", 0.5)),
                         outputs=(("Value", None),))
        link(math_node, "Value", target, "Color")
        math_route = self.module.describe(target, context)
        self.assertEqual((math_route["width"], math_route["height"],
                          math_route["canvas_size"]), (50, 40, (50, 40)))
        target.inputs.get("Color").links.clear()
        scale = Node(tree, "CompositorNodeScale", inputs=(("Image", None),),
                     outputs=(("Image", None),))
        link(scale, "Image", target, "Color")
        spatial_route = self.module.describe(target, context)
        self.assertIsNone(spatial_route["canvas_size"])
        self.assertIsNone(spatial_route["width"])
        self.assertIsNone(spatial_route["height"])

    def test_compositor_canvas_size_changes_request_but_not_saved_receipt(self):
        tree = Tree("Compositor", "CompositorNodeTree")
        self.scene.compositing_node_group = tree
        target = self.make_grade(tree)
        context = SimpleNamespace(scene=self.scene, object=None,
                                  space_data=SimpleNamespace(id=self.scene, node_tree=tree, path=()))
        previous = self.module.describe(target, context)
        self.assertEqual(previous["canvas_size"], (50, 40))
        for name, value, expected in (
            ("resolution_x", 120, (60, 40)),
            ("resolution_y", 100, (60, 50)),
            ("resolution_percentage", 58, (69, 58)),
        ):
            with self.subTest(setting=name):
                setattr(self.scene.render, name, value)
                changed = self.module.describe(target, context)
                passive = self.module.preview(target, context)
                self.assertEqual(changed["canvas_size"], expected)
                self.assertEqual(passive["canvas_size"], expected)
                self.assertEqual(previous["receipt_signature"], changed["receipt_signature"])
                self.assertEqual(changed["request_signature"], passive["request_signature"])
                self.assertNotEqual(previous["request_signature"], changed["request_signature"])
                self.assertNotEqual(previous["observation_signature"], changed["observation_signature"])
                previous = changed
        self.scene.render.resolution_x = 119
        self.assertEqual(previous["request_signature"],
                         self.module.preview(target, context)["request_signature"])

        source = Node(tree, "CompositorNodeImage", outputs=(("Image", None),), image=Image(size=(5, 3)))
        link(source, "Image", target, "Color")
        compositor_image = self.module.preview(target, context)
        shader = self.module.preview(self.grade, self.context)
        self.scene.render.resolution_percentage = 50
        for node, node_context, before in ((target, context, compositor_image),
                                           (self.grade, self.context, shader)):
            with self.subTest(domain=before["domain"]):
                self.assertIsNone(before["canvas_size"])
                self.assertEqual(before["request_signature"], self.module.preview(
                    node, node_context)["request_signature"])

    def test_compositor_override_settings_do_not_change_bake_identity(self):
        tree = Tree("Compositor", "CompositorNodeTree")
        self.scene.compositing_node_group = tree
        target = self.make_grade(tree)
        context = SimpleNamespace(scene=self.scene, object=None,
                                  space_data=SimpleNamespace(id=self.scene, node_tree=tree, path=()))
        first = self.module.describe(target, context)
        self.scene.render.engine = "BLENDER_EEVEE"
        self.scene.cycles.device = "GPU"
        self.scene.render.compositor_device = "GPU"
        self.scene.render.compositor_precision = "AUTO"
        changed = self.module.describe(target, context)
        for key in ("signature", "receipt_signature", "observation_signature"):
            self.assertEqual(first[key], changed[key])

    def test_render_layers_engine_and_effective_cycles_device_change_identity(self):
        tree = Tree("Render Layers Compositor", "CompositorNodeTree")
        self.scene.compositing_node_group = tree
        target = self.make_grade(tree)
        context = SimpleNamespace(scene=self.scene, object=None,
                                  space_data=SimpleNamespace(id=self.scene, node_tree=tree, path=()))
        layers = Node(tree, "CompositorNodeRLayers", outputs=(("Image", None),),
                      scene=self.scene)
        link(layers, "Image", target, "Color")
        world_tree = Tree("Render Layers World")
        self.scene.world = ID("World", node_tree=world_tree)
        world_grade = self.make_grade(world_tree)
        world_output = Node(world_tree, "ShaderNodeOutputWorld", inputs=(("Surface", None),))
        link(world_grade, "Color", world_output, "Surface")
        upstream_grades = []
        cycles = self.module.describe(target, context, upstream_grades=upstream_grades)
        self.assertEqual(len(upstream_grades), 1)
        self.assertIs(upstream_grades[0], world_grade)
        self.scene.render.engine = "BLENDER_EEVEE"
        eevee = self.module.describe(target, context)
        self.assertNotEqual(cycles["signature"], eevee["signature"])
        self.scene.cycles.device = "GPU"
        eevee_gpu_setting = self.module.describe(target, context)
        self.assertEqual(eevee["signature"], eevee_gpu_setting["signature"])
        self.scene.render.engine = "CYCLES"
        gpu = self.module.describe(target, context)
        self.assertNotEqual(cycles["signature"], gpu["signature"])

    def test_render_layers_eevee_settings_change_bake_identity(self):
        tree = Tree("EEVEE Render Layers Compositor", "CompositorNodeTree")
        self.scene.compositing_node_group = tree
        target = self.make_grade(tree)
        context = SimpleNamespace(scene=self.scene, object=None,
                                  space_data=SimpleNamespace(id=self.scene, node_tree=tree, path=()))
        layers = Node(tree, "CompositorNodeRLayers", outputs=(("Image", None),),
                      scene=self.scene)
        link(layers, "Image", target, "Color")
        self.scene.render.engine = "BLENDER_EEVEE"
        first = self.module.describe(target, context)
        self.scene.eevee.taa_render_samples = 128
        changed = self.module.describe(target, context)
        self.assertNotEqual(first["signature"], changed["signature"])

    def test_compositor_camera_settings_change_bake_identity(self):
        camera_data = ID("Bake Camera Data", lens=50.0, sensor_width=36.0)
        camera = ID("Bake Camera", type="CAMERA", data=camera_data,
                    matrix_world=((1., 0., 0., 0.), (0., 1., 0., 0.),
                                  (0., 0., 1., 0.), (0., 0., 0., 1.)))
        self.scene.camera = camera
        tree = Tree("Camera Compositor", "CompositorNodeTree")
        self.scene.compositing_node_group = tree
        target = self.make_grade(tree)
        context = SimpleNamespace(
            scene=self.scene, object=None,
            space_data=SimpleNamespace(id=self.scene, node_tree=tree, path=()),
        )
        layers = Node(tree, "CompositorNodeRLayers", outputs=(("Image", None),),
                      scene=self.scene)
        link(layers, "Image", target, "Color")
        first = self.module.describe(target, context)["signature"]
        camera_data.lens = 85.0
        self.assertNotEqual(first, self.module.describe(target, context)["signature"])

    def test_compositor_light_and_world_settings_change_bake_identity(self):
        light_data = ID("Bake Light Data", energy=10.0, color=(1., .5, .25), node_tree=None)
        light = ID("Bake Light", type="LIGHT", data=light_data,
                   matrix_world=((1., 0., 0., 0.), (0., 1., 0., 0.),
                                 (0., 0., 1., 0.), (0., 0., 0., 1.)))
        self.scene.objects.append(light)
        self.scene.world = ID("Bake World", color=(.1, .2, .3), node_tree=None)
        tree = Tree("Lighting Compositor", "CompositorNodeTree")
        self.scene.compositing_node_group = tree
        target = self.make_grade(tree)
        context = SimpleNamespace(
            scene=self.scene, object=None,
            space_data=SimpleNamespace(id=self.scene, node_tree=tree, path=()),
        )
        layers = Node(tree, "CompositorNodeRLayers", outputs=(("Image", None),),
                      scene=self.scene)
        link(layers, "Image", target, "Color")
        first = self.module.describe(target, context)["signature"]
        light_data.energy = 30.0
        second = self.module.describe(target, context)["signature"]
        self.assertNotEqual(first, second)
        light_data.color = (.2, 1., .4)
        third = self.module.describe(target, context)["signature"]
        self.assertNotEqual(second, third)
        self.scene.world.color = (.5, .5, .5)
        self.assertNotEqual(third, self.module.describe(target, context)["signature"])


if __name__ == "__main__":
    unittest.main()

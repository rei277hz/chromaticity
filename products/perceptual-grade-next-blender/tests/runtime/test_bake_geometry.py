"""Exact bake identity covers mesh shading data beyond positions and UVs."""

from types import SimpleNamespace
import unittest

from . import test_bake_routes as routes


class BakeGeometryTests(unittest.TestCase):
    make_grade = routes.BakeRouteTests.make_grade
    mesh = routes.BakeRouteTests.mesh
    texture = routes.BakeRouteTests.texture
    mapped_texture = routes.BakeRouteTests.mapped_texture

    @classmethod
    def setUpClass(cls):
        routes.BakeRouteTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        routes.BakeRouteTests.tearDownClass.__func__(cls)

    def setUp(self):
        routes.BakeRouteTests.setUp(self)
        self.mapped_texture()
        self.mesh_object = self.mesh()

    def test_attributes_weights_normals_and_smoothing_change_signature(self):
        mesh = self.mesh_object.data
        mesh.attributes = [SimpleNamespace(
            name="roughness", domain="POINT", data_type="FLOAT",
            data=[SimpleNamespace(value=0.25) for _ in mesh.vertices],
        )]
        mesh.color_attributes = [SimpleNamespace(
            name="Tint", domain="CORNER", data_type="FLOAT_COLOR",
            data=[SimpleNamespace(color=(1.0, 0.0, 0.0, 1.0)) for _ in mesh.loops],
        )]
        self.mesh_object.vertex_groups = [SimpleNamespace(name="Mask", index=0)]
        for vertex in mesh.vertices:
            vertex.groups = [SimpleNamespace(group=0, weight=0.5)]
        mesh.has_custom_normals = True
        mesh.corner_normals = SimpleNamespace(
            data=[SimpleNamespace(vector=(0.0, 0.0, 1.0)) for _ in mesh.loops],
        )
        for polygon in mesh.polygons:
            polygon.use_smooth = False

        baseline = self.module.describe(self.grade, self.context)["signature"]
        mesh.attributes[0].data[0].value = 0.75
        self.assertNotEqual(baseline, self.module.describe(self.grade, self.context)["signature"])
        baseline = self.module.describe(self.grade, self.context)["signature"]
        mesh.color_attributes[0].data[0].color = (0.0, 1.0, 0.0, 1.0)
        self.assertNotEqual(baseline, self.module.describe(self.grade, self.context)["signature"])
        baseline = self.module.describe(self.grade, self.context)["signature"]
        mesh.vertices[0].groups[0].weight = 0.25
        self.assertNotEqual(baseline, self.module.describe(self.grade, self.context)["signature"])
        baseline = self.module.describe(self.grade, self.context)["signature"]
        mesh.corner_normals.data[0].vector = (1.0, 0.0, 0.0)
        self.assertNotEqual(baseline, self.module.describe(self.grade, self.context)["signature"])
        baseline = self.module.describe(self.grade, self.context)["signature"]
        mesh.polygons[0].use_smooth = True
        self.assertNotEqual(baseline, self.module.describe(self.grade, self.context)["signature"])

    def test_unsupported_attribute_fails_closed(self):
        mesh = self.mesh_object.data
        mesh.attributes = [SimpleNamespace(
            name="unknown", domain="POINT", data_type="UNSUPPORTED",
            data=[SimpleNamespace(opaque=object()) for _ in mesh.vertices],
        )]
        with self.assertRaises(self.module.RouteBlocked) as caught:
            self.module.describe(self.grade, self.context)
        self.assertEqual(caught.exception.code, "geometry_attributes")

    def test_int2d_attribute_is_fingerprinted(self):
        mesh = self.mesh_object.data
        mesh.attributes = [SimpleNamespace(
            name="corner_index", domain="CORNER", data_type="INT32_2D",
            data=[SimpleNamespace(value=(index, index + 1)) for index, _ in enumerate(mesh.loops)],
        )]
        first = self.module.describe(self.grade, self.context)["signature"]
        mesh.attributes[0].data[0].value = (7, 8)
        self.assertNotEqual(first, self.module.describe(self.grade, self.context)["signature"])

    def test_scene_render_dependency_observes_mesh_attribute_edits(self):
        mesh = self.mesh_object.data
        mesh.attributes = [SimpleNamespace(
            name="render_tint", domain="POINT", data_type="FLOAT_COLOR",
            data=[SimpleNamespace(color=(0.2, 0.3, 0.4, 1.0)) for _ in mesh.vertices],
        )]
        tree = routes.Tree("Rendered Compositor", "CompositorNodeTree")
        self.scene.compositing_node_group = tree
        target = self.make_grade(tree)
        render = routes.Node(tree, "CompositorNodeRLayers", outputs=(("Image", None),),
                             scene=self.scene)
        routes.link(render, "Image", target, "Color")
        context = SimpleNamespace(scene=self.scene, object=None,
                                  space_data=SimpleNamespace(id=self.scene, node_tree=tree, path=()))
        baseline = self.module.describe(target, context)["signature"]
        mesh.attributes[0].data[0].color = (0.8, 0.7, 0.6, 1.0)
        self.assertNotEqual(baseline, self.module.describe(target, context)["signature"])

    def test_sharp_edges_and_active_color_selection_change_identity(self):
        mesh = self.mesh_object.data
        mesh.edges = [SimpleNamespace(vertices=(0, 1), use_edge_sharp=False)]
        mesh.color_attributes = routes.Collection()
        mesh.color_attributes.active_color_name = "First"
        baseline = self.module.describe(self.grade, self.context)["signature"]
        mesh.edges[0].use_edge_sharp = True
        self.assertNotEqual(baseline, self.module.describe(self.grade, self.context)["signature"])
        baseline = self.module.describe(self.grade, self.context)["signature"]
        mesh.color_attributes.active_color_name = "Second"
        self.assertNotEqual(baseline, self.module.describe(self.grade, self.context)["signature"])

    def test_unreadable_custom_normals_fail_closed(self):
        self.mesh_object.data.has_custom_normals = True
        with self.assertRaises(self.module.RouteBlocked) as caught:
            self.module.describe(self.grade, self.context)
        self.assertEqual(caught.exception.code, "geometry_attributes")


if __name__ == "__main__":
    unittest.main()

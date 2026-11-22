"""UV Bake eligibility and native geometry dependencies."""

from types import SimpleNamespace
import unittest

from . import test_bake_routes as routes


class BakeGeometryTests(unittest.TestCase):
    make_grade = routes.BakeRouteTests.make_grade
    mesh = routes.BakeRouteTests.mesh
    texture = routes.BakeRouteTests.texture
    mapped_texture = routes.BakeRouteTests.mapped_texture
    blocked = routes.BakeRouteTests.blocked

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

    def test_uv_request_requires_finite_single_tile_coordinates(self):
        layer = self.mesh_object.data.uv_layers[0]
        for coordinate in ((float("nan"), 0.), (-1., 0.)):
            with self.subTest(coordinate=coordinate):
                layer.data[0].uv = coordinate
                self.assertEqual(self.module.preview(self.grade, self.context)["domain"], "UV")
                self.blocked("uv_tile")

    def test_uv_request_requires_nondegenerate_nonoverlapping_faces(self):
        mesh = self.mesh_object.data
        mesh.loop_triangles = []
        self.blocked("uv_empty")
        mesh.loop_triangles = [SimpleNamespace(loops=(0, 0, 1))]
        self.blocked("uv_degenerate")
        mesh.loop_triangles = [SimpleNamespace(loops=(0, 1, 2))] * 2
        self.blocked("uv_overlap")

    def test_uv_coordinates_stay_out_of_saved_receipt_and_mesh_remains_dependency(self):
        dependencies = []
        before = self.module.describe(
            self.grade, self.context, dependencies=dependencies,
        )
        layer = self.mesh_object.data.uv_layers[0]
        layer.data[2].uv = (.9, 1.)
        after = self.module.describe(self.grade, self.context)
        self.assertEqual(before["receipt_signature"], after["receipt_signature"])
        self.assertEqual(before["request_signature"], after["request_signature"])
        dependency_ids = {item.session_uid for item in dependencies}
        self.assertIn(self.mesh_object.data.session_uid, dependency_ids)

    def test_uv_and_render_layers_track_meshes_without_scanning_shading_attributes(self):
        class NativeAttributes:
            def __iter__(self):
                raise AssertionError("Bake route enumerated mesh attributes")

        obj = self.mesh_object
        obj.data.attributes = NativeAttributes()
        tree = routes.Tree("Rendered Compositor", "CompositorNodeTree")
        self.scene.compositing_node_group = tree
        target = self.make_grade(tree)
        render = routes.Node(tree, "CompositorNodeRLayers", outputs=(("Image", None),),
                             scene=self.scene)
        routes.link(render, "Image", target, "Color")
        compositor = SimpleNamespace(scene=self.scene, object=None, space_data=SimpleNamespace(
            id=self.scene, node_tree=tree, path=(),
        ))
        for node, context, domain in ((self.grade, self.context, "UV"),
                                      (target, compositor, "COMPOSITOR")):
            with self.subTest(domain=domain):
                dependencies = []
                route = self.module.describe(node, context, dependencies=dependencies)
                self.assertEqual(route["domain"], domain)
                keys = {item.session_uid for item in dependencies}
                self.assertTrue({obj.session_uid, obj.data.session_uid} <= keys)


if __name__ == "__main__":
    unittest.main()

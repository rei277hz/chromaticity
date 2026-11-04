"""Native parity while a fixed Stage 2 graph receives new parameter snapshots."""

from dataclasses import replace
from functools import partial
from pathlib import Path
import unittest

import bpy
import numpy as np

from color_tools.kernel import ColorSettings, LinearSettings, Settings, ToneSettings, prepare, prepare_tone
from color_tools.kernel.boundary import prepare_boundary
from color_tools.kernel.stage2_graph import PARAMETER_BINDING, PARAMETER_IMAGE, build_stage2_group
from color_tools.kernel.stage2_parameters import prepare_parameters
from tools.perceptual_grade.reports import cases, oracle
from tools.perceptual_grade.reports.native import NativeFixture


def complete_prepared(settings, boundary):
    base = prepare(settings.linear, settings.tone, settings.space, color=settings.color)
    tone = prepare_tone(settings.tone, full_fields=True)
    return replace(base, tone=tone, boundary=boundary)


def _default(value):
    if isinstance(value, str):
        return value
    try:
        return tuple(float(item) for item in value)
    except TypeError:
        try:
            return float(value)
        except (TypeError, ValueError):
            return value


def native_inventory(tree):
    nodes = tuple((node.as_pointer(), node.bl_idname,
                   getattr(getattr(node, "node_tree", None), "as_pointer", lambda: 0)())
                  for node in tree.nodes)
    links = tuple(sorted((link.from_node.as_pointer(), link.from_socket.as_pointer(),
                          link.to_node.as_pointer(), link.to_socket.as_pointer())
                         for link in tree.links))
    defaults = tuple(sorted(
        (node.as_pointer(), index, socket.name, _default(socket.default_value))
        for node in tree.nodes
        for index, socket in enumerate(node.inputs)
        if hasattr(socket, "default_value")
    ))
    return nodes, links, defaults


class Stage2UpdateTests(unittest.TestCase):
    def test_repeated_parameter_publication_preserves_native_graph_and_matches_oracle(self):
        values = cases.rgba(64)
        updates = (
            Settings(),
            Settings(linear=LinearSettings(
                exposure=.7, source_xy=(.34567, .3585), balance=(.4, -.2),
                spread=(45., -50.), heading=(-38., 72.),
            )),
            Settings(tone=ToneSettings(input_nits=(.2, 8., 40., 235., 1150.), fit=2.)),
            Settings(
                linear=LinearSettings(exposure=-.35, source_xy=(.31, .36),
                                      balance=(-.2, .3), spread=(25., -20.),
                                      heading=(18., -42.)),
                tone=ToneSettings(input_nits=(0., 5., 45., 230., 1300.), fit=-1.),
            ),
            Settings(linear=LinearSettings(exposure=.25), tone=ToneSettings()),
            Settings(),
        )

        reset = prepare()
        boundary = prepare_boundary(reset.fl, reset.aw, reset.gamma)
        for context in ("shader", "compositor"):
            with self.subTest(context=context):
                prepared_initial = complete_prepared(updates[0], boundary)
                fixture = NativeFixture(
                    prepared_initial, values, context,
                    builder=partial(build_stage2_group, diagnostics=True),
                )
                try:
                    built = fixture.built
                    parameter_image, = tuple(
                        image for image in built.images if image.get(PARAMETER_IMAGE)
                    )
                    self.assertEqual(built.tree[PARAMETER_BINDING], parameter_image)
                    tree_pointer = built.tree.as_pointer()
                    image_pointer = parameter_image.as_pointer()
                    inventory = native_inventory(built.tree)
                    image_ids = tuple(image.as_pointer() for image in built.images)
                    group_ids = tuple(group.as_pointer() for group in bpy.data.node_groups)

                    for settings in updates:
                        prepared = complete_prepared(settings, prepared_initial.boundary)
                        parameters = prepare_parameters(prepared)
                        parameter_image.pixels.foreach_set(parameters.pixels.ravel())
                        parameter_image.update()

                        actual = fixture.render()
                        expected = oracle.evaluate_full(
                            values[:, :3], settings.linear, settings.tone,
                            ColorSettings(), settings.space,
                        )
                        metrics = oracle.metrics(actual["rgb"], expected["rgb"])
                        self.assertLessEqual(metrics["max_normalized"], 1e-4,
                                             {"context": context, "settings": settings,
                                              "metrics": metrics})
                        np.testing.assert_array_equal(actual["alpha"], values[:, 3])
                        if context == "compositor":
                            np.testing.assert_array_equal(actual["embedded_alpha"], values[:, 3])

                        self.assertEqual(built.tree.as_pointer(), tree_pointer)
                        self.assertEqual(parameter_image.as_pointer(), image_pointer)
                        self.assertEqual(built.tree[PARAMETER_BINDING], parameter_image)
                        self.assertEqual(tuple(image.as_pointer() for image in built.images), image_ids)
                        self.assertEqual(tuple(group.as_pointer() for group in bpy.data.node_groups),
                                         group_ids)
                        self.assertEqual(native_inventory(built.tree), inventory)
                finally:
                    fixture.close()

    def test_updated_parameter_snapshot_survives_save_and_reload(self):
        values = cases.rgba(64)
        reset = prepare()
        boundary = prepare_boundary(reset.fl, reset.aw, reset.gamma)
        initial = complete_prepared(Settings(), boundary)
        settings = Settings(
            linear=LinearSettings(exposure=.4, source_xy=(.34, .36)),
            tone=ToneSettings(input_nits=(0., 7., 45., 203., 1000.),
                              fit=1., peak_nits=2000.),
        )
        parameters = prepare_parameters(complete_prepared(settings, boundary))
        fixture = NativeFixture(
            initial, values, "compositor",
            builder=partial(build_stage2_group, diagnostics=True),
        )
        try:
            parameter_image, = tuple(
                image for image in fixture.built.images if image.get(PARAMETER_IMAGE)
            )
            parameter_image.pixels.foreach_set(parameters.pixels.ravel())
            parameter_image.update()
            parameter_image.pack()
            before = fixture.render()
            image_name = parameter_image.name
            tree_name = fixture.built.tree.name
            fixture.input_image.pack()
            filename = Path(fixture.directory.name) / "stage2-updated.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(filename))
            bpy.ops.wm.open_mainfile(filepath=str(filename))

            restored = bpy.data.images[image_name]
            self.assertIsNotNone(restored.packed_file)
            self.assertEqual(bpy.data.node_groups[tree_name][PARAMETER_BINDING], restored)
            pixels = np.empty(parameters.pixels.size, dtype=np.float32)
            restored.pixels.foreach_get(pixels)
            np.testing.assert_array_equal(pixels, parameters.pixels.ravel())
            after = fixture.render()
            for name in ("rgb", "alpha", "embedded_alpha", "valid", "margin", "saturated"):
                np.testing.assert_array_equal(after[name], before[name])
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()

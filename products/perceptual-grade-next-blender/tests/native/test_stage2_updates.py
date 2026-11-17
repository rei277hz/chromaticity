"""Native parity while a fixed Grade graph receives complete parameter bundles."""

from dataclasses import replace
from functools import partial
from pathlib import Path
import unittest

import bpy
import numpy as np

from color_tools.kernel import LinearSettings, Settings, ToneSettings, prepare, prepare_tone
from color_tools.kernel.boundary import prepare_boundary
from color_tools.kernel.stage2_parameters import (
    PARAMETER_CONTENT_SIGNATURE, PARAMETER_ROLES, parameter_bank_images,
    parameter_content_signature, prepare_parameters, set_parameter_bundle_signature,
)
from color_tools.template_build.stage2_graph import (
    PARAMETER_ACTIVE_BANK, PARAMETER_BANK_BINDINGS, PARAMETER_IMAGE,
    build_stage2_group,
)
from tools.perceptual_grade.reports import cases, full_cases, oracle
from tools.perceptual_grade.reports.native import NativeFixture


def complete_prepared(settings, boundary):
    base = prepare(settings.linear, settings.tone, settings.space, color=settings.color)
    tone = prepare_tone(settings.tone, full_fields=True)
    return replace(base, tone=tone, boundary=boundary)


def write_parameter_bundle(primary, parameters):
    images = parameter_bank_images(primary)
    signatures = {}
    for role in PARAMETER_ROLES:
        image, pixels = images[role], parameters.roles[role]
        if tuple(image.size) != (pixels.shape[1], pixels.shape[0]):
            raise AssertionError("Parameter role Image shape changed: " + role)
        image.pixels.foreach_set(pixels.ravel())
        image.update()
        image.pack()
        if image.packed_file is None or image.is_dirty:
            raise AssertionError("Parameter role Image is not a clean packed receipt: " + role)
        signature = parameter_content_signature(pixels)
        image[PARAMETER_CONTENT_SIGNATURE] = signature
        signatures[role] = signature
    set_parameter_bundle_signature(primary, signatures)


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
            Settings(color=full_cases.guard_before_scale_grade()),
            Settings(),
        )

        reset = prepare()
        boundary = prepare_boundary(reset.fl, reset.aw, reset.gamma)
        for context in ("shader", "compositor"):
            with self.subTest(context=context):
                prepared_initial = complete_prepared(updates[0], boundary)
                fixture = NativeFixture(
                    prepared_initial, values, context, threads=2,
                    builder=partial(build_stage2_group, diagnostics=True),
                )
                try:
                    built = fixture.built
                    marked_images = tuple(
                        image for image in built.images if image.get(PARAMETER_IMAGE)
                    )
                    parameter_images = tuple(
                        built.tree[key] for key in PARAMETER_BANK_BINDINGS
                    )
                    self.assertEqual(len(parameter_images), 2)
                    self.assertEqual(len(marked_images), 10)
                    bank_images = tuple(
                        image for primary in parameter_images
                        for image in parameter_bank_images(primary).values()
                    )
                    self.assertEqual(
                        {image.as_pointer() for image in marked_images},
                        {image.as_pointer() for image in bank_images},
                    )
                    active_bank = built.tree[PARAMETER_ACTIVE_BANK]
                    parameter_image = parameter_images[active_bank]
                    tree_pointer = built.tree.as_pointer()
                    image_pointers = tuple(image.as_pointer() for image in bank_images)
                    inventory = native_inventory(built.tree)
                    image_ids = tuple(image.as_pointer() for image in built.images)
                    group_ids = tuple(group.as_pointer() for group in bpy.data.node_groups)

                    for settings in updates:
                        prepared = complete_prepared(settings, prepared_initial.boundary)
                        parameters = prepare_parameters(prepared)
                        write_parameter_bundle(parameter_image, parameters)

                        actual = fixture.render()
                        expected = oracle.evaluate_full(
                            values[:, :3], settings.linear, settings.tone,
                            settings.color, settings.space,
                        )
                        metrics = oracle.metrics(actual["rgb"], expected["rgb"])
                        self.assertLessEqual(metrics["max_normalized"], 1e-4,
                                             {"context": context, "settings": settings,
                                              "metrics": metrics})
                        np.testing.assert_array_equal(actual["alpha"], values[:, 3])
                        if context == "compositor":
                            np.testing.assert_array_equal(actual["embedded_alpha"], values[:, 3])

                        self.assertEqual(built.tree.as_pointer(), tree_pointer)
                        self.assertEqual(
                            tuple(image.as_pointer() for primary in parameter_images
                                  for image in parameter_bank_images(primary).values()),
                            image_pointers,
                        )
                        self.assertEqual(built.tree[PARAMETER_ACTIVE_BANK], active_bank)
                        self.assertEqual(
                            tuple(built.tree[key] for key in PARAMETER_BANK_BINDINGS),
                            parameter_images,
                        )
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
            color=full_cases.guard_before_scale_grade(),
        )
        parameters = prepare_parameters(complete_prepared(settings, boundary))
        fixture = NativeFixture(
            initial, values, "compositor", threads=2,
            builder=partial(build_stage2_group, diagnostics=True),
        )
        try:
            parameter_images = tuple(
                image for image in fixture.built.images if image.get(PARAMETER_IMAGE)
            )
            self.assertEqual(len(parameter_images), 10)
            active_bank = fixture.built.tree[PARAMETER_ACTIVE_BANK]
            primary = fixture.built.tree[PARAMETER_BANK_BINDINGS[active_bank]]
            write_parameter_bundle(primary, parameters)
            before = fixture.render()
            image_names = tuple(image.name for image in parameter_images)
            tree_name = fixture.built.tree.name
            fixture.input_image.pack()
            filename = Path(fixture.directory.name) / "stage2-updated.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(filename))
            bpy.ops.wm.open_mainfile(filepath=str(filename))

            restored_tree = bpy.data.node_groups[tree_name]
            restored_banks = tuple(restored_tree[key] for key in PARAMETER_BANK_BINDINGS)
            restored_images = tuple(
                image for bank in restored_banks
                for image in parameter_bank_images(bank).values()
            )
            self.assertEqual(tuple(image.name for image in restored_images), image_names)
            for role, image in parameter_bank_images(restored_banks[active_bank]).items():
                self.assertIsNotNone(image.packed_file)
                pixels = np.empty(parameters.roles[role].size, dtype=np.float32)
                image.pixels.foreach_get(pixels)
                np.testing.assert_array_equal(pixels, parameters.roles[role].ravel())
            after = fixture.render()
            for name in ("rgb", "alpha", "embedded_alpha", "valid", "margin", "saturated"):
                np.testing.assert_array_equal(after[name], before[name])
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()

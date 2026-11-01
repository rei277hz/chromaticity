import unittest
from types import SimpleNamespace

from color_tools.perceptual_grade_next_blender.controls import (
    COLOR_FIT,
    GRADE_CONTROL_SPECS,
    TONE_FIT,
    control_paths,
    settings_from_controls,
    unsupported_node_animation_paths,
    move_stack_entry,
)


def controls():
    fields = dict(
        exposure=1.25, source_x=0.3127, source_y=0.329,
        balance_a=0.1, balance_b=-0.2, spread_a=3.0, spread_b=-4.0,
        heading_a=15.0, heading_b=-30.0,
        tone_fit=2.0, peak_nits=4000.0,
        lightness_fit=-2.0, chroma_fit=6.0, global_gain=0.25,
        adaptance_half_saturation=0.4, working_space="ACEScg",
    )
    fields.update({f"input_nits_{i}": x for i, x in enumerate((0.0, 3.2, 36.54, 203.0, 4000.0))})
    for prefix, rows, columns in (
        ("lightness", 4, 4), ("chroma", 4, 4), ("adaptance", 4, 2),
        ("web_hue", 4, 6), ("web_chroma", 4, 6), ("web_scale", 4, 6),
    ):
        for row in range(rows):
            for column in range(columns):
                fields[f"{prefix}_{row}_{column}"] = 0.0
    fields["lightness_0_0"] = 2.0
    fields["web_scale_3_5"] = -0.75
    return SimpleNamespace(**fields)


class ControlSchemaTests(unittest.TestCase):
    def test_fit_domains_match_the_current_reference_contract(self):
        self.assertEqual(TONE_FIT, (-2.0, 2.0))
        self.assertEqual(COLOR_FIT, (-2.0, 6.0))
        self.assertEqual(GRADE_CONTROL_SPECS[6].minimum, -2.0)
        self.assertEqual(GRADE_CONTROL_SPECS[6].maximum, 2.0)
        self.assertFalse(any(spec.animatable for spec in GRADE_CONTROL_SPECS))

    def test_property_snapshot_maps_full_schema_into_core_settings(self):
        settings = settings_from_controls(controls())
        self.assertEqual(settings.linear.exposure, 1.25)
        self.assertEqual(settings.linear.balance, (0.1, -0.2))
        self.assertEqual(settings.tone.fit, 2.0)
        self.assertEqual(settings.tone.reference_nits, 203.0)
        self.assertEqual(settings.color.lightness_fit, -2.0)
        self.assertEqual(settings.color.chroma_fit, 6.0)
        self.assertEqual(settings.color.lightness[0][0], 2.0)
        self.assertEqual(settings.color.web.log_scale[3][5], -0.75)
        self.assertEqual(settings.working_space, "ACEScg")

    def test_static_path_inventory_rejects_control_animation_but_not_other_channels(self):
        path = 'nodes["Grade"].perceptual_grade_next_controls.tone_fit'
        unrelated = 'nodes["Color"].inputs["Color"].default_value'
        action = SimpleNamespace(fcurves=(SimpleNamespace(data_path=path), SimpleNamespace(data_path=unrelated)))
        animation = SimpleNamespace(action=action, nla_tracks=(), drivers=())
        self.assertEqual(
            unsupported_node_animation_paths(animation, 'nodes["Grade"]'), (path,)
        )
        self.assertIn("perceptual_grade_next_controls.web_scale_3_5", control_paths())

    def test_stack_entry_animation_is_detected_by_collection_index(self):
        path = ('nodes["Stack"].perceptual_grade_next_stack_controls.entries[2].'
                'settings.tone_fit')
        action = SimpleNamespace(fcurves=(SimpleNamespace(data_path=path),))
        animation = SimpleNamespace(action=action, nla_tracks=(), drivers=())
        self.assertEqual(unsupported_node_animation_paths(animation, 'nodes["Stack"]'),
                         (path,))

    def test_stack_reorder_queues_the_new_order_and_rejects_boundaries(self):
        class Entries(list):
            def move(self, source, destination):
                self.insert(destination, self.pop(source))

        entries = Entries(("first", "second", "third"))
        node = SimpleNamespace(perceptual_grade_next_stack_controls=SimpleNamespace(
            entries=entries
        ))
        queued = []
        mark_dirty = lambda owner: queued.append(owner) or True

        self.assertTrue(move_stack_entry(node, 1, 1, mark_dirty=mark_dirty))
        self.assertEqual(entries, ["first", "third", "second"])
        self.assertEqual(queued, [node])
        self.assertFalse(move_stack_entry(node, 0, -1, mark_dirty=mark_dirty))
        self.assertFalse(move_stack_entry(node, 1, 0, mark_dirty=mark_dirty))
        self.assertFalse(move_stack_entry(node, "1", 1, mark_dirty=mark_dirty))
        self.assertEqual(len(queued), 1)

    def test_failed_stack_reorder_preparation_restores_authored_order(self):
        class Entries(list):
            def move(self, source, destination):
                self.insert(destination, self.pop(source))

        entries = Entries(("first", "second"))
        node = SimpleNamespace(perceptual_grade_next_stack_controls=SimpleNamespace(
            entries=entries
        ))
        self.assertFalse(move_stack_entry(node, 0, 1, mark_dirty=lambda _node: False))
        self.assertEqual(entries, ["first", "second"])


if __name__ == "__main__":
    unittest.main()

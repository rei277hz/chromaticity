"""Build-only fixed Color topology shared by Grade and Stack compute emission."""

from .color_graph import ColorGraph
from ..kernel.stage2_parameters import (
    COLOR_FLAGS_SLOT, WEB_FLAGS_SLOT, COLOR_SCALARS_SLOT,
    COLOR_ROLE_FIELDS,
    ADAPTANCE_ANCHORS_SLOT, ADAPTANCE_SUPPORT_SLOT,
)


class ParameterColorGraph(ColorGraph):
    """Use runtime texels for authored choices; retain the canonical Color math.

    The composed adapter supplies ``parameters.sample(slot)`` and
    ``parameters.sample_field(role, table, coordinate, row)``. No emitter from
    this module is included in the extension package.
    """

    _color_full_topology = True

    @property
    def _color_energy_scale(self):
        # Compositor GPU Auto may transport node results through binary16.
        # Keep squared achromatic energy small while preserving J_A scale.
        return 4096.0 if self.tree.bl_idname == "CompositorNodeTree" else 1.0

    def _color_lanes(self, slot):
        color, alpha = self.parameters.sample(slot)
        return (*self.split(color), alpha)

    def _color_setting(self, name):
        index = {'global_gain': 0, 'adaptance_half_saturation': 1}[name]
        return self._color_lanes(COLOR_SCALARS_SLOT)[index]

    def _color_enabled(self, name):
        if name in ('lightness', 'chroma', 'adaptance', 'web'):
            return self._color_lanes(COLOR_FLAGS_SLOT)[
                ('lightness', 'chroma', 'adaptance', 'web').index(name)
            ]
        return self._color_lanes(WEB_FLAGS_SLOT)[
            ('hue_degrees', 'log_chroma', 'log_scale').index(name)
        ]

    def _color_adaptance_controls(self):
        return (self._color_lanes(ADAPTANCE_ANCHORS_SLOT),
                self._color_lanes(ADAPTANCE_SUPPORT_SLOT))

    def _color_height(self, table, h):
        high = self._color_lanes(COLOR_SCALARS_SLOT)[2]
        return self.mul(table.cells, self.clamp(self.div(h, high)))

    def sample_field(self, table, coordinate, row, *, interpolation='Linear'):
        for role, name in COLOR_ROLE_FIELDS.items():
            if table is getattr(self.prepared.color, name):
                return self.parameters.sample_field(role, table, coordinate, row)
        return super().sample_field(table, coordinate, row, interpolation=interpolation)

    @property
    def _color_source_squares_safe(self):
        return False

    @property
    def _color_safe(self):
        return False

    def _color_bounded(self, *names, limit=2.**120):
        return False

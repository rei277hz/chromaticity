"""Fast float32 execution of the emitted Color equations at extreme controls.

The adapter substitutes arithmetic and texture reads, while all Color and
H-K decisions remain the actual build-only implementation under test. It is
not a product pixel evaluator or a replacement for native graph acceptance.
"""

from dataclasses import asdict, replace
import math
from types import SimpleNamespace
import unittest

import numpy as np

from color_tools.kernel import prepare
from color_tools.template_build.graph import Graph
from color_tools.template_build.color_graph import ColorSockets
from color_tools.template_build.guard_graph import _retained_tone_responses
from color_tools.kernel import ColorSettings
from color_tools.kernel.settings import SPACES
from color_tools.perceptual_grade_reference import grading, model
from color_tools.perceptual_grade_reference.cube_guard import guard as cube_guard
from tools.perceptual_grade.reports import full_cases, oracle


class FloatGraph(Graph):
    """Round each scalar/vector operation exactly once to binary32."""

    def __init__(self, prepared):
        super().__init__(SimpleNamespace(bl_idname="ShaderNodeTree"), prepared)

    @staticmethod
    def f(value):
        return np.asarray(value, dtype=np.float32)

    def op(self, operation, *values):
        a = tuple(self.f(value) for value in values)
        with np.errstate(all="ignore"):
            functions = {
                "ADD": lambda: a[0] + a[1],
                "SUBTRACT": lambda: a[0] - a[1],
                "MULTIPLY": lambda: a[0] * a[1],
                "MULTIPLY_ADD": lambda: a[0].astype(float) * a[1].astype(float) + a[2],
                "DIVIDE": lambda: np.divide(*np.broadcast_arrays(a[0], a[1]),
                    out=np.zeros(np.broadcast_shapes(a[0].shape, a[1].shape), np.float32),
                    where=a[1] != 0),
                "ABSOLUTE": lambda: abs(a[0]),
                "MAXIMUM": lambda: np.maximum(a[0], a[1]),
                "MINIMUM": lambda: np.minimum(a[0], a[1]),
                "SQRT": lambda: np.sqrt(np.maximum(a[0], 0.)),
                "POWER": lambda: np.power(a[0], a[1]),
                "FLOOR": lambda: np.floor(a[0]),
                "SIGN": lambda: np.sign(a[0]),
                "LESS_THAN": lambda: a[0] < a[1],
                "COMPARE": lambda: abs(a[0] - a[1]) <= a[2],
                "SINE": lambda: np.sin(a[0]),
                "COSINE": lambda: np.cos(a[0]),
                "ARCTAN2": lambda: np.arctan2(a[0], a[1]),
                "FLOORED_MODULO": lambda: np.remainder(a[0], a[1]),
                "EXPONENT": lambda: np.exp(a[0]),
                "LOGARITHM": lambda: np.log(a[0]) / np.log(a[1]),
            }
            return self.f(functions[operation]())

    def clamp(self, value, low=0., high=1.):
        return self.f(np.clip(self.f(value), self.f(low), self.f(high)))

    def select(self, condition, yes, no):
        return self.f(np.where(self.f(condition) > 0., self.f(yes), self.f(no)))

    def vector(self, values):
        return np.stack(np.broadcast_arrays(*(self.f(value) for value in values)), axis=-1)

    def split(self, value):
        return tuple(self.f(value)[..., index] for index in range(3))

    def vop(self, operation, *values):
        if operation == "SCALE":
            return self.mul(values[0], self.f(values[1])[..., None])
        return self.op(operation, *values)

    def vselect(self, condition, yes, no):
        return self.select(self.f(condition)[..., None], yes, no)

    def vselect_components(self, condition, yes, no):
        return self.select(condition, yes, no)

    def sample_field(self, table, coordinate, row, *, interpolation="Linear"):
        # Match Graph's linear reads in pixel space, including segmented rows.
        x = self.f(coordinate)
        rows = self.f(row)
        if table.segments > 1:
            segment = self.minimum(table.segments - 1, self.op("FLOOR", self.div(x, table.segment_cells)))
            x = self.sub(x, self.mul(segment, table.segment_cells))
            rows = self.madd(rows, table.segments, segment)
        x, rows = np.broadcast_arrays(x, rows)
        left = np.floor(x).astype(int)
        fraction = self.sub(x, left)
        left = np.clip(left, 0, table.pixels.shape[1] - 1)
        right = np.minimum(left + 1, table.pixels.shape[1] - 1)
        rows = np.clip(np.rint(rows).astype(int), 0, table.pixels.shape[0] - 1)
        a, b = table.pixels[rows, left], table.pixels[rows, right]
        result = self.madd(self.sub(b, a), fraction[..., None], a)
        return tuple(result[..., index] for index in range(4))

def input_state(graph, toned):
    q = np.asarray(toned.q, np.float32)
    ja = np.asarray(toned.ja, np.float32)
    c = graph.hypot(q[..., 1], q[..., 2])
    e = graph.mul(ja, abs(ja))
    magnitude = graph.hypot(ja, graph.mul(math.sqrt(66.), graph.sqrt(c)))
    return ColorSockets(graph, q[..., 0], q[..., 1], q[..., 2], e, e,
        magnitude, c, e, 0., c,
        graph._color_offset(e, magnitude, graph.mul(math.sqrt(66.), graph.sqrt(c))), ja)


class ColorTransportTests(unittest.TestCase):
    def test_retained_tone_decode_requires_semantic_color_and_hk_identity(self):
        class ResponseGraph(FloatGraph):
            flags = {}

            def _color_enabled(self, name):
                return float(self.flags.get(name, False))

            def dot(self, vector, row):
                return self.f(np.sum(self.f(vector) * self.f(row), axis=-1))

        graph = ResponseGraph(prepare())
        tone = SimpleNamespace(J_A=np.array((1., 0., -1., -1.)),
            H=np.array((1., 0., -1., 1.)), achromatic=3.05, raw_a=0., raw_b=0.)
        retain, responses = _retained_tone_responses(graph, tone)
        np.testing.assert_array_equal(retain, (1., 1., 1., 0.))
        np.testing.assert_allclose(responses, (1., 1., 1.), atol=1e-7)
        # Any active authored family, including final Web Scale, requires the
        # actual Color output even if a rounded energy happens to be unchanged.
        for name in ('adaptance', 'web'):
            with self.subTest(active=name):
                graph.flags = {name: True}
                retain, _ = _retained_tone_responses(graph, tone)
                np.testing.assert_array_equal(retain, 0.)

    def test_unchanged_half_energy_keeps_original_achromatic_coordinate(self):
        class HalfGraph(FloatGraph):
            @staticmethod
            def f(value):
                # The live GPU's half-image stores truncate these carriers.
                # Keep arithmetic in float32, then materialize that half value.
                source = np.asarray(value, dtype=np.float32)
                with np.errstate(all="ignore"):
                    rounded = source.astype(np.float16)
                    overshot = abs(rounded.astype(np.float32)) > abs(source)
                    rounded = np.where(overshot,
                        np.nextafter(rounded, np.float16(0.)), rounded)
                return rounded.astype(np.float32)

            @property
            def _color_energy_scale(self):
                return 4096.

            def _color_bounded(self, *_names, **_kwargs):
                return False

        graph = HalfGraph(prepare())
        ja = graph.f(522.)  # Measured live GPU Auto post-Tone coordinate.
        normalized = graph.div(ja, 64.)
        energy = graph.mul(normalized, normalized)
        state = ColorSockets(graph, ja, 0., 0., energy, energy, ja, 0., energy,
                             chroma_value=0., ja_value=ja)
        with np.errstate(all="ignore"):
            self.assertNotEqual(replace(state, ja_value=None).J_A, ja)
            self.assertEqual(state.J_A, ja)
            self.assertEqual(graph.hk_guard(state).J_A, ja)
            changed = graph._color_scale(state, 2.)
            self.assertEqual(changed.J_A, graph.mul(ja, 2.))

            tiny_ja = graph.f(.001)
            tiny_energy = graph.mul(graph.div(tiny_ja, 64.), graph.div(tiny_ja, 64.))
            self.assertEqual(tiny_energy, 0.)
            tiny = replace(state, H=tiny_ja, energy=tiny_energy,
                           reference_energy=tiny_energy, ja_value=tiny_ja)
            scaled = graph._color_scale(tiny, 2.)
            self.assertEqual(scaled.energy, tiny_energy)
            self.assertEqual(scaled.J_A, graph.mul(tiny_ja, 2.))
            self.assertNotEqual(scaled.J_A, tiny.J_A)

    def test_unselected_small_change_height_candidate_stays_finite(self):
        class EagerMixGraph(FloatGraph):
            def select(self, condition, yes, no):
                # Native Mix can evaluate both branches and propagate a NaN
                # from an unselected candidate through zero multiplication.
                values = (self.f(yes), self.f(no))
                for value in values:
                    if not np.isfinite(value).all():
                        raise AssertionError("Nonfinite eager Mix candidate")
                return super().select(condition, *values)

        graph = EagerMixGraph(prepare())
        state = ColorSockets(graph, 10., .6, .8, -1., -1., 10., 1., -1.,
                             chroma_value=1.)
        for opponent_scale in (1., 1e-20):
            with self.subTest(opponent_scale=opponent_scale):
                result = graph._color_adaptance_height(state, 7., 1e-30,
                    opponent_scale, 1., 1e38, 1e38, -1e38, 0.)
                self.assertEqual(result, 7.)

    def test_adaptance_support_preserves_exact_zero_intervals_and_anchor_values(self):
        for bits in range(16):
            flags = np.array(tuple(float(bool(bits & (1 << index))) for index in range(4)))
            rows = tuple((flag * 1e-20, 0.) for flag in flags)
            prepared = prepare(color=ColorSettings(adaptance=rows))
            graph = FloatGraph(prepared)
            anchors = np.asarray(prepared.color.anchors, np.float32)
            heights = np.r_[0., anchors, (anchors[:-1] + anchors[1:]) / 2., anchors[-1] * 2.]
            expected = np.r_[flags[0], flags, np.maximum(flags[:-1], flags[1:]), flags[-1]]
            with self.subTest(active_rows=bits):
                np.testing.assert_array_equal(graph._color_adaptance_support(heights), expected)

    def test_extreme_stage_transport_matches_independent_guard_before_scale(self):
        corpus = [row for row in full_cases.grades()
                  if row[0] in ("saturation", "all_active_saturation")]
        corpus += [row for row in full_cases.ui_boundaries()
                   if row[0] in ("all_families_max", "all_families_max_active_tail")]
        for space in SPACES:
            for name, linear, tone, color in corpus:
                with self.subTest(case=name, space=space):
                    values = full_cases.rgba(space, 256)[:, :3]
                    expected = oracle.evaluate_full(values, linear, tone, color, space)
                    lp, tp = oracle.parameters(linear, tone)
                    reference = model.Model(model.Settings(linear=lp, tone=tp,
                        color=grading.ColorSettings(**asdict(color))), space)
                    prepared = prepare(linear, tone, space, color=color)
                    graph = FloatGraph(prepared)
                    state = input_state(graph, expected["tone"])
                    state, scale, scale_flag = graph._color_web(state)
                    before_adaptance = state
                    state = graph._color_adaptance(state)
                    inactive = graph._color_adaptance_support(state.tonal_h) == 0.
                    for field in ("H", "a", "b", "energy"):
                        value = getattr(state, field)
                        self.assertTrue(np.isfinite(value).all(), field)
                        np.testing.assert_array_equal(value[inactive],
                            getattr(before_adaptance, field)[inactive], err_msg=field)
                    repaired = graph.hk_guard(state)
                    state = replace(state, H=repaired.H, a=repaired.a, b=repaired.b,
                        energy=repaired.energy, chroma_value=repaired.chroma, offset_value=None,
                        ja_value=repaired.J_A)
                    actual = graph._color_scale(state, scale, scale_flag)
                    self.assertTrue(np.isfinite(actual.q).all())
                    self.assertTrue(np.isfinite(actual.energy).all())
                    _, _, native = cube_guard(oracle.exact_boundary(reference), actual.q.astype(float),
                                               actual.energy.astype(float))
                    output = native[..., 1, None] + (native - native[..., 1, None]) @ expected["to_scene"].T
                    result = oracle.metrics(output, expected["rgb"])
                    self.assertLessEqual(result["max_normalized"], 1e-4, result)


if __name__ == "__main__":
    unittest.main()

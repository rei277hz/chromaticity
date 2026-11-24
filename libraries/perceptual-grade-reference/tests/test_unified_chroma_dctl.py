"""Compare the reference stage with the compiled Unified Chroma DCTL."""
from dataclasses import replace
import unittest

import numpy as np

from color_tools.perceptual_grade_reference.unified_chroma import UnifiedChroma, UnifiedChromaSettings
from tests.support import cone_reference as cone, oracle


class UnifiedChromaDCTLTests(unittest.TestCase):
    def test_matches_compiled_stage_on_signed_cone_wire(self):
        points = np.array([
            [0., 0., 0.], [-40., 0., 0.], [56., 0., 0.], [0., 12., -16.],
            [-52., 12., 23.], [25., -10., -17.], [170., 28., -41.], [1.e-4, 2.e-6, -1.e-5],
        ])
        wire = cone.pack(*points.T).astype("f4")
        chart = cone.enter(wire)
        inputs = np.column_stack([chart.ja, chart.q[:, 1:]])
        controls = dict(inputShadows=2.4, inputMidtones=42., inputWhite=225., inputHighlights=1600.,
                        blackCompression=1.1, cMutedGain=-1.3, cVividGain=1.7,
                        cSaturationCrossover=.22, shadowChroma=1.5, highlightChroma=-1.3,
                        cToneCrossover=35.)
        settings = UnifiedChromaSettings(
            input_nits=(2.4, 42., 225., 1600.), black_compression_nits=1.1,
            muted_gain=-1.3, vivid_gain=1.7, saturation_crossover=.22,
            shadow_chroma=1.5, highlight_chroma=-1.3, tone_crossover=35.,
        )
        for peak_index, peak in enumerate((500, 1000, 2000, 4000)):
            for fit in (-2, 0, 2):
                stage = UnifiedChroma(replace(settings, peak_nits=peak, fit=fit))
                for direction, evaluate in enumerate((stage.forward, stage.inverse)):
                    with self.subTest(peak=peak, fit=fit, direction=direction):
                        expected = cone.pack(*evaluate(inputs).T)
                        actual = oracle.run(
                            "jc_tone_fit_unified_chroma", wire,
                            dict(controls, peakNits=peak_index, remapFit=fit, direction=direction),
                        )
                        error = np.max(abs(actual - expected), axis=-1)
                        limit = np.maximum(2.e-4 * np.max(abs(expected), axis=-1), 1.e-7)
                        self.assertTrue(np.all(error <= limit), (error, limit))

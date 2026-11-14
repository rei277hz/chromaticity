"""Compare complete Grade instantiation with the procedural build baseline."""

import json
import statistics
import time
import unittest

import bpy

from color_tools.kernel.node_templates import instantiate_grade
from color_tools.template_build.stage2_graph import build_stage2_group

from .template_support import SPACES, TREE_TYPES, complete_prepared


class TemplateTimingTests(unittest.TestCase):
    def test_five_complete_creations_per_grade_variant_are_at_least_five_times_faster(self):
        report = {"blender": list(bpy.app.version), "samples_per_variant": 5,
                  "variants": []}
        try:
            for space in SPACES:
                prepared = complete_prepared(space, adjusted=True)
                for tree_type in TREE_TYPES:
                    bpy.ops.wm.read_factory_settings(use_empty=True)
                    procedural, template = [], []
                    for _ in range(5):
                        for builder, samples in ((build_stage2_group, procedural),
                                                 (instantiate_grade, template)):
                            started = time.perf_counter()
                            built = builder(prepared, tree_type)
                            samples.append(time.perf_counter() - started)
                            built.dispose()
                    speedup = statistics.median(procedural) / statistics.median(template)
                    record = {"space": space, "tree_type": tree_type,
                              "procedural_seconds": procedural,
                              "template_seconds": template, "median_speedup": speedup}
                    report["variants"].append(record)
                    self.assertGreaterEqual(speedup, 5.0, record)
        finally:
            bpy.ops.wm.read_factory_settings(use_empty=True)
            print("Template creation timing: " + json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    unittest.main()

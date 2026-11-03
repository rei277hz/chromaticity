"""Retain every independent local Color gate for the persistent graph builder."""
from functools import partial
from pathlib import Path
import hashlib
import unittest

from color_tools.kernel.persistent import _PersistentGraph
from . import test_color_stages as stages


class PersistentColorStageTests(stages.ColorStageTests):
    persistent_routes = True

    @classmethod
    def source_identity(cls):
        return dict(super().source_identity(), persistent_test_sha256=
                    hashlib.sha256(Path(__file__).read_bytes()).hexdigest())

    @classmethod
    def setUpClass(cls):
        cls.original_graph, cls.original_prepare = stages.color_local.Graph, stages.prepare
        stages.color_local.Graph = _PersistentGraph
        stages.prepare = partial(stages.prepare, full_fields=True)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            stages.color_local.Graph, stages.prepare = cls.original_graph, cls.original_prepare


if __name__ == '__main__':
    unittest.main()

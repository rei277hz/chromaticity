"""Reference accelerated Grade kernel with the reference Stage 3 ordering."""

import hashlib

import numpy as np

from ..perceptual_grade_core.model.bake import Kernel as _Kernel
from .grading import CHROMA_CROSSOVER, Color
from .responses import State


class Kernel(_Kernel):
    """Use the reference Color implementation for accelerated Grade rows."""

    def __init__(self, data, tone, color, table=None, *, hk_guard=True):
        self.color_model = (color if color.hk_guard == bool(hk_guard) else
                            Color(color.settings, tone, color.boundary, hk_guard=hk_guard))
        super().__init__(data, tone, color, table, hk_guard=hk_guard)
        self.resource_key = hashlib.sha256(
            self.resource_key.encode("ascii") + b"reference-warp-v3"
        ).hexdigest()

    def grade(self, state, tonal=None):
        q = np.asarray(state, dtype=np.float32)
        result = self.color_model.apply_state(State(q[..., :3], q[..., 3]))
        return np.concatenate((result.q, np.asarray(result.energy)[..., None]), -1).astype("f4")

    def export(self, state, reference=None):
        """Export by cube containment only; grading already performed repair."""
        return super().export(state, None)

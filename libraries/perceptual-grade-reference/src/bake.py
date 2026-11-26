"""Reference accelerated Grade kernel with post-Tone Unified Chroma."""

import hashlib

import numpy as np

from ..perceptual_grade_core.model.bake import Kernel as _Kernel
from ..perceptual_grade_core.model.bake_inverse import Inverse as _Inverse
from .export import OutputCompressionSettings, compress_saturation
from .grading import Color
from .responses import HK, State, signed_hk
from .unified_chroma import radial_gain


def _signed_ja(state):
    energy = state[..., 3]
    return np.sign(energy) * np.sqrt(abs(energy))


def _appearance_state(ja, ab, energy):
    h = signed_hk(ja, np.hypot(ab[..., 0], ab[..., 1]))
    return np.concatenate((h[..., None], ab, energy[..., None]), axis=-1)


def _scale_ray(state, ja, chroma, source_height, target_height):
    # Normalize the quadratic by the incoming squared H-K height.
    valid = source_height > 0
    ratio = np.divide(target_height, source_height, out=np.zeros_like(target_height), where=valid)
    j = np.divide(ja, source_height, out=np.zeros_like(ja), where=valid)
    c = np.divide(np.sqrt(np.float32(HK) * chroma), source_height,
                  out=np.zeros_like(chroma), where=valid)**2
    denominator = np.hypot(c, 2 * j * ratio) + c
    gain = np.divide(2 * ratio * ratio, denominator,
                     out=np.ones_like(ratio), where=denominator > 0)
    ja = np.where(chroma == 0, np.copysign(target_height, ja), ja * gain)
    mapped = _appearance_state(ja, state[..., 1:3] * gain[..., None], ja * abs(ja))
    return np.where(valid[..., None], mapped, state)


class Kernel(_Kernel):
    """Use the reference Color implementation for accelerated Grade rows."""

    def __init__(self, data, tone, color, table=None, *, hk_guard=True, tone_chroma=None,
                 output_compression=OutputCompressionSettings()):
        self.color_model = (color if color.hk_guard == bool(hk_guard) else
                            Color(color.settings, tone, color.boundary, hk_guard=hk_guard))
        self.tone_chroma = tone_chroma
        self.output_compression = output_compression
        super().__init__(data, tone, color, table, hk_guard=hk_guard)
        key = self.resource_key.encode("ascii") + b"reference-warp-v3"
        if tone_chroma is not None:
            p = tone_chroma.settings
            controls = (p.muted_gain, p.vivid_gain, p.saturation_crossover,
                        p.shadow_chroma, p.highlight_chroma, p.tone_crossover)
            key += b"unified-chroma-v3" + np.asarray(controls, dtype="<f8").tobytes()
            self.identity = self.identity and not tone_chroma.chroma_active
        if output_compression.enabled:
            key += b"output-saturation-v1" + np.asarray(
                (output_compression.knee, output_compression.ceiling), dtype="<f8").tobytes()
        self.resource_key = hashlib.sha256(key).hexdigest()

    def _chroma_state(self, state, ja, *, invert=False):
        if not self.tone_chroma.chroma_active:
            return state
        ab = state[..., 1:3]
        chroma = np.hypot(ab[..., 0], ab[..., 1])
        gain = np.asarray(self.tone_chroma.chroma_gain(ja, chroma, invert=invert), dtype="f4")
        result = _appearance_state(ja, ab * gain[..., None], state[..., 3])
        return np.where(((gain == 1) | (chroma == 0))[..., None], state, result)

    def tone_state(self, state):
        if self.tone_chroma is None:
            return super().tone_state(state)
        q = np.asarray(state, dtype="f4")
        ja = _signed_ja(q)
        tone = self.tone
        if not tone.active:
            return self._chroma_state(q, ja).copy()

        chroma = np.hypot(q[..., 1], q[..., 2])
        height = np.hypot(ja, np.sqrt(np.float32(HK) * chroma))
        normalized = height / 100
        compressed = normalized * radial_gain(normalized, np.float32(2 * tone.black), .5, 1.)
        t = compressed / np.float32(tone.span)
        k = self.tone_curve.evaluate(t)
        out = 100 * (np.float32(tone.slope) * t + np.sum(k * self.tone_curve_residual, axis=-1))
        out = np.where(t == 1, np.float32(tone.high), out)
        q = _scale_ray(q, ja, chroma, height, out)
        return self._chroma_state(q, _signed_ja(q))

    def grade(self, state, tonal=None):
        q = np.asarray(state, dtype=np.float32)
        result = self.color_model.apply_state(State(q[..., :3], q[..., 3]))
        return np.concatenate((result.q, np.asarray(result.energy)[..., None]), -1).astype("f4")

    def export(self, state, reference=None):
        """Project raw appearance to AP1, including inverse candidates and handoffs."""
        return super().export(state, None)

    def final_export(self, state, native=None):
        """Compress a terminal state, retaining the supplied native RGB on exact identity."""
        original = State(state[..., :3], state[..., 3])
        mapped = compress_saturation(original, self.output_compression)
        if native is None:
            return self.export(np.concatenate((mapped.q, state[..., 3:]), axis=-1))
        unchanged = np.all(mapped.q[..., 1:] == original.q[..., 1:], axis=-1)
        keep = unchanged & np.all((native >= 0.) & (native <= 1024.), axis=-1)
        out = native.copy()
        if not np.all(keep):
            rows = np.concatenate((mapped.q[~keep], state[..., 3:][~keep]), axis=-1)
            out[~keep] = self.export(rows)
        return out

    def evaluate(self, rgb):
        if not self.output_compression.enabled:
            return super().evaluate(rgb)
        rgb = np.asarray(rgb, dtype=np.float32)
        entered = self.enter(rgb)
        if self.identity:
            return self.final_export(entered, rgb)
        return self.final_export(self.grade(self.tone_state(entered)))


class Inverse(_Inverse):
    """Reconstruct input appearance from a pre-Warp inverse candidate."""

    def undo_tone(self, q):
        kernel = self.kernel
        if kernel.tone_chroma is None:
            return super().undo_tone(q)
        q = np.asarray(q, dtype="f4")
        ja = _signed_ja(q)
        q = kernel._chroma_state(q, ja, invert=True)
        tone = kernel.tone
        if tone.active:
            if self.tone_table is None:
                raise RuntimeError("Prepare the inverse tone table before evaluating pixels")
            chroma = np.hypot(q[..., 1], q[..., 2])
            height = np.hypot(ja, np.sqrt(np.float32(HK) * chroma))
            t = np.where(height == np.float32(tone.high), np.float32(1.),
                         self.tone_table.evaluate(height))
            compressed = np.float32(tone.span) * t
            original = 100 * compressed * radial_gain(compressed, np.float32(2 * tone.black),
                                                      .5, 1., invert=True)
            q = _scale_ray(q, ja, chroma, height, original)
        return q.copy()

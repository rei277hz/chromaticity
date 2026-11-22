"""Independent float64 maps for the saturation-preserving cone J/C prototypes."""
import numpy as np

from . import cone_reference as cone, jc_surface
from .cone_color import integrate_stretch


def saturation(chroma, height):
    total = chroma + (35. / 75.) * height
    return np.divide(chroma, total, out=np.zeros_like(chroma), where=total > 0.)


def invert_radius(target, forward):
    # Both maps have gains in [1/4, 4] at every radius for the allowed stops.
    low, high = target / 4., target * 4.
    for _ in range(56):
        middle = .5 * (low + high)
        below = forward(middle) < target
        low, high = np.where(below, middle, low), np.where(below, high, middle)
    return .5 * (low + high)


def apply(stage, wire, tone, settings):
    point = cone.enter(wire)
    ja, ab = point.ja, point.q[:, 1:]
    anchors = 100. * tone.target[1:]
    c_amounts = [settings.get(f"tone{row}CGain", 0.) for row in "SMWH"]
    j_amounts = [settings.get(f"tone{row}JContrast", 0.) for row in "SMWH"]
    inverse = settings.get("direction", 0)

    def apply_c(ja, ab):
        c = np.linalg.norm(ab, axis=-1)
        amount = jc_surface.anchor(abs(ja), anchors, np.array(c_amounts))

        def forward(radius):
            s = saturation(radius, abs(ja))
            q = 9. * s / (1. + 8. * s)
            if stage == "jc_log_gain":
                return radius * np.exp2(amount * q)
            return radius * ((1. - q) + np.exp2(amount) * q)

        mapped = invert_radius(c, forward) if inverse else forward(c)
        gain = np.divide(mapped, c, out=np.ones_like(c), where=c > 0.)
        return ab * gain[:, None]

    def apply_j(ja, ab):
        height = abs(ja)
        s = saturation(np.linalg.norm(ab, axis=-1), height)
        fade = jc_surface.smoothstep(s / .10)
        slopes = np.column_stack([np.ones_like(s), np.exp2(fade[:, None] * j_amounts)])
        knots = np.r_[0., anchors]

        def forward(radius):
            return integrate_stretch(radius, knots, slopes)

        mapped = invert_radius(height, forward) if inverse else forward(height)
        gain = np.divide(mapped, height, out=np.ones_like(height), where=height > 0.)
        return ja * gain, ab * gain[:, None]

    if inverse:
        ja, ab = apply_j(ja, ab)
        ab = apply_c(ja, ab)
    else:
        ab = apply_c(ja, ab)
        ja, ab = apply_j(ja, ab)
    return cone.pack(ja, ab[:, 0], ab[:, 1])

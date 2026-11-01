"""Current-reference Grade evaluation with signed input and guarded export."""

from dataclasses import dataclass
import numpy as np

from .._shared import linear as color_linear, modcam16

D65 = color_linear.D65
CAT16 = np.asarray(color_linear.CAT16, dtype=np.float64)
ICAT16 = np.asarray(color_linear.ICAT16, dtype=np.float64)

from ..settings import GradeSettings
from .grading import Color, Tone
from .hk_guard import GradedState, guard as hk_guard
from .linear import rgb_xyz_matrices, xyz_matrix


MAX_RGB = 1024.0


@dataclass(frozen=True)
class GradeResult:
    rgb: np.ndarray
    appearance: modcam16.State
    export_appearance: modcam16.State


class CubeBoundary:
    """Exact decoder-backed radial projection into the AP1 output cube."""

    def __init__(self, fl, aw, gamma):
        self.fl, self.aw, self.gamma = float(fl), float(aw), float(gamma)
        p = (self.fl * MAX_RGB) ** 0.42
        self.response_white = 400.0 * p / (27.13 + p)
        self.white = 100.0 * (3.05 * self.response_white / self.aw) ** self.gamma
        self.cones_to_xyz = np.linalg.inv(CAT16) @ np.diag(CAT16 @ _d65_xyz())
        ap1_to_xyz, _ = rgb_xyz_matrices("ACEScg")
        self.xyz_to_ap1 = np.linalg.inv(ap1_to_xyz)
        self.matrix = self.xyz_to_ap1 @ self.cones_to_xyz
        self.matrix[:, 1] = 1.0 - self.matrix[:, 0] - self.matrix[:, 2]

    def decode(self, q, energy):
        q = np.asarray(q, dtype=np.float64)
        energy = np.broadcast_to(np.asarray(energy, dtype=np.float64), q.shape[:-1])
        if q.shape[-1:] != (3,) or not np.isfinite(q).all() or not np.isfinite(energy).all():
            raise ValueError("Cube decode requires finite appearance triples and energy")
        chroma = np.hypot(q[..., 1], q[..., 2])
        hue = np.arctan2(q[..., 2], q[..., 1])
        opponent = q[..., 1:] * (
            self.aw / (1204.0 * modcam16.eccentricity(hue))
        )[..., None]
        # ``achromatic_response`` returns the weighted A component.  A neutral
        # cone response is A/3.05 because inverse opponent decoding maps the
        # common A term through INVERSE[:, 0].
        neutral = modcam16.achromatic_response(energy, self.aw) * modcam16.INVERSE[0, 0]
        responses = (neutral[..., None]
                     + opponent[..., 0, None] * modcam16.INVERSE[:, 1]
                     + opponent[..., 1, None] * modcam16.INVERSE[:, 2])
        pole = np.abs(responses) >= 400.0
        if np.any(pole):
            raise ValueError("Appearance decode reached a response pole")
        magnitude = (np.abs(responses) * (400.0 - self.response_white)
                     / (self.response_white * (400.0 - np.abs(responses))))
        cones = np.sign(responses) * MAX_RGB * magnitude ** (50.0 / 21.0)
        result = cones[..., 1, None] + (cones - cones[..., 1, None]) @ self.matrix.T

        # At the bright end, the reference decoder evaluates the bounded
        # complement form to avoid subtracting nearly equal 1024-valued
        # channels.  Apply it only where all opponent deficits are physical;
        # other signed rows retain the ordinary inverse response path.
        position = np.sign(energy) * (np.sqrt(np.abs(energy)) / self.white) ** (1.0 / self.gamma)
        position_flat = np.asarray(position).reshape(-1)
        active = np.flatnonzero(np.asarray((energy > 0.0) & (position > 0.5)).reshape(-1))
        if len(active):
            rows = q.reshape(-1, 3)[active]
            hues = np.arctan2(rows[:, 2], rows[:, 1])
            opponent_rows = rows[:, 1:] * (
                self.aw / (1204.0 * modcam16.eccentricity(hues))
            )[:, None]
            deficits = (1.0 - position_flat[active, None]) - (
                opponent_rows @ modcam16.INVERSE[:, 1:].T
            ) / self.response_white
            valid = np.all(deficits <= 1.0, axis=-1)
            if np.any(valid):
                selected = result.reshape(-1, 3)[active]
                d = deficits[valid]
                bounded_cones = -MAX_RGB * np.expm1(
                    (50.0 / 21.0)
                    * (np.log1p(-d) - np.log1p(
                        self.response_white / (400.0 - self.response_white) * d
                    ))
                )
                selected[valid] = MAX_RGB - (
                    bounded_cones[:, 1, None]
                    + (bounded_cones - bounded_cones[:, 1, None]) @ self.matrix.T
                )
                result.reshape(-1, 3)[active] = selected
        return result

    def guard(self, q, energy):
        q = np.asarray(q, dtype=np.float64)
        energy = np.broadcast_to(np.asarray(energy, dtype=np.float64), q.shape[:-1])
        if q.shape[-1:] != (3,) or not np.isfinite(q).all() or not np.isfinite(energy).all():
            raise ValueError("Cube guard requires finite appearance triples and energy")
        rows, energies = q.reshape(-1, 3), energy.reshape(-1)
        out_q, out_e = rows.copy(), energies.copy()
        rgb = np.zeros_like(rows)
        white_rows = energies >= self.white * self.white
        out_q[energies <= 0.0] = 0.0
        out_e[energies <= 0.0] = 0.0
        out_q[white_rows] = (self.white, 0.0, 0.0)
        out_e[white_rows] = self.white * self.white
        rgb[white_rows] = MAX_RGB
        active = np.flatnonzero((energies > 0.0) & ~white_rows)
        for index in active:
            row, value = rows[index], energies[index]
            try:
                decoded = self.decode(row, value)
            except ValueError:
                decoded = np.full(3, np.nan)
            if np.isfinite(decoded).all() and np.all((decoded >= 0.0) & (decoded <= MAX_RGB)):
                rgb[index] = decoded
                continue
            chroma = float(np.hypot(row[1], row[2]))
            if chroma == 0.0:
                raise ArithmeticError("An interior neutral must decode inside the AP1 cube")
            unit = row[1:] / chroma
            ja = np.sqrt(value)
            low, high = 0.0, chroma
            accepted_q = np.asarray((ja, 0.0, 0.0))
            accepted_rgb = self.decode(accepted_q, value)
            for _ in range(56):
                middle = low + (high - low) / 2.0
                if middle == low or middle == high:
                    break
                trial_q = np.asarray((modcam16.signed_hk(ja, middle), *(unit * middle)))
                try:
                    trial_rgb = self.decode(trial_q, value)
                    legal = np.isfinite(trial_rgb).all() and np.all(
                        (trial_rgb >= 0.0) & (trial_rgb <= MAX_RGB)
                    )
                except ValueError:
                    legal = False
                if legal:
                    low, accepted_q, accepted_rgb = middle, trial_q, trial_rgb
                else:
                    high = middle
            out_q[index], out_e[index], rgb[index] = accepted_q, value, accepted_rgb
        shape = q.shape
        return out_q.reshape(shape), out_e.reshape(energy.shape), rgb.reshape(shape)


def _d65_xyz():
    return np.asarray(color_linear.xyz(D65), dtype=np.float64)


class GradeModel:
    """Complete forward Grade model for Stack evaluation and conformance tests."""

    def __init__(self, settings=GradeSettings()):
        if not isinstance(settings, GradeSettings):
            raise ValueError("settings must be GradeSettings")
        self.settings = settings
        self.rgb_to_xyz, self.xyz_to_rgb = rgb_xyz_matrices(settings.working_space)
        self.stage1 = xyz_matrix(settings.linear)
        self.fl, self.aw = modcam16.viewing(settings.tone.reference_nits)
        self.gamma = modcam16.GAMMA
        self.white_xyz = _d65_xyz()
        self.cones_to_xyz = np.linalg.inv(CAT16) @ np.diag(CAT16 @ self.white_xyz)
        self.xyz_to_cones = np.linalg.inv(self.cones_to_xyz)
        self.tone = Tone(settings.tone)
        self.color = Color(settings.color, self.tone, self._boundary)
        self._cube = None

    @property
    def boundary(self):
        if self._cube is None:
            self._cube = CubeBoundary(self.fl, self.aw, self.gamma)
        return self._cube

    def encode(self, rgb):
        values = np.asarray(rgb, dtype=np.float64)
        if values.shape[-1:] != (3,) or not np.isfinite(values).all():
            raise ValueError("Grade input must contain finite RGB triples")
        xyz = values @ self.rgb_to_xyz.T
        xyz = xyz @ self.stage1.T
        cones = xyz @ self.xyz_to_cones.T
        appearance = modcam16.encode_cones(cones, constants=(self.fl, self.aw))
        return modcam16.State(appearance.q, appearance.ja * np.abs(appearance.ja))

    def enter_ap1(self, rgb):
        """Encode AP1 samples to raw appearance without repairing signed input."""
        values = np.asarray(rgb, dtype=np.float64)
        if values.shape[-1:] != (3,) or not np.isfinite(values).all():
            raise ValueError("AP1 input must contain finite RGB triples")
        ap1_to_xyz, _ = rgb_xyz_matrices("ACEScg")
        cones = values @ ap1_to_xyz.T @ self.xyz_to_cones.T
        appearance = modcam16.encode_cones(cones, constants=(self.fl, self.aw))
        return modcam16.State(appearance.q, appearance.ja * np.abs(appearance.ja))

    def evaluate(self, rgb):
        source = self.encode(rgb)
        toned = self.tone.apply(modcam16.Appearance(source.q, source.ja))
        energy = toned.ja * np.abs(toned.ja)
        if not self.tone.active:
            energy = source.energy.copy()
        graded = self.color.apply_state(modcam16.State(toned.q, energy))
        export = GradedState(graded.q, graded.energy, energy)
        repaired_q, repaired_energy = hk_guard(export.q, export.energy, export.reference_energy)
        guarded_q, guarded_energy, ap1 = self.boundary.guard(repaired_q, repaired_energy)
        ap1_to_d65_xyz, _ = rgb_xyz_matrices("ACEScg")
        xyz = ap1 @ ap1_to_d65_xyz.T
        output = xyz @ self.xyz_to_rgb.T
        return GradeResult(output, source, modcam16.State(guarded_q, guarded_energy))

    def apply_rgb(self, rgb):
        return self.evaluate(rgb).rgb

    def apply(self, rgb):
        return self.apply_rgb(rgb)

    def grade_state(self, state):
        """Apply Tone and Color to a raw appearance handoff without RGB repair."""
        state = modcam16.State(np.asarray(state.q, dtype=np.float64),
                               np.asarray(state.energy, dtype=np.float64))
        ja = state.ja
        toned = self.tone.apply(modcam16.Appearance(state.q, ja))
        reference = toned.ja * np.abs(toned.ja) if self.tone.active else state.energy.copy()
        graded = self.color.apply_state(modcam16.State(toned.q, reference))
        return GradedState(graded.q, graded.energy, reference)

    def grade_ap1(self, rgb):
        """Evaluate Tone/Color for AP1 input, preserving the raw Stack handoff."""
        return self.grade_state(self.enter_ap1(rgb))

    def release_ap1(self, state, guard=True):
        """Decode a raw Stack handoff to AP1; forward output applies both guards."""
        q, energy = np.asarray(state.q, dtype=np.float64), np.asarray(state.energy, dtype=np.float64)
        if guard:
            q, energy = hk_guard(q, energy, getattr(state, "reference_energy", energy))
            return self.boundary.guard(q, energy)
        return q, energy, self.boundary.decode(q, energy)

    def apply_ap1(self, rgb, *, apply_linear=True):
        """Apply one forward stage to AP1 values, with the stage's XYZ matrix."""
        values = np.asarray(rgb, dtype=np.float64)
        if values.shape[-1:] != (3,) or not np.isfinite(values).all():
            raise ValueError("AP1 input must contain finite RGB triples")
        if apply_linear:
            ap1_to_xyz, _ = rgb_xyz_matrices("ACEScg")
            xyz = values @ ap1_to_xyz.T
            xyz = xyz @ self.stage1.T
            values = xyz @ np.linalg.inv(ap1_to_xyz).T
        state = self.grade_ap1(values)
        return self.release_ap1(state, guard=True)[2]

    @property
    def stage1_ap1_matrix(self):
        ap1_to_xyz, xyz_to_ap1 = rgb_xyz_matrices("ACEScg")
        return xyz_to_ap1 @ self.stage1 @ ap1_to_xyz

    def export_state(self, state):
        """Apply the Grade export guards and return the accepted AP1 RGB output."""
        reference = getattr(state, "reference_energy", state.energy)
        q, energy = hk_guard(state.q, state.energy, reference)
        return self.boundary.guard(q, energy)

    def _boundary(self):
        return self.boundary

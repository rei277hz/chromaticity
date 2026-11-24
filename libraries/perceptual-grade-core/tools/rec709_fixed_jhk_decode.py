"""Raw Rec.709 fixed-J_HK decoding and bounds for its binary calibration."""

import numpy as np

from color_tools.color_core import linear, modcam16
from tools.build.appearance_certificate import I, trig
from tools.build.spindle_certificate import power


HEIGHT = 99.9
REFERENCE_NITS = 203
_COSINE = (-.0582, -.0258, -.1347, .0289)
_SINE = (-.1475, -.0308, .0385, .0096)
_POWER = I(1) / (2 * modcam16.GAMMA)
_ENERGY_SCALE = I(modcam16.HK) / 10000


def _stack(values):
    return I(np.stack([value.lo for value in values], axis=-1),
             np.stack([value.hi for value in values], axis=-1))


def _inverse(matrix):
    cofactors = [
        [
            matrix[(i + 1) % 3][(j + 1) % 3] * matrix[(i + 2) % 3][(j + 2) % 3]
            - matrix[(i + 1) % 3][(j + 2) % 3] * matrix[(i + 2) % 3][(j + 1) % 3]
            for j in range(3)
        ]
        for i in range(3)
    ]
    determinant = sum(matrix[0][j] * cofactors[0][j] for j in range(3))
    return tuple(tuple(cofactors[j][i] / determinant for j in range(3)) for i in range(3))


def _rgb_matrix():
    wc = linear.mv(linear.CAT16, linear.xyz(linear.D65))
    xyz = linear.rgb_to_xyz('Linear Rec.709')
    cones = linear.mm(linear.CAT16, xyz)
    # Anchor the neutral axis exactly using the first and last coefficients.
    rows = tuple((row[0] / white, row[2] / white) for row, white in zip(cones, wc))
    floating = tuple((l, 1 - l - r, r) for l, r in rows)
    enclosed = tuple((I(l), I(1) - l - r, I(r)) for l, r in rows)
    if any(value.lo <= 0 for row in enclosed for value in row):
        raise ValueError('The Rec.709 cone transform must have positive coefficients')
    return np.asarray(linear.inverse(floating)), _inverse(enclosed)


class Decoder:
    """Decode the physical achromatic branch at a positive fixed J_HK."""

    def __init__(self, height=HEIGHT):
        self.height = float(height)
        if not (np.isfinite(self.height) and self.height > 0):
            raise ValueError('Fixed J_HK must be positive and finite')
        self._to_rgb, self._rgb_matrix_bounds = _rgb_matrix()
        fl, _ = modcam16.viewing(REFERENCE_NITS)
        white_power = fl ** modcam16.POWER
        self._white_response = modcam16.B * white_power / (27.13 + white_power)
        white_power = power(I(fl))
        self._white_response_bounds = modcam16.B * white_power / (27.13 + white_power)
        self._height_squared = I(self.height) * self.height
        self.chroma_limit = float((self._height_squared / modcam16.HK).hi)

    @property
    def linear_rgb_matrix(self):
        """Return the conversion from normalized cones to linear Rec.709."""
        return self._to_rgb.copy()

    @property
    def linear_rgb_matrix_bounds(self):
        return self._rgb_matrix_bounds

    @property
    def normalized_white_response(self):
        return self._white_response / modcam16.B

    @property
    def normalized_white_response_bounds(self):
        return self._white_response_bounds / modcam16.B

    def direction(self, hue):
        """Return the normalized opponent response per unit chroma."""
        hue = np.asarray(hue, dtype=float)
        inverse = modcam16.INVERSE
        opponents = np.cos(hue)[..., None] * inverse[:, 1] + np.sin(hue)[..., None] * inverse[:, 2]
        return 3.05 * opponents / (1204 * modcam16.eccentricity(hue)[..., None])

    def direction_bounds(self, hue):
        return self._directions(I(hue))

    def rgb(self, chroma, hue):
        """Evaluate raw linear RGB at the decoder's fixed height."""
        return self.rgb_at_height(self.height, chroma, hue)

    def rgb_at_height(self, height, chroma, hue):
        """Decode the nonnegative achromatic branch with broadcastable inputs."""
        height, chroma, hue = np.broadcast_arrays(
            np.asarray(height, float), np.asarray(chroma, float), np.asarray(hue, float),
        )
        energy = np.maximum(0., height * height - modcam16.HK * chroma) / 10000
        response = energy[..., None] ** (1 / (2 * modcam16.GAMMA)) + chroma[..., None] * self.direction(hue)
        magnitude = np.abs(response)
        white = self._white_response
        cones = np.sign(response) * (magnitude * (modcam16.B - white)
                                    / (modcam16.B - white * magnitude)) ** (50 / 21)
        reference = cones[..., 1, None]
        return reference + (cones - reference) @ self._to_rgb.T

    def _directions(self, hue, derivative=False):
        e = I(1)
        de = I(0)
        for k, (a, b) in enumerate(zip(_COSINE, _SINE), start=1):
            angle = hue if k == 1 else k * hue
            c, s = trig(angle, cosine=True), trig(angle)
            if k == 1:
                cosine, sine = c, s
            e = e + a * c + b * s
            if derivative:
                de = de + k * (-a * s + b * c)
        cosine, sine = cosine[..., None], sine[..., None]
        a, b = modcam16.INVERSE[:, 1], modcam16.INVERSE[:, 2]
        numerator = a * cosine + b * sine
        e = e[..., None]
        direction = 3.05 * numerator / (1204 * e)
        if derivative:
            numerator_h = -a * sine + b * cosine
            direction_h = (3.05 * (numerator_h * e - numerator * de[..., None])
                           / (1204 * e * e))
            return direction, direction_h
        return direction

    def _energy(self, chroma):
        # The outward-rounded chroma limit can exceed the branch endpoint by
        # a few ulps. This extension keeps the endpoint in the closed search.
        return ((self._height_squared - modcam16.HK * chroma) / 10000).positive()

    def _cone_base(self, magnitude):
        white = self._white_response_bounds
        margin = modcam16.B - white * magnitude
        if np.any(margin.lo <= 0):
            raise ValueError('The fixed-J_HK response enclosure reaches a decoder pole')
        return (magnitude * (modcam16.B - white) / margin).positive(), margin

    def _cone_derivatives(self, response, second=False):
        magnitude = I(np.maximum(0., np.maximum(response.lo, -response.hi)),
                      np.maximum(np.abs(response.lo), np.abs(response.hi)))
        base, margin = self._cone_base(magnitude)
        white = self._white_response_bounds
        base_d = modcam16.B * (modcam16.B - white) / (margin * margin)
        exponent = I(50) / 21
        first = exponent * power(base, 29, 21) * base_d
        if second:
            magnitude_second = (exponent * (I(29) / 21) * power(base, 8, 21) * base_d * base_d
                                + first * 2 * white / margin)
            sign = I(np.sign(response.lo), np.sign(response.hi))
            return first, sign * magnitude_second
        return first

    def _image(self, cones):
        left, middle, right = (cones[..., i] for i in range(3))
        return _stack([
            left * row[0] + middle * row[1] + right * row[2]
            for row in self._rgb_matrix_bounds
        ])

    def bounds(self, chroma_lo, chroma_hi, hue_lo, hue_hi):
        """Enclose every channel across a closed chroma and radian hue box."""
        chroma, hue = I(chroma_lo, chroma_hi), I(hue_lo, hue_hi)
        response = self._energy(chroma).power(_POWER)[..., None] + chroma[..., None] * self._directions(hue)
        # The signed cone inverse is monotone. Evaluate its two end values
        # without treating their signs and magnitudes as independent intervals.
        endpoints = np.stack((response.lo, response.hi))
        base, _ = self._cone_base(I(np.abs(endpoints)))
        cones = power(base, 50, 21)
        low = np.where(endpoints[0] < 0, -cones.hi[0], cones.lo[0])
        high = np.where(endpoints[1] < 0, -cones.lo[1], cones.hi[1])
        return self._image(I(low, high))

    def slopes(self, chroma_lo, chroma_hi, hue_lo, hue_hi):
        """Enclose the RGB derivatives with respect to chroma and radian hue."""
        chroma, hue = I(chroma_lo, chroma_hi), I(hue_lo, hue_hi)
        direction, direction_h = self._directions(hue, derivative=True)
        energy = self._energy(chroma)
        response = energy.power(_POWER)[..., None] + chroma[..., None] * direction
        cone_d = self._cone_derivatives(response)

        interior = energy.lo > 0
        safe_energy = I(np.where(interior, energy.lo, 1.), np.where(interior, energy.hi, 1.))
        neutral_c = -_ENERGY_SCALE * _POWER * safe_energy.power(_POWER - 1)
        rgb_c = self._image(cone_d * (neutral_c[..., None] + direction))
        rgb_c = I(np.where(interior[..., None], rgb_c.lo, -np.inf),
                  np.where(interior[..., None], rgb_c.hi, np.inf))
        return rgb_c, self._image(cone_d * chroma[..., None] * direction_h)

    def white_slopes(self, hue_lo, hue_hi):
        """Enclose the white chroma derivative and its derivative in radian hue."""
        if self.height != 100:
            raise ValueError('White slopes require J_HK=100')
        direction, direction_h = self._directions(I(hue_lo, hue_hi), derivative=True)
        cone_d = (I(50) / 21) * modcam16.B / (modcam16.B - self._white_response_bounds)
        # At white, the cone derivative is common and the inverse maps the
        # neutral direction to itself exactly.
        rgb_c = cone_d * (self._image(direction) - _POWER * _ENERGY_SCALE)
        return rgb_c, cone_d * self._image(direction_h)

    def chroma_second(self, chroma_lo, chroma_hi, hue_lo, hue_hi):
        """Enclose the RGB second chroma derivative away from zero energy."""
        chroma, hue = I(chroma_lo, chroma_hi), I(hue_lo, hue_hi)
        energy = self._energy(chroma)
        if np.any(energy.lo <= 0):
            raise ValueError('The second chroma derivative requires strictly positive energy')
        direction = self._directions(hue)
        response = energy.power(_POWER)[..., None] + chroma[..., None] * direction
        response_c = direction - (_ENERGY_SCALE * _POWER * energy.power(_POWER - 1))[..., None]
        response_cc = _ENERGY_SCALE * _ENERGY_SCALE * _POWER * (_POWER - 1) * energy.power(_POWER - 2)
        cone_d, cone_dd = self._cone_derivatives(response, second=True)
        return self._image(cone_dd * response_c * response_c + cone_d * response_cc[..., None])

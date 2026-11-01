"""External Colour references and independently specified appearance boundaries."""
import unittest
from fractions import Fraction as F
import colour
import numpy as np
from color_tools.perceptual_grade_reference.appearance import encode, decode, viewing, CAT16
from color_tools.perceptual_grade_reference.model import xyz_from_xy, rgb_matrix


class AppearanceTests(unittest.TestCase):
    def test_external_hellwig_coordinates_and_units(self):
        # Stimulus/white from Colour's published Hellwig2022 example, evaluated
        # in our documented Dark/203-nit profile rather than its Average profile.
        xyz = np.array([19.01, 20., 21.78])/100
        white = np.array([95.05, 100., 108.88])/100
        expected = colour.XYZ_to_Hellwig2022(100*xyz, **viewing(white, 203.))
        actual = encode(xyz, white)
        np.testing.assert_allclose(actual.ja, expected.J, rtol=2e-14)
        np.testing.assert_allclose(np.hypot(*actual.q[1:]), expected.C, rtol=2e-14, atol=1e-13)
        self.assertAlmostEqual(actual.q[0]**2, expected.J**2+66*expected.C, places=11)
        recovered = decode(actual.q, actual.ja**2, white)
        np.testing.assert_allclose(recovered, xyz, rtol=2e-12, atol=1e-14)

    def test_ap1_matrix_from_published_chromaticities(self):
        # https://docs.acescentral.com/encodings/acescg/#color-space-chromaticities
        # Derive the expected NPM with exact rational Cramer's rule, independently
        # of Colour/NumPy matrix construction and production coordinate code.
        def xyz(x, y):
            x, y = F(x), F(y)
            return [x/y, F(1), (1-x-y)/y]
        basis = list(map(list, zip(xyz('.713', '.293'), xyz('.165', '.830'), xyz('.128', '.044'))))
        white = xyz('.32168', '.33767')
        def determinant(m):
            return sum(m[0][i]*(m[1][(i+1)%3]*m[2][(i+2)%3]-m[1][(i+2)%3]*m[2][(i+1)%3]) for i in range(3))
        scales = [determinant([[white[i] if k == j else basis[i][k] for k in range(3)]
                               for i in range(3)])/determinant(basis) for j in range(3)]
        expected = [[float(basis[i][j]*scales[j]) for j in range(3)] for i in range(3)]
        np.testing.assert_allclose(rgb_matrix('ACEScg'), expected, rtol=0, atol=5e-15)
        np.testing.assert_allclose(rgb_matrix('ACEScg') @ np.ones(3), xyz_from_xy((.32168, .33767)), atol=5e-15)

    def test_carried_energy_black_neutrals_and_invalid_records(self):
        white = xyz_from_xy((.3127, .329))
        xyz = np.array([-128., -1., -.18, 0., .18, 1., 128.])[:, None]*white
        appearance = encode(xyz, white)
        np.testing.assert_array_equal(appearance.q[:, 1:], 0)
        recovered = decode(appearance.q, appearance.ja*np.abs(appearance.ja), white)
        np.testing.assert_allclose(recovered, xyz, rtol=2e-12, atol=1e-14)
        for q, energy in [([np.inf, 0, 0], 1), ([10, 0, 0], np.nan), ([np.nan, 0, 0], 0)]:
            with self.assertRaises(ValueError):
                decode(q, energy, white)
        with self.assertRaisesRegex(ValueError,'below 400'):
            decode([100,1e8,0],100,white)
        np.testing.assert_allclose(decode([-100., 0., 0.], -10000., white), -white, rtol=2e-12)
        self.assertEqual(encode(np.empty((0, 3)), white).q.shape, (0, 3))

    def test_signed_cones_against_external_colour_and_roundtrip(self):
        white = xyz_from_xy((.32168, .33767))
        cones = np.array([[.7015334528421091, .15673048085276647, -.11885648203192463],
                          [-.1, -.1, -.1], [-.1, .02, .01], [-.001, -.3, -.1]])
        xyz = (cones*(CAT16 @ white)) @ np.linalg.inv(CAT16).T
        expected = colour.XYZ_to_Hellwig2022(100*xyz, **viewing(white, 203.))
        actual = encode(xyz, white)
        np.testing.assert_allclose(actual.ja, expected.J, rtol=3e-14)
        c = np.hypot(actual.q[:, 1], actual.q[:, 2])
        np.testing.assert_allclose(c, expected.C, rtol=3e-14, atol=2e-13)
        # sqrt(C) is ill-conditioned at neutral: external roundoff in C is
        # already checked above, rather than amplified into a false H mismatch.
        b = np.sqrt(66*c)
        h = np.where(expected.J >= 0, np.hypot(expected.J, b), 2*b-np.hypot(expected.J, b))
        np.testing.assert_allclose(actual.q[:, 0], h, rtol=3e-14, atol=2e-13)
        recovered = decode(actual.q, actual.ja*np.abs(actual.ja), white)
        np.testing.assert_allclose(recovered, xyz, rtol=3e-12, atol=2e-14)

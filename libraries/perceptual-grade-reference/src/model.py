"""Independent complete grade in XYZ, with explicit RGB boundary adapters."""
from dataclasses import dataclass, field
import colour
import numpy as np
from .appearance import CAT16, response_constants, encode_cones
from .grading import ToneSettings, ColorSettings, Tone, Color
from ..color_core.scaled import Scalar as S, dot
from .export import input_repair
from .cube import context as cube_context
from .cube_guard import guard as cube_guard, guard_scaled as cube_guard_scaled
from .responses import compress, coordinates, requested_energy, State


WHITES = {'D65': (.3127, .329), 'D60': (.32161671, .33761992), 'ACES': (.32168, .33767),
          'D50': (.34567, .35850), 'D55': (.33242, .34743), 'D75': (.29903, .31488),
          'DCI': (.314, .351), 'E': (1/3, 1/3)}
RGB_SPACES = {'Linear Rec.709': 'ITU-R BT.709', 'Linear Rec.2020': 'ITU-R BT.2020', 'ACEScg': 'ACEScg'}


@dataclass(frozen=True)
class LinearSettings:
    exposure: float = 0.
    source_xy: tuple = WHITES['D65']
    balance: tuple = (0., 0.)
    spread: tuple = (0., 0.)
    heading: tuple = (0., 0.)
    # Optional authoritative complete XYZ matrix; replaces control construction.
    matrix: tuple | None = None


@dataclass(frozen=True)
class Settings:
    white: str = 'D65'
    linear: LinearSettings = field(default_factory=LinearSettings)
    tone: ToneSettings = field(default_factory=ToneSettings)
    color: ColorSettings = field(default_factory=ColorSettings)


def xyz_from_xy(xy):
    return np.asarray(colour.xy_to_XYZ(np.asarray(xy, dtype=np.float64)), dtype=np.float64)


def adaptation(source, destination, method='CAT16'):
    return np.asarray(colour.adaptation.matrix_chromatic_adaptation_VonKries(
        np.asarray(source), np.asarray(destination), transform=method), dtype=np.float64)


def rgb_matrix(space):
    rgb = colour.RGB_COLOURSPACES[RGB_SPACES[space]]
    return np.asarray(colour.normalised_primary_matrix(rgb.primaries, rgb.whitepoint), dtype=np.float64)


def source_white(point):
    """Project clamped xy onto the independently constructed CAT16-positive polygon."""
    point = np.asarray(point, dtype=np.float64)
    if point.shape != (2,):
        raise ValueError('Source xy must have two components')
    if not np.isfinite(point).all():
        raise ValueError('Source xy must be finite')
    point = np.clip(point, 0, .9)
    normals = CAT16[:, :2]-CAT16[:, 2, None]
    offsets = CAT16[:, 2]-.002*np.linalg.norm(normals, axis=-1)
    planes = np.vstack((np.column_stack((normals, offsets)), [0, 1, -.002]))
    polygon = np.array([[0., 0.], [.9, 0.], [.9, .9], [0., .9]])
    for a, b, c in planes:
        vertices = []
        for p, q in zip(polygon, np.roll(polygon, -1, axis=0)):
            fp, fq = a*p[0]+b*p[1]+c, a*q[0]+b*q[1]+c
            if fp >= 0:
                vertices.append(p)
            if (fp >= 0) != (fq >= 0):
                vertices.append(p+fp/(fp-fq)*(q-p))
        polygon = np.array(vertices)
    if np.all(planes[:, :2] @ point+planes[:, 2] >= 0):
        return point
    starts, ends = polygon, np.roll(polygon, -1, axis=0)
    edges = ends-starts
    t = np.clip(np.sum((point-starts)*edges, axis=-1)/np.sum(edges*edges, axis=-1), 0, 1)
    candidates = starts+t[:, None]*edges
    return candidates[np.argmin(np.sum((candidates-point)**2, axis=-1))]


def linear_matrix(settings, white):
    values = np.array([settings.exposure, *settings.balance, *settings.spread, *settings.heading])
    if not np.isfinite(values).all() or any(len(getattr(settings, name)) != 2 for name in ('balance', 'spread', 'heading')):
        raise ValueError('Linear controls must be finite, with two directional axes')
    source = source_white(settings.source_xy)
    if settings.matrix is not None:
        matrix = np.asarray(settings.matrix, dtype=np.float64)
        if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
            raise ValueError('Authoritative XYZ matrix must be finite and 3 by 3')
        return matrix.copy()
    white_xy = np.asarray(colour.XYZ_to_xy(white))
    # I + a change makes equal whites exactly I, without a tolerance boundary.
    ratios = (CAT16 @ white)/(CAT16 @ xyz_from_xy(source))
    cat = np.eye(3)+np.linalg.inv(CAT16) @ np.diag(ratios-1) @ CAT16
    if np.any(values[1:] != 0):
        primaries = np.array([[.64, .33], [.15, .06]])
        anchors = colour.XYZ_to_xy(xyz_from_xy(primaries) @ adaptation(xyz_from_xy(WHITES['D65']), white).T)
        anchors = white_xy+.3*(anchors-white_xy)
        targets = []
        for xy, balance, spread, heading in zip(anchors, settings.balance, settings.spread, settings.heading):
            angle = np.deg2rad(float(np.remainder(heading, 360)))
            rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
            direction = rotation @ (xy-white_xy)
            point = [S(v)+(1+S(spread)/100)*d for v, d in zip(white_xy, direction)]
            point[1] = max(S(.01), point[1])
            gain = (-S(balance)).exp2()
            targets.append([point[0]/point[1]*gain, gain, (1-point[0]-point[1])/point[1]*gain])
        basis = np.column_stack((white, xyz_from_xy(anchors).T))
        target = np.column_stack((white, np.asarray(targets, dtype=object).T))
        inverse = np.linalg.inv(basis)
        change = [[S(target[i, j])-basis[i, j] for j in range(3)] for i in range(3)]
        directional = [[dot(row, inverse[:, j])+(1. if i == j else 0.)
                        for j in range(3)] for i, row in enumerate(change)]
    else:
        directional = np.eye(3)
    gain = S(settings.exposure).exp2()
    matrix = [[gain*dot(row, cat[:, j]) for j in range(3)] for row in directional]
    if all(abs(v) <= S(np.finfo(np.float64).max) and (not v or v.e >= -1021) for row in matrix for v in row):
        return np.array([[float(v) for v in row] for row in matrix])
    return np.asarray(matrix, dtype=object)


class Model:
    def __init__(self, settings=Settings(), space='Linear Rec.709', *, hk_guard=True):
        if settings.white not in WHITES or space not in RGB_SPACES:
            raise ValueError('Unknown grading white or RGB space')
        if settings.white != 'D65' or settings.tone.reference_nits != 203.:
            raise ValueError('Only cached D65 / 203 nits is supported')
        self.hk_guard = bool(hk_guard)
        self.settings, self.space = settings, space
        self.white = xyz_from_xy(WHITES[settings.white])
        rgb_white = xyz_from_xy(colour.RGB_COLOURSPACES[RGB_SPACES[space]].whitepoint)
        self.rgb_to_xyz = rgb_matrix(space)
        if not np.array_equal(rgb_white, self.white):
            self.rgb_to_xyz = adaptation(rgb_white, self.white, 'Bradford') @ self.rgb_to_xyz
        self.xyz_to_rgb = np.linalg.inv(self.rgb_to_xyz)
        self.canonical_to_xyz = adaptation(xyz_from_xy(WHITES['D65']), self.white, 'Bradford') @ rgb_matrix('Linear Rec.709')
        self.xyz_to_canonical = np.linalg.inv(self.canonical_to_xyz)
        self.linear = linear_matrix(settings.linear, self.white)
        if not isinstance(settings.color, ColorSettings):
            raise ValueError('Unknown reference color settings schema')
        shapes = [('lightness', (4, 4)), ('chroma', (4, 4)), ('adaptance', (4, 2))]
        for name, shape in shapes:
            values = np.asarray(getattr(settings.color, name))
            if values.shape != shape or not np.isfinite(values).all():
                raise ValueError(f'{name} must be finite with shape {shape}')
        scalars = (settings.tone.reference_nits, settings.tone.peak_nits, settings.color.global_gain,
                   settings.color.adaptance_half_saturation, *settings.tone.input_nits)
        if len(settings.tone.input_nits) != 5 or not np.isfinite(scalars).all():
            raise ValueError('Tone levels and scalar controls must be finite')
        fits = [settings.tone.fit, settings.color.lightness_fit, settings.color.chroma_fit]
        for fit in fits:
            if not np.isfinite(fit):
                raise ValueError('Fit must be finite')
        self.tone = Tone(settings.tone)
        self.color = Color(settings.color, self.tone, lambda: self.boundary, hk_guard=self.hk_guard)
        self.white_cones = CAT16 @ self.white
        self.cones_to_xyz = np.linalg.inv(CAT16) @ np.diag(self.white_cones)
        self.fl, self.aw = response_constants(self.tone.reference)
        self.rgb_white = self.white
        self.to_acescg = (np.linalg.inv(rgb_matrix('ACEScg'))
                          @ adaptation(self.rgb_white, xyz_from_xy(WHITES['ACES']), 'Bradford') @ self.rgb_to_xyz)
        self.acescg_y = rgb_matrix('ACEScg')[1]
        self.native_matrix = (np.linalg.inv(rgb_matrix('ACEScg'))
                              @ adaptation(self.rgb_white, xyz_from_xy(WHITES['ACES']), 'Bradford')
                              @ self.cones_to_xyz)
        self.neutral_rgb = settings.linear.matrix is None and np.array_equal(source_white(settings.linear.source_xy), np.asarray(WHITES[settings.white]))
        self.exposure = S(settings.linear.exposure).exp2()
        # Representation selection, not control limits: both paths evaluate
        # the same complete equations. These bounds keep vector intermediates
        # away from overflow; other finite values use integer exponents.
        p = settings.color
        web_vector = (np.max(np.abs(p.web.log_chroma)) <= 64 and
                                np.max(np.abs(p.web.log_scale)) <= 64)
        self.vector_controls = (web_vector and self.linear.dtype != object and np.max(np.abs(self.linear)) < 2.**200 and
                                np.max(np.abs(p.lightness)) < 2.**100 and np.max(np.abs(p.adaptance)) < 2.**100 and
                                np.max(np.abs(p.chroma)) <= 64 and abs(p.global_gain) <= 128)

    @property
    def boundary(self):
        return cube_context(self.fl, self.aw, self.native_matrix)

    def encode_cones(self, cones):
        boundary = self.boundary
        return encode_cones(cones, self.tone.reference, (boundary.fl, boundary.aw))

    def enter_native(self, values):
        from .responses import State
        native=input_repair(values,self.acescg_y)
        inverse=np.linalg.inv(self.boundary.matrix)
        cones=native[...,1,None]+np.einsum('ij,...j->...i',inverse,native-native[...,1,None])
        source=self.encode_cones(cones)
        return State(source.q,source.ja*np.abs(source.ja))

    def grade_state(self, state):
        """Grade through pre-Scale H-K repair; hand off before cube export."""
        if state.q.dtype!=object and self.vector_controls:
            tone=self.tone.apply(state)
            return self.color.apply_state(tone)
        coordinates=[];energies=[]
        for q,j,e in zip(state.q.reshape(-1,3),state.ja.reshape(-1),state.energy.reshape(-1)):
            base,j=self.tone.scaled_apply(list(map(S,q)),S(j))
            reference = j*abs(j) if self.tone.active else S(e)
            request,energy=self.color.scaled_apply_state(base,j,reference)
            coordinates.append(request);energies.append(energy)
        return State(np.asarray(coordinates,dtype=object).reshape(state.q.shape),
                     np.asarray(energies,dtype=object).reshape(state.energy.shape))

    def release_state(self, state, guard=False):
        """Decode an appearance state, optionally applying only cube containment.

        H-K repair already occurs inside Stage 3, before final Scale. Repeating
        it here would change the repaired saturation as Scale changes.
        """
        if state.q.dtype!=object:
            q,e=state.q,state.energy
            if guard:
                return cube_guard(self.boundary,q,e)[2]
            return self.boundary.decode(q,e)
        out=[]
        for q,e in zip(state.q.reshape(-1,3),state.energy.reshape(-1)):
            q=list(q)
            rgb=(cube_guard_scaled(self.boundary,q,e)[2] if guard
                 else self.boundary.decode_scaled(q,e))
            out.append([float(v) for v in rgb])
        return np.asarray(out).reshape(state.q.shape)

    def _adapters(self, input_matrix, output_matrix):
        native_xyz = self.boundary.matrix @ (CAT16/self.white_cones[:, None])
        return native_xyz @ input_matrix, output_matrix @ np.linalg.inv(native_xyz)

    def prepare_native(self, values):
        return input_repair(values, self.acescg_y)

    def input_native(self, values, input_matrix=None, apply_linear=False):
        """Raw input -> optional XYZ Stage 1 -> native AP1 input repair."""
        values = np.asarray(values, dtype=float)
        if values.shape[-1:] != (3,) or not np.isfinite(values).all():
            raise ValueError('Input must contain finite triples')
        before = self.rgb_to_xyz if input_matrix is None else input_matrix
        native_xyz = self.boundary.matrix @ (CAT16/self.white_cones[:, None])
        neutral = np.ones(3) if np.array_equal(before, self.rgb_to_xyz) else np.linalg.solve(before, self.white)
        matrix = self.linear if apply_linear else np.eye(3)
        diagonal = matrix[1, 1]
        if (matrix.dtype != object and np.max(abs(values),initial=0) < 2.**700
                and np.all((values==0)|(abs(values)>=2.**-700)) and np.max(abs(matrix)) < 2.**200
                and np.all((matrix==0)|(abs(matrix)>=2.**-200))):
            delta = ((values-values[..., 1, None]*neutral) @ before.T) @ matrix.T
            delta += values[..., 1, None]*((matrix-diagonal*np.eye(3)) @ self.white)
            return input_repair(diagonal*values[..., 1, None]+delta @ native_xyz.T, self.acescg_y)
        result = []
        for row in values.reshape(-1, 3):
            delta = [dot(axis, [S(v)-S(row[1])*n for v,n in zip(row,neutral)]) for axis in before]
            delta = [dot(axis,delta)+S(row[1])*dot([S(v)-(S(diagonal) if i == j else S()) for j,v in enumerate(axis)],self.white)
                     for i,axis in enumerate(matrix)]
            native = [S(row[1])*diagonal+dot(axis,delta) for axis in native_xyz]
            amplitude = max(map(abs,native))
            unit = np.array([float(v/amplitude) if amplitude else 0. for v in native])
            repaired = input_repair(unit,self.acescg_y)
            upper = max(repaired)
            factor = min(amplitude,S(np.nextafter(1024.,0.))/upper) if upper else S()
            result.append([S(v)*factor for v in repaired])
        scaled=any(v and abs(v)<S(2.**-1021) for row in result for v in row)
        return np.asarray(result,dtype=object if scaled else float).reshape(values.shape)

    def _scaled_entry(self,values,export):
        inverse=np.linalg.inv(self.boundary.matrix)
        result=[]
        for row in values.reshape(-1,3):
            cones=[S(row[1])+dot(axis,[S(v)-row[1] for v in row]) for axis in inverse]
            result.append([float(v) for v in self.core(cones,export)])
        return np.asarray(result).reshape(values.shape)

    def prepare_input(self, values, input_matrix=None):
        before = self.rgb_to_xyz if input_matrix is None else input_matrix
        to_native, _ = self._adapters(before, np.eye(3))
        neutral = np.ones(3) if np.array_equal(before, self.rgb_to_xyz) else np.linalg.solve(before, self.white)
        native = self.prepare_native(self.input_native(values, before))
        return native[..., 1, None]*neutral+(native-native[..., 1, None]) @ np.linalg.inv(to_native).T

    def core(self, cones, export=True):
        boundary = self.boundary
        source = [compress(v, boundary.fl) for v in cones]
        q, ja = coordinates(source, boundary.aw)
        if cones[0] == cones[1] == cones[2]:q = [ja, S(), S()]
        stage2_q, stage2_ja = self.tone.scaled_apply(q, ja)
        request, energy = self.color.scaled_apply_state(stage2_q, stage2_ja)
        if export:
            return cube_guard_scaled(boundary,request,energy)[2]
        return self.boundary.decode_scaled(request, energy)

    def _core_arrays(self, cones, export=True):
        source = self.encode_cones(cones)
        stage2 = self.tone.apply(source)
        if np.any((stage2.ja != 0) & (np.abs(stage2.ja) < 2.**-200)):return None
        result = self.color.apply_state(stage2)
        request, energy = result.q, result.energy
        if np.any((request[..., 0] > 0) & (request[..., 0] < 2.**-200)):return None
        if export:
            return cube_guard(self.boundary, request, energy)[2]
        return self.boundary.decode(request, energy)

    def forward_native(self, values, export=True, entry=True, apply_linear=True):
        """Native AP1 input repair, raw-coordinate grading, optional cube export."""
        values = np.asarray(values)
        internal_scaled=values.dtype==object and all(isinstance(v,S) for v in values.flat)
        if not internal_scaled:values=np.asarray(values,dtype=float)
        if values.shape[-1:] != (3,) or (not internal_scaled and not np.isfinite(values).all()):
            raise ValueError('Input must contain finite triples')
        linear = self.linear if apply_linear else np.eye(3)
        before = self.cones_to_xyz @ np.linalg.inv(self.boundary.matrix)
        if entry:
            if apply_linear:values = self.input_native(values,before,True)
            if export and not (self.tone.active or self.color.active):
                return np.asarray(values,dtype=float) if values.dtype==object else input_repair(values,self.acescg_y)
            if values.dtype==object:return self._scaled_entry(values,export)
            values = self.prepare_native(values)
            linear = np.eye(3)
        to_cones = CAT16/self.white_cones[:, None]
        if self.vector_controls:
            diagonal = linear[1, 1]
            delta = ((values-values[..., 1, None]) @ before.T) @ linear.T
            delta += values[..., 1, None]*((linear-diagonal*np.eye(3)) @ self.white)
            cones = diagonal*values[..., 1, None]+delta @ to_cones.T
            suitable = np.all((cones == 0) | ((abs(cones) >= 2.**-200) & (abs(cones) <= 2.**300)))
            if suitable:
                result = self._core_arrays(cones, export)
                if result is not None:return result
        result = []
        for row in values.reshape(-1, 3):
            diagonal = S(linear[1, 1])
            delta = [dot(axis, [S(v)-row[1] for v in row]) for axis in before]
            delta = [dot(axis, delta)+S(row[1])*dot([S(c)-(diagonal if i == j else S()) for j,c in enumerate(axis)], self.white)
                     for i,axis in enumerate(linear)]
            cones = [S(row[1])*diagonal+dot(axis,delta) for axis in to_cones]
            result.append([float(v) for v in self.core(cones,export)])
        return np.asarray(result,dtype=float).reshape(values.shape)

    def _forward(self, values, input_matrix, output_matrix, apply_linear=True, export=True, entry=True):
        to_native, from_native = self._adapters(input_matrix, output_matrix)
        if entry:native = self.input_native(values, input_matrix, apply_linear)
        else:
            values = np.asarray(values, dtype=float)
            white = np.ones(3) if np.array_equal(input_matrix, self.rgb_to_xyz) else np.linalg.solve(input_matrix,self.white)
            native = values[...,1,None]+(values-values[...,1,None]*white) @ to_native.T
        result = self.forward_native(native, export, entry, apply_linear and not entry)
        white = np.ones(3) if np.array_equal(output_matrix,self.xyz_to_rgb) else output_matrix @ self.white
        return result[...,1,None]*white+(result-result[...,1,None]) @ from_native.T

    def nonlinear_xyz(self, xyz):
        return self._forward(xyz, np.eye(3), np.eye(3), False)

    def forward_xyz(self, xyz):
        return self._forward(xyz, np.eye(3), np.eye(3))

    def forward(self, rgb):
        return self._forward(rgb, self.rgb_to_xyz, self.xyz_to_rgb)

    def inverse_xyz(self, xyz):
        from .inverse import solve
        return solve(self, xyz)

    def inverse(self, rgb):
        from .inverse import InverseResult, solve
        rgb = np.asarray(rgb, dtype=np.float64)
        if rgb.shape[-1:] != (3,):
            raise ValueError('Inverse input must have a final dimension of three')
        def to_xyz(values):
            return values[..., 1, None]*self.rgb_white+(values-values[..., 1, None]) @ self.rgb_to_xyz.T
        def from_xyz(values):
            return values[..., 1, None]+(values-values[..., 1, None]*self.rgb_white) @ self.xyz_to_rgb.T
        def forward(xyz):
            return to_xyz(self.forward(from_xyz(xyz)))
        result = solve(self, to_xyz(rgb), forward)
        return InverseResult(from_xyz(result.value), result.residual, result.status)

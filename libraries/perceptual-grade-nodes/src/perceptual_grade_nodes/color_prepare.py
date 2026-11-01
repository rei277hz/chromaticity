"""Portable preparation of Color parameters, independent of the Grade products.

Only parameter functions are sampled. Pixel coordinates, radial operations,
signed energy and both export guards remain native arithmetic.
"""
from dataclasses import dataclass, replace
import math
from types import MappingProxyType
import numpy as np

from ..color_core import linear as color_linear
from ..color_core.modcam16 import encode_cones, eccentricity, INVERSE, GAMMA
from .settings import ColorSettings, WebSettings
from .tables import kernel, readonly
from .layouts import FIELD_CELLS, LAYOUT_SCHEMA, packed_shape, supported_cells

COLOR_TABLE_ERROR_LIMIT = 1e-5
FLOAT_MAX = float(np.finfo(np.float32).max)
TAU = 2 * math.pi


def _validate_color_schema(color):
    """Reject obsolete prepared topology while allowing offline grid studies."""
    if (getattr(color, 'layout_schema', None) != LAYOUT_SCHEMA
            or hasattr(color, 'adaptance_interior_table')
            or any(getattr(table, 'schema', None) != LAYOUT_SCHEMA for table in color.tables)):
        raise ValueError('Prepared Color layout schema is obsolete; prepare again and rebuild the tree')


def smoother(t):
    t = np.clip(np.asarray(t, dtype=np.float64), 0., 1.)
    return t*t*t*(10+t*(-15+6*t))


def cardinal_values(h, anchors, values):
    h, anchors, values = np.asarray(h, float), np.asarray(anchors), np.asarray(values)
    index = np.clip(np.searchsorted(anchors, h, side='right')-1, 0, len(anchors)-2)
    u = smoother((h-anchors[index])/(anchors[index+1]-anchors[index]))
    return values[index]+(values[index+1]-values[index])*u.reshape(u.shape+(1,)*(values.ndim-1))


def coefficient_weights(h, knots, high, fit):
    t = smoother(np.asarray(h, float)/high)
    width = .05*2.**(-float(fit))
    values = np.stack([kernel(t, left, right, width)/kernel(1., left, right, width)
                       for left, right in zip(knots[:-1], knots[1:])], axis=-1)
    values = np.minimum.accumulate(np.clip(values, 0., 1.), axis=-1)
    return np.stack((1-values[..., 1], values[..., 1]-values[..., 2],
                     values[..., 2]-values[..., 3], values[..., 3]), axis=-1)


def drivers(q, ja):
    q, ja = np.asarray(q, float), np.asarray(ja, float)
    c = np.hypot(q[..., 1], q[..., 2])
    r = (35./75.)*abs(ja)
    scale = np.maximum(c, r)
    cn = np.divide(c, scale, out=np.zeros_like(c), where=scale > 0)
    rn = np.divide(r, scale, out=np.zeros_like(c), where=scale > 0)
    den = cn*cn+rn*rn
    visible = (c/np.hypot(c, 2.))**2
    low = np.divide(rn*rn, den, out=np.zeros_like(c), where=den > 0)
    high = np.divide(cn*cn, den, out=np.zeros_like(c), where=den > 0)
    return np.concatenate((np.stack((visible*low, visible*high), axis=-1),
                           q[..., 1:]/np.hypot(c, 2.)[..., None]), axis=-1)


def radial_attenuation(c, toe):
    c, toe = np.broadcast_arrays(np.asarray(c, float), np.asarray(toe, float))
    scale = np.maximum(c, toe)
    return (toe/scale)/np.sqrt(np.hypot((c/scale)**2, (toe/scale)**2))


def radial_coefficient(source, target, toe):
    a = radial_attenuation(source, toe)
    ratio = np.asarray(target)/source
    return np.where(ratio >= 1, 1+(ratio-1)/(1-a), (ratio-a)/(1-a))


def _toe(*radii):
    values = np.concatenate([.1*np.asarray(value) for value in radii], axis=-1)
    values = np.concatenate((np.full(values.shape[:-1]+(1,), 2.), values), axis=-1)
    minimum = np.min(values, axis=-1)
    return minimum/np.sum((minimum[..., None]/values)**8, axis=-1)**.125


@dataclass(frozen=True)
class WebGeometry:
    anchors: np.ndarray
    q: np.ndarray
    energy: np.ndarray
    radii: np.ndarray
    angles: np.ndarray


def web_geometry(anchors, reference):
    rays = np.array(((1, 0, 0), (1, 1, 0), (0, 1, 0),
                     (0, 1, 1), (0, 0, 1), (1, 0, 1)), float)
    cat = np.asarray(color_linear.CAT16)
    white = np.asarray(color_linear.xyz(color_linear.D65))
    matrix = np.asarray(color_linear.rgb_to_xyz('Linear Rec.709'))
    cones = np.broadcast_to(rays @ (cat @ matrix).T/(cat @ white), (4, 6, 3))
    heights = np.broadcast_to(np.asarray(anchors)[:, None], (4, 6))
    low, high = np.zeros_like(heights), np.ones_like(heights)
    for _ in range(64):
        below = encode_cones(cones*high[..., None], reference).q[..., 0] < heights
        if not np.any(below):
            break
        high = np.where(below, high*2, high)
    else:
        raise ValueError('Rec.709 rays cannot reach requested web height')
    for _ in range(64):
        middle = (low+high)/2
        below = encode_cones(cones*middle[..., None], reference).q[..., 0] < heights
        low, high = np.where(below, middle, low), np.where(below, high, middle)
    state = encode_cones(cones*((low+high)/2)[..., None], reference)
    radii = np.hypot(state.q[..., 1], state.q[..., 2])
    angles = np.unwrap(np.arctan2(state.q[..., 2], state.q[..., 1]), axis=-1)
    if np.any(np.diff(angles, axis=-1) <= 0) or np.any(angles[:, -1] >= angles[:, 0]+TAU):
        raise ValueError('Rec.709 handles do not have strict cyclic hue order')
    return WebGeometry(readonly(anchors), readonly(state.q), readonly(state.ja*abs(state.ja)),
                       readonly(radii), readonly(angles))


def response_transform(response, gain):
    r, m = np.broadcast_arrays(np.asarray(response, float), np.asarray(gain, float))
    t = np.minimum(abs(r)/400., 1.)
    result = r*(m/((1-t)+m*t))
    outside = abs(r) > 400.
    if np.any(outside):
        root = np.sqrt(abs(r[outside])/400.-1)
        u = root*(2*root/(np.hypot(1., 2*root)+1))
        z = u/m[outside]
        result = np.array(result, copy=True)
        result[outside] = np.sign(r[outside])*400*(1+z+z*z)
    return np.where(m == 1., r, result)


def adaptation_log_gains(targets, anchors, aw):
    targets = np.asarray(targets, float)
    r0 = aw/3.05*(np.asarray(anchors)/100.)**(1/GAMMA)
    if np.any(r0 >= 400.):
        raise ValueError('Adaptance calibration anchors exceed physical response range')
    angle = np.arctan2(targets[:, 1], targets[:, 0])
    opponent = targets*(aw/(1204*eccentricity(angle)))[:, None]
    target = r0[:, None]+opponent @ INVERSE[:, 1:].T
    if np.any(target <= 0) or np.any(target >= 400):
        raise ValueError('Neutral target requires positive cone responses below 400')
    logs = np.log(target)-np.log(400-target)-np.log(r0[:, None])+np.log(400-r0[:, None])
    return np.where(np.all(targets == 0, axis=-1)[:, None], 0., logs)


@dataclass(frozen=True)
class PreparedColor:
    settings: ColorSettings
    anchors: np.ndarray
    coefficient_knots: np.ndarray
    high: float
    reference: float
    aw: float
    log_gains: np.ndarray
    geometry: WebGeometry | None
    coefficient_table: object = None
    web_table: object = None
    web_toe_table: object = None
    adaptance_table: object = None
    full_fields: bool = False
    layout_schema: int = LAYOUT_SCHEMA

    @property
    def tables(self):
        return tuple(value for value in (self.coefficient_table, self.web_table, self.web_toe_table, self.adaptance_table)
                     if value is not None)

    @property
    def lightness_active(self): return bool(np.any(self.settings.lightness))
    @property
    def chroma_active(self): return bool(np.any(self.settings.chroma) or self.settings.global_gain)
    @property
    def adaptance_active(self): return bool(np.any(self.settings.adaptance))
    @property
    def web_active(self): return self.settings.web.active
    @property
    def active(self):
        return self.lightness_active or self.chroma_active or self.adaptance_active or self.web_active

    def terms(self, h):
        p = self.settings
        return (coefficient_weights(h, self.coefficient_knots, self.high, p.lightness_fit) @ np.asarray(p.lightness),
                coefficient_weights(h, self.coefficient_knots, self.high, p.chroma_fit) @ np.asarray(p.chroma))

    def finite_bounds(self, post_tone_h_bound):
        """Conservative absolute stage bounds; optimization only, never admission.

        Source-ratio intervals retain the correlation between chroma membership
        and Adaptance reach. Each interval uses conservative endpoint bounds,
        including zero and the unbounded tail. Failure to establish a small
        range keeps native saturation operations; it never rejects controls.
        """
        h0 = max(0., float(post_tone_h_bound))
        def driver_bound(values):
            values = np.asarray(values, float)
            return float(np.max(np.maximum(abs(values[:, 0]), abs(values[:, 1]))
                                +np.hypot(values[:, 2], values[:, 3])))
        try:
            h = h0+driver_bound(self.settings.lightness)
            c = h0*h0/66.*math.exp2(self.settings.global_gain+driver_bound(self.settings.chroma))
            scale = 1.
            if self.web_active:
                c *= max(1., math.exp2(float(np.max(self.settings.web.log_chroma)))/.9)
                scale = max(1., math.exp2(float(np.max(self.settings.web.log_scale)))/.9)
            b = math.sqrt(66*c)
            e = (h+b)*(h+3*b)
            intermediate = dict(pre_adaptance_H=h, pre_adaptance_C=c, pre_adaptance_energy=e,
                                input_response=0., transformed_response=0.)
            response = 0.
            if self.adaptance_active:
                # Triangle bound on the four sine/cosine harmonic pairs.
                rho = sum(math.hypot(a, b) for a, b in
                          ((.0582, .1475), (.0258, .0308), (.1347, .0385), (.0289, .0096)))
                opponent = float(np.max(np.hypot(INVERSE[:, 1], INVERSE[:, 2])))
                low = min(0., float(np.min(self.log_gains)))
                high = max(0., float(np.max(self.log_gains)))
                if self.adaptance_table is not None:
                    low = min(low, float(np.min(self.adaptance_table.pixels[..., :3])))
                    high = max(high, float(np.max(self.adaptance_table.pixels[..., :3])))
                lower = np.minimum(0., np.minimum(np.min(self.log_gains, axis=0),
                                                  -2*np.max(self.log_gains, axis=0)))
                normalization = 3.05/math.fsum(weight*math.exp(float(value))
                                               for weight, value in zip((2., 1., .05), lower))
                # Native linear sampling stays in the stored log-k hull. Its
                # exact bound avoids pairing an exterior normalization limit
                # with unrelated low-H calibration gains.
                if self.adaptance_table is not None:
                    normalization = math.exp(max(0., float(np.max(self.adaptance_table.pixels[..., 3]))))
                light = np.asarray(self.settings.lightness, float)
                chroma = np.asarray(self.settings.chroma, float)
                def weighted_driver_bound(values, lo, hi):
                    direction = np.hypot(values[:, 2], values[:, 3])
                    return max(float(np.max(abs(values[:, 0])*weight+abs(values[:, 1])*(1-weight)+direction))
                               for weight in (lo, hi))
                web_gain = max(1., math.exp2(float(np.max(self.settings.web.log_chroma)))/.9) if self.web_active else 1.
                half = self.settings.adaptance_half_saturation
                limits = np.r_[0., np.exp2(np.linspace(-24., 24., 193)), math.inf]
                input_bound = transformed_bound = response = 0.
                for left, right in zip(limits[:-1], limits[1:]):
                    # u=C0/abs(J_A0), so C0<=min(u_upper*H0,H0²/66).
                    c0 = h0*h0/66. if math.isinf(right) else min(right*h0, h0*h0/66.)
                    lo = 0. if math.isinf(right) else ((35/75)/math.hypot(35/75, right))**2
                    hi = ((35/75)/math.hypot(35/75, left))**2
                    ch = c0*math.exp2(self.settings.global_gain+weighted_driver_bound(chroma, lo, hi))*web_gain
                    hh = h0+weighted_driver_bound(light, lo, hi)
                    bb = math.sqrt(66*ch)
                    ee = (hh+bb)*(hh+3*bb)
                    incoming = self.aw/3.05*(math.sqrt(ee)/100.)**(1/GAMMA)+self.aw/(1204*(1-rho))*opponent*ch
                    unit = max(half, left)
                    a4, c4 = (half/unit)**4, (left/unit)**4
                    reach = a4/(a4+c4)
                    # Responses within the physical range stay within400; for an exterior
                    # response only gains below1 can increase its magnitude.
                    transformed = (min(400., incoming*math.exp(reach*high)) if incoming <= 400.
                                   else incoming*math.exp(-2*reach*low))
                    input_bound = max(input_bound, incoming)
                    transformed_bound = max(transformed_bound, transformed)
                    response = max(response, transformed*normalization**reach)
                intermediate['input_response'] = input_bound
                intermediate['transformed_response'] = transformed_bound
                j = 100*(3.05*response/self.aw)**GAMMA
                e = j*j
                raw_opponent = math.hypot(24/11, 4/9)*response
                c = 1204*(1+rho)/self.aw*raw_opponent
                h = math.sqrt(e+66*c)
            intermediate.update(post_adaptance_C=c, post_adaptance_H=h, post_adaptance_energy=e)
            e *= scale*scale
            c *= scale
            h = max(h, math.sqrt(e+66*c))
            parameters = max((float(np.max(abs(table.pixels))) for table in self.tables), default=0.)
            peak = max(h, c, e, response, parameters, h0*h0)
            return dict(**intermediate, H=h, C=c, energy=e, response=response, parameter=parameters,
                        small_arithmetic=math.isfinite(peak) and peak <= 2.**28)
        except (OverflowError, ValueError):
            return dict(H=math.inf, C=math.inf, energy=math.inf, response=math.inf,
                        parameter=math.inf, small_arithmetic=False,
                        **dict.fromkeys(('pre_adaptance_H', 'pre_adaptance_C', 'pre_adaptance_energy',
                                         'input_response', 'transformed_response', 'post_adaptance_H',
                                         'post_adaptance_C', 'post_adaptance_energy'), math.inf))

    def adaptation_parameters(self, h):
        h = np.asarray(h, float)
        logs = cardinal_values(h, self.anchors, self.log_gains)
        m = np.exp(logs)
        r0 = self.aw/3.05*(h/100.)**(1/GAMMA)
        t = np.minimum(r0/400., 1.)[..., None]
        ratio = m/((1-t)+m*t)
        outside = r0 > 400.
        if np.any(outside):
            ratio = np.array(ratio, copy=True)
            ratio[outside] = response_transform(r0[outside, None], m[outside])/r0[outside, None]
        k = 3.05/(ratio @ np.array((2., 1., .05)))
        return logs, k

    def web_parameters(self, h):
        if self.geometry is None:
            raise ValueError('An inactive web has no prepared geometry')
        h = np.asarray(h, float)
        if not np.isfinite(h).all():
            raise ValueError('Web tonal height must be finite')
        def blend(values):
            return cardinal_values(h, self.anchors, values)
        angles = blend(self.geometry.angles)
        radii = np.exp(blend(np.log(self.geometry.radii)))
        target_angles = angles+np.deg2rad(blend(self.settings.web.hue_degrees))
        with np.errstate(over='ignore', under='ignore'):
            target_radii = radii*np.exp2(blend(self.settings.web.log_chroma))
            scales = np.exp2(blend(self.settings.web.log_scale))
            final_radii = target_radii*scales
        gaps = np.diff(np.concatenate((target_angles, target_angles[..., :1]+TAU), axis=-1), axis=-1)
        if np.any(gaps <= 1.e-8) or not np.isfinite(target_angles).all():
            raise ValueError('Web target hues must preserve strict cyclic order')
        if any(np.any(v <= 0) or not np.isfinite(v).all() for v in (radii, target_radii, scales, final_radii)):
            raise ValueError('Web target radii and scales must be finite and positive')
        angular_toe, chroma_toe, scale_toe = _toe(radii), _toe(radii, target_radii), _toe(target_radii, final_radii)
        gc = radial_coefficient(radii, target_radii, chroma_toe[..., None])
        gs = radial_coefficient(target_radii, final_radii, scale_toe[..., None])
        if any(np.any(v <= 0) or not np.isfinite(v).all() for v in (angular_toe, chroma_toe, scale_toe, gc, gs)):
            raise ValueError('Web controls exceed the finite geometry coefficient range')
        source_width = np.diff(np.concatenate((angles, angles[..., :1]+TAU), axis=-1), axis=-1)
        slopes = gaps/source_width
        previous = np.roll(slopes, 1, axis=-1)
        small = np.minimum(slopes, previous)
        derivatives = small/(.5*((small/slopes)**4+(small/previous)**4))**.25
        return dict(angles=angles, radii=radii, target_angles=target_angles, target_radii=target_radii,
                    scales=scales, angular_toe=angular_toe, chroma_toe=chroma_toe, scale_toe=scale_toe,
                    chroma_coefficients=gc, scale_coefficients=gs, angular_derivatives=derivatives)

    def web_toes(self, h):
        """Exact positive toe fields without unrelated angular preparation."""
        h = np.asarray(h, float)
        radii = np.exp(cardinal_values(h, self.anchors, np.log(self.geometry.radii)))
        targets = radii*np.exp2(cardinal_values(h, self.anchors, self.settings.web.log_chroma))
        scales = np.exp2(cardinal_values(h, self.anchors, self.settings.web.log_scale))
        return np.stack((_toe(radii), _toe(radii, targets), _toe(targets, targets*scales)), axis=-1)


@dataclass(frozen=True)
class ColorTable:
    """RGBA parameter rows with hardware-linear lookup at floating pixel X.

    ``fields`` maps a named scalar/vector field to (row, channel) pairs. Native
    evaluation uses the public coordinate mapping, then multiplies by cells.
    Endpoints include analytic constant/asymptotic tails.
    """
    name: str
    cells: int
    pixels: np.ndarray
    fields: object
    mapping: str
    domain: float
    max_error: float | None
    probe_count: int | None
    angular_row: int = 5
    radial_row: int = 17
    scales: object = None
    field_errors: object = None
    max_pointwise_error: float | None = None
    max_mapper_error: float | None = None
    segment_cells: int = 8192
    segments: int = 1
    schema: int = LAYOUT_SCHEMA
    semantic_rows: int = 0
    relative_columns: tuple = ()
    absolute_columns: tuple = ()
    relative_interpolation_limit: float = 0.
    absolute_interpolation_limit: float = 0.
    max_relative_interpolation_error: float | None = None
    max_relative_mapper_error: float | None = None
    max_absolute_interpolation_error: float | None = None

    audit_witness: object = None
    audit_candidates: tuple = ()
    audit_complete: bool = False

    @property
    def memory_bytes(self): return self.pixels.nbytes

    def coordinate(self, h, aw=None, dtype=np.float32):
        h = np.maximum(dtype(0), np.asarray(h, dtype=dtype))
        if self.mapping == 'linear':
            return np.minimum(h/dtype(self.domain), dtype(1))
        if aw is None:
            raise ValueError('Compact Adaptance sampling requires aw')
        s = dtype(math.sqrt(aw/(3.05*400)))*np.power(h/dtype(100), dtype(1/(2*GAMMA)))
        return s/(dtype(1)+s)

    def evaluate(self, coordinate, dtype=np.float32):
        """Simulate packed float32 linear sampling; returns (..., rows, RGBA)."""
        coordinate = np.clip(np.asarray(coordinate, dtype=dtype), dtype(0), dtype(1))
        p = coordinate*dtype(self.cells)
        segment = np.minimum(np.floor(p/dtype(self.segment_cells)).astype(np.int64), self.segments-1)
        local = p-segment.astype(dtype)*dtype(self.segment_cells)
        index = np.minimum(np.floor(local).astype(np.int64), self.segment_cells-1)
        u = (local-index.astype(dtype))[..., None, None]
        rows = self.semantic_rows or self.pixels.shape[0]//self.segments
        data = self.pixels[:rows*self.segments].reshape(rows, self.segments, self.segment_cells+1, 4).astype(dtype, copy=False)
        # Advanced indices lead the result, followed by semantic row and RGBA.
        data = np.transpose(data, (1, 2, 0, 3))
        return data[segment, index]+(data[segment, index+1]-data[segment, index])*u

    def field(self, name, coordinate, dtype=np.float32):
        values = self.evaluate(coordinate, dtype)
        locations = self.fields[name]
        result = np.stack([values[..., row, channel] for row, channel in locations], axis=-1)
        return result[..., 0] if len(locations) == 1 else result


def _field_layout(spec):
    return MappingProxyType({name: tuple((int(index)//4, int(index)%4) for index in indices)
                             for name, indices in spec.items()})


def _compact_height(x, aw):
    x = np.asarray(x, float)
    s = np.divide(x, 1-x, out=np.full_like(x, np.inf), where=x < 1)
    return 100*np.power(s/math.sqrt(aw/(3.05*400)), 2*GAMMA)


def _table_probes(cells, knots):
    probes = np.unique(np.r_[np.linspace(0., 1., cells*8+1), knots,
                             np.nextafter(knots, 0.), np.nextafter(knots, 1.)])
    center = probes.astype(np.float32)
    previous = np.nextafter(center, np.float32(-np.inf)).astype(float)
    following = np.nextafter(center, np.float32(np.inf)).astype(float)
    low = np.nextafter((previous+center.astype(float))/2, center.astype(float))
    high = np.nextafter((following+center.astype(float))/2, center.astype(float))
    return np.unique(np.clip(np.r_[probes, low, high], 0., 1.))


def _generate_field(name, evaluator, fields, mapping, domain, knots=(), scales=None, min_cells=2048,
                    relative_columns=(), relative_limit=1e-6, absolute_columns=(), absolute_limit=3e-6,
                    max_cells=131072, *, cells=None):
    """Generate one fixed field. No resolution search or dense accuracy gate."""
    cells = FIELD_CELLS[name] if cells is None else int(cells)
    if cells not in supported_cells(name):
        raise ValueError('Unsupported fixed field cell count')
    fields = _field_layout(fields)
    values = np.asarray(evaluator(np.linspace(0., 1., cells+1)), float)
    if values.ndim != 2 or values.shape[1] % 4:
        raise ValueError('Color field evaluator must return packed RGBA rows')
    saturated = np.clip(values, -FLOAT_MAX, FLOAT_MAX).astype(np.float32)
    if not np.isfinite(saturated).all():
        raise ValueError(f'{name} parameter field contains nonfinite data')
    rows = saturated.shape[1]//4
    data = saturated.reshape(cells+1, rows, 4)
    segment_cells = min(cells, 8192)
    segments = cells//segment_cells
    # Every segment includes both endpoints, so linear lookup cannot
    # interpolate across an unrelated parameter row at a packing seam.
    pixels = np.stack([data[i*segment_cells:(i+1)*segment_cells+1]
                       for i in range(segments)], axis=0)
    pixels = np.transpose(pixels, (2, 0, 1, 3)).reshape(rows*segments, segment_cells+1, 4)
    physical_height = 1 << (pixels.shape[0]-1).bit_length()
    if pixels.shape[0] != physical_height:
        # Integer row centers then have an exactly representable binary
        # normalized Y coordinate. Otherwise hardware bilinear sampling
        # can leak unrelated neighboring parameter rows into the result.
        pixels = np.pad(pixels, ((0, physical_height-pixels.shape[0]), (0, 0), (0, 0)))
    conditioning = np.ones(values.shape[1]) if scales is None else np.asarray(scales, float)
    if conditioning.shape != (values.shape[1],) or np.any(conditioning < 1):
        raise ValueError('Parameter field conditioning must provide one positive scale per channel')
    table = ColorTable(name, cells, readonly(pixels, np.float32), fields, mapping,
                       float(domain), None, None, scales=readonly(conditioning.reshape(-1, 4)),
                       segment_cells=segment_cells, segments=segments, semantic_rows=rows,
                       relative_columns=tuple(relative_columns), absolute_columns=tuple(absolute_columns),
                       relative_interpolation_limit=relative_limit if relative_columns else 0.,
                       absolute_interpolation_limit=absolute_limit if absolute_columns else 0.)
    return table


def _audit_field(table, evaluator, knots=(), *, stop_on_failure=False):
    """Development-only dense audit of already generated float32 pixels."""
    probes = _table_probes(table.cells, np.asarray(knots, float))
    conditioning = table.scales.ravel()
    relative_columns, absolute_columns = table.relative_columns, table.absolute_columns
    witnesses = {}
    evaluated = 0
    error = pointwise = mapper = relative_error = relative_mapper = absolute_error = 0.
    field_errors = np.zeros(table.semantic_rows*4)
    # Bound temporary analysis memory even for the full nine-row web atlas.
    for start in range(0, len(probes), 8192):
        x = probes[start:start+8192]
        expected = np.asarray(evaluator(x), float)
        actual = table.evaluate(x).reshape(len(x), -1).astype(float)
        discrepancy = abs(actual-expected)/np.maximum(1+abs(expected), conditioning)
        peak = float(np.max(discrepancy, initial=0))
        if 'conditioned' not in witnesses or peak > error:
            row, column = np.unravel_index(int(np.argmax(discrepancy)), discrepancy.shape)
            witnesses['conditioned'] = dict(coordinate=float(x[row]), channel=int(column), expected=float(expected[row, column]),
                                           actual=float(actual[row, column]), error=peak)
        error = max(error, peak)
        field_errors = np.maximum(field_errors, np.max(discrepancy, axis=0))
        pointwise = max(pointwise, float(np.max(abs(actual-expected)/(1+abs(expected)), initial=0)))
        rounded_input = np.asarray(evaluator(x.astype(np.float32).astype(float)), float)
        mapper = max(mapper, float(np.max(abs(rounded_input-expected)/(1+abs(expected)), initial=0)))
        if relative_columns:
            exact = rounded_input[:, relative_columns]
            if np.any(exact <= 0):
                raise ValueError('Relative interpolation budgets require positive parameter fields')
            relative = abs(actual[:, relative_columns]-exact)/exact
            peak = float(np.max(relative))
            if 'relative' not in witnesses or peak > relative_error:
                row, column = np.unravel_index(int(np.argmax(relative)), relative.shape)
                native_column = relative_columns[column]
                witnesses['relative'] = dict(coordinate=float(x[row]), channel=int(native_column),
                    expected=float(exact[row, column]), actual=float(actual[row, native_column]), error=peak)
            relative_error = max(relative_error, peak)
            relative_mapper = max(relative_mapper, float(np.max(
                abs(exact-expected[:, relative_columns])/expected[:, relative_columns])))
        if absolute_columns:
            absolute = abs(actual[:, absolute_columns]-rounded_input[:, absolute_columns])
            peak = float(np.max(absolute))
            if 'absolute' not in witnesses or peak > absolute_error:
                row, column = np.unravel_index(int(np.argmax(absolute)), absolute.shape)
                native_column = absolute_columns[column]
                witnesses['absolute'] = dict(coordinate=float(x[row]), channel=int(native_column),
                    expected=float(rounded_input[row, native_column]), actual=float(actual[row, native_column]), error=peak)
            absolute_error = max(absolute_error, peak)
        evaluated += len(x)
        if stop_on_failure and (error > COLOR_TABLE_ERROR_LIMIT
                or (relative_columns and relative_error > table.relative_interpolation_limit)
                or (absolute_columns and absolute_error > table.absolute_interpolation_limit)):
            break
    return replace(table, max_error=error, probe_count=evaluated,
                   field_errors=readonly(field_errors.reshape(-1, 4)),
                   max_pointwise_error=pointwise, max_mapper_error=mapper,
                   max_relative_interpolation_error=relative_error,
                   max_relative_mapper_error=relative_mapper,
                   max_absolute_interpolation_error=absolute_error, audit_witness=witnesses,
                   audit_complete=evaluated == len(probes))


def _field_passed(table):
    return (table.max_error <= COLOR_TABLE_ERROR_LIMIT
            and (not table.relative_columns or table.max_relative_interpolation_error <= table.relative_interpolation_limit)
            and (not table.absolute_columns or table.max_absolute_interpolation_error <= table.absolute_interpolation_limit))


def _build_field(name, evaluator, fields, mapping, domain, knots=(), scales=None, min_cells=2048,
                 relative_columns=(), relative_limit=1e-6, absolute_columns=(), absolute_limit=3e-6,
                 max_cells=131072):
    """Development-only smallest-passing resolution search."""
    attempts = []
    last = None
    for cells in supported_cells(name):
        if cells > max_cells:
            continue
        table = _generate_field(name, evaluator, fields, mapping, domain, knots, scales,
                                relative_columns=relative_columns, relative_limit=relative_limit,
                                absolute_columns=absolute_columns, absolute_limit=absolute_limit, cells=cells)
        last = _audit_field(table, evaluator, knots, stop_on_failure=True)
        attempts.append(dict(cells=cells, passed=_field_passed(last), max_error=last.max_error,
                             relative_error=last.max_relative_interpolation_error,
                             absolute_error=last.max_absolute_interpolation_error, witness=last.audit_witness))
        if _field_passed(last):
            return replace(last, audit_candidates=tuple(attempts))
    raise ValueError(f'{name} has no passing resolution through {max_cells} cells: {attempts}')

def _runtime_layout_matches(table):
    """Whether a prior payload can be reused under the current fixed layout."""
    cells = FIELD_CELLS.get(table.name)
    if (cells is None or table.cells != cells or table.semantic_rows <= 0
            or getattr(table, 'schema', None) != LAYOUT_SCHEMA):
        return False
    segment = min(cells, 8192)
    return (table.segment_cells == segment and table.segments == cells//segment
            and table.pixels.shape == packed_shape(table.name, table.semantic_rows))


def _prepare_tables(prepared, *, builder=_generate_field, previous=None):
    coefficient, web, web_toe, adaptance = None, None, None, None
    if (previous is not None and builder is _generate_field
            and getattr(previous, 'layout_schema', None) == LAYOUT_SCHEMA
            and not hasattr(previous, 'adaptance_interior_table')):
        generate = builder
        same_context = (prepared.reference == previous.reference and prepared.aw == previous.aw
                        and np.array_equal(prepared.anchors, previous.anchors))
        p, q = prepared.settings, previous.settings
        reusable = {
            'Color coefficients': same_context and all(getattr(p, key) == getattr(q, key)
                for key in ('lightness', 'chroma', 'lightness_fit', 'chroma_fit')),
            'Web parameters': same_context and p.web == q.web,
            # Hue does not participate in radial toe preparation.
            'Web toes': same_context and p.web.log_chroma == q.web.log_chroma and p.web.log_scale == q.web.log_scale,
            'Adaptance parameters': same_context and p.adaptance == q.adaptance,
        }
        existing = {table.name: table for table in previous.tables}
        def builder(name, *args, **kwargs):
            if reusable[name] and name in existing and _runtime_layout_matches(existing[name]):
                return existing[name]
            return generate(name, *args, **kwargs)
    if prepared.full_fields or prepared.lightness_active or np.any(prepared.settings.chroma):
        def values(x):
            a, b = prepared.terms(x*prepared.high)
            return np.concatenate((a, b), axis=-1)
        coefficient = builder('Color coefficients', values,
                                   {'lightness': range(4), 'chroma': range(4, 8)},
                                   'linear', prepared.high,
                                   prepared.anchors/prepared.high,
                                   1+np.r_[np.max(abs(np.asarray(prepared.settings.lightness)), axis=0),
                                           np.max(abs(np.asarray(prepared.settings.chroma)), axis=0)],
                                   absolute_columns=(4, 5, 6, 7) if np.any(prepared.settings.chroma) else ())
    if prepared.full_fields or prepared.web_active:
        anchor_angles = prepared.web_parameters(prepared.anchors)['target_angles']
        # A constant whole-turn shift per handle keeps its left endpoint near
        # the principal atan2 range without introducing a tonal discontinuity.
        mid_angles = (np.min(anchor_angles, axis=0)+np.max(anchor_angles, axis=0))/2
        radial_shifts = TAU*np.floor(mid_angles/TAU+.5)
        def values(x):
            p = prepared.web_parameters(x*prepared.high)
            data = np.zeros(x.shape+(29, 4))
            flat = data.reshape(x.shape+(116,))
            flat[..., :6] = p['angles']
            flat[..., 8:14] = p['target_angles']
            src = np.concatenate((p['angles'], p['angles'][..., :1]+TAU), -1)
            dst = np.concatenate((p['target_angles'], p['target_angles'][..., :1]+TAU), -1)
            gc, gs = np.log(p['chroma_coefficients']), np.log(p['scale_coefficients'])
            for i in range(6):
                following = (i+1) % 6
                width = src[..., i+1]-src[..., i]
                delta = dst[..., i+1]-dst[..., i]
                d0, d1 = width*p['angular_derivatives'][..., i], width*p['angular_derivatives'][..., following]
                data[..., 5+2*i, :] = np.stack((src[..., i], width, dst[..., i], d0), -1)
                data[..., 6+2*i, :3] = np.stack((10*delta-6*d0-4*d1,
                                               -15*delta+8*d0+7*d1, 6*delta-3*d0-3*d1), -1)
                data[..., 17+2*i, :] = np.stack((dst[..., i]-radial_shifts[i], delta,
                                                gc[..., i], gc[..., following]), -1)
                data[..., 18+2*i, :2] = np.stack((gs[..., i], gs[..., following]), -1)
            return flat
        fields = {'angles': range(6), 'target_angles': range(8, 14)}
        # Log radial coefficients stay within log(1/.9) of the authored log
        # ratio: the prepared toe is at most one tenth of either endpoint.
        # These per-handle scales are derived from settings, never from probes.
        gc_scale = 1+math.log(2)*np.max(abs(np.asarray(prepared.settings.web.log_chroma)), axis=0)-math.log(.9)
        gs_scale = 1+math.log(2)*np.max(abs(np.asarray(prepared.settings.web.log_scale)), axis=0)-math.log(.9)
        scales = np.ones((29, 4))
        for i in range(6):
            scales[17+2*i, 2:] = gc_scale[[i, (i+1)%6]]
            scales[18+2*i, :2] = gs_scale[[i, (i+1)%6]]
        fields['log_chroma_coefficients'] = tuple(4*(17+2*i)+2 for i in range(6))
        fields['log_scale_coefficients'] = tuple(4*(18+2*i) for i in range(6))
        # Exponentiation makes absolute log interpolation error significant,
        # including a zero crossing between opposite authored stop values.
        log_columns = tuple(column for i in range(6)
                            for column in (4*(17+2*i)+2, 4*(17+2*i)+3,
                                           4*(18+2*i), 4*(18+2*i)+1))
        web = builder('Web parameters', values, fields, 'linear', prepared.high,
                           prepared.anchors/prepared.high, scales.ravel(),
                           absolute_columns=log_columns)
        def toe_values(x):
            toes = prepared.web_toes(x*prepared.high)
            return np.concatenate((toes, np.zeros(x.shape+(1,))), axis=-1)
        web_toe = builder('Web toes', toe_values,
            {'angular_toe': (0,), 'chroma_toe': (1,), 'scale_toe': (2,)},
            'linear', prepared.high, prepared.anchors/prepared.high,
            relative_columns=(0, 1, 2), max_cells=524288)
    if prepared.full_fields or prepared.adaptance_active:
        def values(x):
            h = _compact_height(x, prepared.aw)
            # At compact infinity the calibrated logs are constant and the
            # algebraic exterior response ratio is exactly exp(-2*logs).
            interior = x < 1
            logs = np.broadcast_to(prepared.log_gains[-1], x.shape+(3,)).copy()
            k = np.full(x.shape, 3.05/np.dot(np.exp(-2*prepared.log_gains[-1]), (2., 1., .05)))
            if np.any(interior):
                logs[interior], k[interior] = prepared.adaptation_parameters(h[interior])
            return np.concatenate((logs, np.log(k)[..., None]), axis=-1)
        s = math.sqrt(prepared.aw/(3.05*400))*np.power(prepared.anchors/100, 1/(2*GAMMA))
        adaptance = builder('Adaptance parameters', values,
                                {'log_gains': range(3), 'log_k': (3,)},
                                'response_compact', 0., np.r_[s/(1+s), .5],
                                1+np.r_[np.max(abs(prepared.log_gains), axis=0),
                                        2*np.max(abs(prepared.log_gains))])
    return replace(prepared, coefficient_table=coefficient, web_table=web, web_toe_table=web_toe,
                   adaptance_table=adaptance)


def _prepare_color_parameters(settings, tone, *, full_fields=False, previous=None):
    if not isinstance(settings, ColorSettings):
        raise TypeError('color must be ColorSettings')
    for name, shape in (('lightness', (4, 4)), ('chroma', (4, 4)), ('adaptance', (4, 2))):
        array = np.asarray(getattr(settings, name), float)
        if array.shape != shape or not np.isfinite(array).all():
            raise ValueError(f'Color {name} must be finite with shape {shape}')
    for name in ('log_chroma', 'hue_degrees', 'log_scale'):
        array = np.asarray(getattr(settings.web, name), float)
        if array.shape != (4, 6) or not np.isfinite(array).all():
            raise ValueError(f'Web {name} must be finite with shape (4, 6)')
    for name in ('lightness_fit', 'chroma_fit'):
        value = float(getattr(settings, name))
        if not math.isfinite(value) or not -2 <= value <= 6:
            raise ValueError('The evaluated Color fit domain is [-2, 6]')
    if not math.isfinite(settings.global_gain):
        raise ValueError('Global chroma gain must be finite')
    if not math.isfinite(settings.adaptance_half_saturation) or not .05 <= settings.adaptance_half_saturation <= 1:
        raise ValueError('Adaptance half-influence saturation must be in [.05, 1]')
    anchors = readonly(100*tone.target[1:])
    same_context = (previous is not None and previous.reference == tone.reference
                    and previous.aw == tone.aw and np.array_equal(previous.anchors, anchors))
    if (same_context and settings == previous.settings and full_fields == previous.full_fields
            and getattr(previous, 'layout_schema', None) == LAYOUT_SCHEMA
            and not hasattr(previous, 'adaptance_interior_table')
            and all(_runtime_layout_matches(table) for table in previous.tables)):
        return previous
    logs = (previous.log_gains if same_context and settings.adaptance == previous.settings.adaptance
            else readonly(adaptation_log_gains(settings.adaptance, anchors, tone.aw)))
    geometry = None
    if full_fields or settings.web.active:
        geometry = (previous.geometry if same_context and previous.geometry is not None
                    else web_geometry(anchors, tone.reference))
    prepared = PreparedColor(settings, anchors, readonly(smoother(tone.target/tone.target[-1])),
                             100*tone.high, tone.reference, tone.aw, logs, geometry,
                             full_fields=full_fields)
    if prepared.web_active:
        prepared.web_parameters(anchors)
    return prepared


def prepare_color(settings, tone, *, full_fields=False, previous=None):
    """Generate fixed parameter fields without any dense accuracy audit."""
    prepared = _prepare_color_parameters(settings, tone, full_fields=full_fields, previous=previous)
    if prepared is previous:
        return prepared
    return _prepare_tables(prepared, previous=previous)


def audit_color(prepared, *, select=False):
    """Development-only fixed-field audit or explicit resolution search.

    Runtime preparation never calls this API. Returned metadata describes only
    this authored case, not full-domain certification.
    """
    def audit_builder(name, evaluator, fields, mapping, domain, knots=(), scales=None, **kwargs):
        if select:
            return _build_field(name, evaluator, fields, mapping, domain, knots, scales, **kwargs)
        current = next(table for table in prepared.tables if table.name == name)
        return _audit_field(current, evaluator, knots)
    return _prepare_tables(prepared, builder=audit_builder)

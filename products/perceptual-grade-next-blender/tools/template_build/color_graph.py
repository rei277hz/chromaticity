"""Native Color stage with frozen selectors and independent signed energy.

Parameter atlases contain scalar functions of the original post-Tone height.
No RGB grading samples, Python pixel evaluation, or product imports are used.
"""
from dataclasses import dataclass, replace
from functools import cached_property
import math
from numbers import Real
from typing import Optional


TAU = 2 * math.pi
SQRT_HK = math.sqrt(66.)
INVERSE = ((460/1403, 451/1403, 288/1403),
           (460/1403, -891/1403, -261/1403),
           (460/1403, -220/1403, -6300/1403))


@dataclass(frozen=True)
class ColorSockets:
    graph: object
    H: object
    a: object
    b: object
    energy: object
    reference_energy: object
    tonal_h: object
    source_chroma: object
    source_energy: object
    saturated: object = 0.
    chroma_value: Optional[object] = None
    offset_value: Optional[object] = None
    ja_value: Optional[object] = None

    @cached_property
    def chroma(self):
        return self.chroma_value if self.chroma_value is not None else self.graph._color_norm(self.a, self.b)

    @cached_property
    def J_A(self):
        g = self.graph
        if self.ja_value is not None:
            return self.ja_value
        return g.mul(g.mul(g.sign(self.energy), g.sqrt(g.abs(self.energy))),
                     math.sqrt(g._color_energy_scale))

    @property
    def ja(self):
        return self.J_A

    @cached_property
    def q(self):
        return self.graph.vector((self.H, self.a, self.b))

    @cached_property
    def offset(self):
        """H-sqrt(66C), rationalized to retain a small signed energy."""
        g = self.graph
        if self.offset_value is not None:
            return self.offset_value
        base = g.mul(SQRT_HK, g.sqrt(self.chroma))
        magnitude = g._color_magnitude(self.energy, self.chroma)
        return g._color_offset(self.energy, magnitude, base)


def _active(values):
    return any(value != 0 for row in values for value in row)


class ColorGraph:
    """Mixin using Graph's cached arithmetic and caller-owned image sampling."""

    _color_full_topology = False

    @property
    def _color_energy_scale(self):
        return 1.0

    def _color_setting(self, name):
        return getattr(self.prepared.color.settings, name)

    def _color_enabled(self, name):
        color = self.prepared.color
        if name in ('adaptance', 'web'):
            return float(getattr(color, name + '_active'))
        return float(_active(getattr(color.settings.web, name)))

    def _color_route(self, enabled, yes, no):
        return replace(yes, **{name: self.select(enabled, getattr(yes, name), getattr(no, name))
                              for name in ('H', 'a', 'b', 'energy', 'saturated')},
                       chroma_value=self.select(enabled, yes.chroma, no.chroma),
                       offset_value=self.select(enabled, yes.offset, no.offset),
                       ja_value=self.select(enabled, yes.J_A, no.J_A))

    @cached_property
    def _color_source_height(self):
        """Conservative static proof that this grade needs no overflow clamps.

        All encoded responses are bounded by 400. This bound therefore does
        not depend on the current image or sampled validation pixels. Unsafe
        bounds retain the protected graph; they never reject authored controls.
        """
        rho = sum(math.hypot(a, b) for a, b in
                  ((.0582, .1475), (.0258, .0308), (.1347, .0385), (.0289, .0096)))
        ja = 100*(1220/self.prepared.aw)**self.prepared.gamma
        c = 1204*(1+rho)/self.prepared.aw*400*math.hypot(24/11, 4/9)
        height = math.sqrt(ja*ja+66*c*self.prepared.tone.maximum_chroma_gain)
        target = float(self.prepared.tone.remap(height))
        return target

    @cached_property
    def _color_bounds(self):
        return self.prepared.color.finite_bounds(self._color_source_height)

    @property
    def _color_source_squares_safe(self):
        # C0 <= H0²/66 and |E0| <= H0² in every post-Tone source state.
        return self.parameters is None and self._color_source_height < math.sqrt(66.)*2.**29

    @property
    def _color_safe(self):
        return self.parameters is None and all(math.isfinite(self._color_bounds[key]) and self._color_bounds[key] < 2.**58
                   for key in ('H', 'C', 'energy', 'response', 'parameter'))

    def _color_bounded(self, *names, limit=2.**120):
        return self.parameters is None and all(math.isfinite(self._color_bounds[name]) and self._color_bounds[name] < limit
                   for name in names)

    def _color_norm(self, a, b):
        return self._color_norm_result(a, b)[0]

    def _color_norm_result(self, a, b):
        safe = self._color_bounded('C', 'pre_adaptance_C', limit=2.**58)
        value = self.sqrt(self.madd(a, a, self.mul(b, b))) if safe else self.hypot(a, b)
        return (value, 0.) if self._color_bounded('C', 'pre_adaptance_C') else self._color_positive_saturate(value)

    def _color_mul(self, a, b, bound='C'):
        return (self.mul(a, b), 0.) if self._color_bounded(bound) else self.sat_mul(a, b)

    def _color_positive_saturate(self, value):
        return self.minimum(3.4028234663852886e38, value), self.lt(3.4028234663852886e38, value)

    def _color_positive_mul(self, a, b, bound='C'):
        value = self.mul(a, b)
        return (value, 0.) if self._color_bounded(bound) else self._color_positive_saturate(value)

    def _color_sat(self, value):
        return (value, 0.) if self._color_safe else self.saturate(value)

    def _color_vsat(self, value, bound='response'):
        return (value, 0.) if self._color_bounded(bound) else self.vsaturate(value)

    def _color_flag(self, *flags):
        selected = [v for v in flags if not isinstance(v, Real) or v != 0]
        if not selected:
            return 0.
        value = selected[0]
        for other in selected[1:]:
            value = self.maximum(value, other)
        return value

    def _color_exp(self, value, upper, base=math.e):
        # Linear texture interpolation remains in the prepared sample hull.
        # Omit overflow guards when that hull proves the exponential bounded.
        if isinstance(value, Real):
            try:
                exponential = math.exp(value) if base == math.e else math.pow(base, value)
            except OverflowError:
                return 3.4028234663852886e38, 1.
        else:
            exponential = self.op('EXPONENT', value) if base == math.e else self.power(base, value)
        if upper * math.log(base) < 88.:
            return exponential, 0.
        return self._color_positive_saturate(exponential)

    def _color_smoother(self, value):
        t = self.clamp(value)
        v = self.sub(1., t)
        # Positive Bernstein form avoids cancellation near the right endpoint;
        # sharp radial log gains amplify an otherwise small blend error.
        return self.mul(self.mul(t, self.mul(t, t)), self.madd(v, self.madd(6., v, 3.), 1.))

    def _color_height(self, table, h):
        return self.mul(table.cells, self.clamp(self.div(h, table.domain)))

    def _color_field(self, table, x, name):
        rows = {}
        result = []
        for row, channel in table.fields[name]:
            if row not in rows:
                rows[row] = self.sample_field(table, x, row)
            result.append(rows[row][channel])
        return tuple(result)

    def _color_h(self, energy, chroma):
        base = self.mul(SQRT_HK, self.sqrt(chroma))
        magnitude = self._color_magnitude(energy, chroma)
        return self.select(self.lt(energy, 0.), self.sub(self.mul(2., base), magnitude), magnitude)

    def _color_magnitude(self, energy, chroma):
        """sqrt(|E|+66C), using a scaled E carrier for Compositor trees."""
        if self._color_energy_scale == 1.:
            absolute = self.abs(energy)
            if self._color_safe or self._color_bounded('C', 'pre_adaptance_C', limit=2.**96):
                return self.sqrt(self.madd(66., chroma, absolute))
            scale = self.maximum(absolute, chroma)
            normalized = self.madd(66., self.div(chroma, scale), self.div(absolute, scale))
            return self.mul(self.sqrt(scale), self.sqrt(normalized))
        absolute = self.mul(self.sqrt(self.abs(energy)),
                            math.sqrt(self._color_energy_scale))
        base = self.mul(SQRT_HK, self.sqrt(chroma))
        return self.hypot(absolute, base)

    def _color_offset(self, energy, magnitude, base):
        root_scale = math.sqrt(self._color_energy_scale)
        if root_scale == 1.:
            return self.div(energy, self.add(magnitude, base))
        denominator = self.add(self.div(magnitude, root_scale),
                               self.div(base, root_scale))
        return self.mul(root_scale, self.div(energy, denominator))

    def _color_carry(self, state, height, chroma):
        """Stable signed H/C change, without subtracting rounded squares.

        Rationalized source offset and chroma difference preserve the signed
        branch. The direct final product is algebraically the reference's
        carried-energy law. An exact unchanged coordinate retains its input E.
        """
        old_c = state.chroma
        old_b = self.mul(SQRT_HK, self.sqrt(old_c))
        new_b = self.mul(SQRT_HK, self.sqrt(chroma))
        db = self.mul(66., self.div(self.sub(chroma, old_c), self.add(new_b, old_b)))
        dh = self.sub(height, state.H)
        offset = self.add(state.offset, self.sub(dh, db))
        root_scale = math.sqrt(self._color_energy_scale)
        left = self.div(offset, root_scale)
        right = self.div(self.add(self.abs(offset), self.mul(2., new_b)), root_scale)
        energy, flag = self._color_mul(left, right, 'pre_adaptance_energy')
        changed = self.maximum(self.lt(0., self.abs(dh)), self.lt(0., self.abs(db)))
        return (self.safe_select(changed, energy, state.energy),
                self._color_flag(state.saturated, self.mul(changed, flag)), offset)

    def _color_sector(self, angle, angles):
        local = self.add(self.op('FLOORED_MODULO', self.sub(angle, angles[0]), TAU), angles[0])
        index = 0.
        for edge in angles[1:]:
            index = self.add(index, self.sub(1., self.lt(local, edge)))
        return local, index

    def _color_radial(self, c, gain, toe):
        """Stable A and 1-A, retaining the fourth-order neutral toe."""
        scale = self.maximum(c, toe)
        cn, tn = self.div(c, scale), self.div(toe, scale)
        c2, t2 = self.mul(cn, cn), self.mul(tn, tn)
        norm = self.sqrt(self.madd(c2, c2, self.mul(t2, t2)))
        attenuation = self.div(tn, self.sqrt(norm))
        ratio = self.div(c2, norm)
        complement = self.div(self.mul(ratio, ratio),
                              self.mul(self.add(1., attenuation), self.madd(attenuation, attenuation, 1.)))
        upward = self.madd(self.sub(gain, 1.), complement, 1.)
        downward = self.madd(self.sub(1., gain), attenuation, gain)
        factor = self.select(self.lt(gain, 1.), downward, upward)
        return self._color_positive_mul(c, factor)

    def _color_web(self, state):
        prepared = self.prepared.color
        if not (self._color_full_topology or prepared.web_active):
            return state, 1., 0.
        table = prepared.web_table
        x = self._color_height(table, state.tonal_h)
        toe_table = prepared.web_toe_table
        toes = self.sample_field(toe_table, self._color_height(toe_table, state.tonal_h), 0)
        angle = self.op('ARCTAN2', state.b, state.a)
        out_angle = angle
        hue_active = self._color_full_topology or _active(prepared.settings.web.hue_degrees)
        chroma_active = self._color_full_topology or _active(prepared.settings.web.log_chroma)
        scale_active = self._color_full_topology or _active(prepared.settings.web.log_scale)
        c = state.chroma
        if hue_active:
            angles = self._color_field(table, x, 'angles')
            local, index = self._color_sector(angle, angles)
            row = self.madd(2., index, table.angular_row)
            left, width, target, slope = self.sample_field(table, x, row)
            c3, c4, c5, _ = self.sample_field(table, x, self.add(row, 1.))
            u = self.div(self.sub(local, left), width)
            value = self.madd(u, self.add(slope, self.mul(self.mul(u, u),
                    self.madd(u, self.madd(u, c5, c4), c3))), target)
            fade = self._color_smoother(self.div(c, toes[0]))
            out_angle = self.select(self._color_enabled('hue_degrees'),
                                    self.madd(fade, self.sub(value, local), angle), angle)
        c1, scale, flag = c, 1., state.saturated
        if chroma_active or scale_active:
            targets = self._color_field(table, x, 'target_angles')
            local, index = self._color_sector(out_angle, targets)
            row = self.madd(2., index, table.radial_row)
            left, width, gc0, gc1 = self.sample_field(table, x, row)
            # Subtract the nearby, fixed-turn left endpoint directly. The
            # lifted sector coordinate loses precision before this
            # subtraction at sharp radial gains. A wrapped result near
            # TAU can only be a rounded sample just before this sector's
            # left endpoint; clamp it to that endpoint, not the right.
            delta = self.op('FLOORED_MODULO', self.sub(out_angle, left), TAU)
            delta = self.select(self.lt(self.mul(.5, self.add(width, TAU)), delta), 0., delta)
            blend = self._color_smoother(self.div(delta, width))
            chroma_log = self.madd(blend, self.sub(gc1, gc0), gc0)
            if scale_active:
                gs0, gs1, _, _ = self.sample_field(table, x, self.add(row, 1.))
                scale_log = self.madd(blend, self.sub(gs1, gs0), gs0)
            if chroma_active:
                upper = math.inf if self._color_full_topology else math.log(2.)*max(v for row in prepared.settings.web.log_chroma for v in row)-math.log(.9)
                gc, fg = self._color_exp(chroma_log, max(0., upper))
                c1, fc = self._color_radial(c, gc, toes[1])
                enabled = self._color_enabled('log_chroma')
                c1 = self.select(enabled, c1, c)
                flag = self.select(enabled, self._color_flag(flag, fg, fc), flag)
            if scale_active:
                upper = math.inf if self._color_full_topology else math.log(2.)*max(v for row in prepared.settings.web.log_scale for v in row)-math.log(.9)
                gs, fg = self._color_exp(scale_log, max(0., upper))
                c2, fc = self._color_radial(c1, gs, toes[2])
                scale = self.select(self._color_enabled('log_scale'),
                                    self.select(self.lt(0., c1), self.div(c2, c1), 1.), 1.)
                scale_flag = self.select(self._color_enabled('log_scale'),
                                         self._color_flag(fg, fc), 0.)
            else:
                scale_flag = 0.
        else:
            scale_flag = 0.
        radial = self.select(self.lt(0., c), self.div(c1, c), 1.)
        if hue_active:
            a = self.mul(c1, self.op('COSINE', out_angle))
            b = self.mul(c1, self.op('SINE', out_angle))
            same = self.op('COMPARE', out_angle, angle, 0.)
            same = self.maximum(same, self.sub(1., self._color_enabled('hue_degrees')))
            a = self.select(same, self.mul(state.a, radial), a)
            b = self.select(same, self.mul(state.b, radial), b)
        else:
            a, b = self.mul(state.a, radial), self.mul(state.b, radial)
        if chroma_active:
            energy, fe, offset = self._color_carry(state, state.H, c1)
            enabled = self._color_enabled('log_chroma')
            energy = self.select(enabled, energy, state.energy)
            offset = self.select(enabled, offset, state.offset)
            flag = self.select(enabled, self._color_flag(flag, fe), flag)
        else:
            energy = state.energy
            offset = state.offset_value
        result = replace(state, a=a, b=b, energy=energy, saturated=flag,
                         chroma_value=c1, offset_value=offset, ja_value=None)
        changed = self.lt(0., self.abs(self.sub(c1, c)))
        result = replace(result, ja_value=self.select(changed, result.J_A, state.J_A))
        return self._color_route(self._color_enabled('web'), result, state), scale, scale_flag

    def _color_response_vector(self, responses, gains):
        """The three independent response maps evaluated by vector nodes."""
        zero, one = (0.,)*3, (1.,)*3
        absolute = self.vop('ABSOLUTE', responses)
        relative = self.vscale(absolute, 1/400.)
        t = self.vop('MINIMUM', relative, one)
        denominator = self.vadd(self.vsub(one, t), self.vmul(gains, t))
        inside = self.vmul(responses, self.vdiv(gains, denominator))
        y = self.vop('MAXIMUM', self.vsub(relative, one), zero)
        root = self.vop('POWER', self.vadd(one, self.vscale(y, 4.)), (.5,)*3)
        u = self.vdiv(self.vscale(y, 2.), self.vadd(root, one))
        # A zero gain can arise by float32 underflow. Positive u/0 has the
        # positive saturated exterior limit; the exact pole u=0 stays fixed.
        if self._color_bounded('transformed_response'):
            z, fz, overflow_flag = self.vdiv(u, gains), 0., 0.
        else:
            # A reciprocal float32 maximum is subnormal. Native Blender
            # flushes that socket literal to zero while appending a library;
            # two normal factors preserve both the graph and its threshold.
            threshold = self.vscale(self.vscale(u, 2.**-64),
                                    2.**64/3.4028232635611926e38)
            safe_gain = self.vop('MAXIMUM', gains, threshold)
            z, fz = self.vsaturate(self.vdiv(u, safe_gain))
            overflow = self.vop('MAXIMUM', self.vop('SIGN', self.vsub(threshold, gains)), zero)
            zero_gain = self.vsub(one, self.vop('SIGN', gains))
            overflow = self.vop('MAXIMUM', overflow, self.vmul(self.vop('SIGN', u), zero_gain))
            z = self.vselect_components(overflow, (3.4028234663852886e38,)*3, z)
            overflow_components = self.split(overflow)
            overflow_flag = self.maximum(overflow_components[0], self.maximum(*overflow_components[1:]))
        z2, f2 = self._color_vsat(self.vmul(z, z), 'transformed_response')
        outer, fa = self._color_vsat(self.vadd(z2, self.vadd(one, z)), 'transformed_response')
        outer, fm = self._color_vsat(self.vscale(outer, 400.), 'transformed_response')
        outer = self.vmul(self.vop('SIGN', responses), outer)
        mask = self.vop('SIGN', self.vsub(relative, one))
        result = self.vselect_components(mask, outer, inside)
        return result, self._color_flag(fz, f2, fa, fm, overflow_flag)

    def _color_response_delta(self, responses, logs, gains, log_bound):
        """Transport small response changes without subtracting full cones."""
        protected = not self._color_bounded('transformed_response')
        if protected:
            transformed, flag = self._color_response_vector(responses, gains)
            original_logs = logs
            # A broad authored range may require representational protection,
            # while the frozen reach makes this particular log tiny. Retain
            # its analytic delta: subtracting full responses would erase it
            # before H-K repair amplifies the small signed-energy change.
            logs = self.vop('MINIMUM', self.vop('MAXIMUM', logs, (-.1,)*3), (.1,)*3)
            gains = self.vop('POWER', (math.e,)*3, logs)
            log_bound = .1
        zero, one = (0.,)*3, (1.,)*3
        # expm1's sixth-degree Taylor form has error below 3e-11 on [-.1,.1].
        polynomial = (1/720.,)*3
        for coefficient in (1/120., 1/24., 1/6., .5, 1.):
            polynomial = self.vop('MULTIPLY_ADD', polynomial, logs, (coefficient,)*3)
        small = self.vmul(logs, polynomial)
        if log_bound <= .1:
            change = small
        else:
            mask = self.vop('SIGN', self.vsub(self.vop('ABSOLUTE', logs), (.1,)*3))
            change = self.vselect_components(mask, self.vsub(gains, one), small)
        relative = self.vscale(self.vop('ABSOLUTE', responses), 1/400.)
        t = self.vop('MINIMUM', relative, one)
        remaining = self.vsub(one, t)
        denominator = self.vop('MULTIPLY_ADD', gains, t, remaining)
        inside = self.vmul(responses, self.vdiv(self.vmul(change, remaining), denominator))
        y = self.vop('MAXIMUM', self.vsub(relative, one), zero)
        root = self.vop('POWER', self.vop('MULTIPLY_ADD', y, (4.,)*3, one), (.5,)*3)
        u = self.vdiv(self.vscale(y, 2.), self.vadd(root, one))
        z = self.vdiv(u, gains)
        outer = self.vmul(self.vmul(self.vscale(u, -400.), self.vdiv(change, gains)),
                          self.vadd(one, self.vadd(u, z)))
        outer = self.vmul(self.vop('SIGN', responses), outer)
        mask = self.vop('SIGN', self.vsub(relative, one))
        delta = self.vselect_components(mask, outer, inside)
        if protected:
            small_log = self.vop('SIGN', self.vsub((.1,)*3, self.vop('ABSOLUTE', original_logs)))
            return self.vselect_components(small_log, delta, self.vsub(transformed, responses)), flag
        return delta, 0.

    def _color_polynomial_delta(self, coefficients, value, delta):
        """P(value+delta)-P(value), without subtracting close polynomials."""
        current, change = coefficients[0], 0.
        shifted = self.add(value, delta)
        for coefficient in coefficients[1:]:
            change = self.madd(change, shifted, self.mul(current, delta))
            current = self.madd(current, value, coefficient)
        return change

    def _color_power_delta(self, relative, exponent):
        """(1+r)^p-1 on the small relative-change branch."""
        relative = self.clamp(relative, -.01, .01)
        coefficients, coefficient = [], 1.
        for order in range(1, 9):
            coefficient *= (exponent-order+1)/order
            coefficients.append(coefficient)
        value = coefficients[-1]
        for coefficient in reversed(coefficients[:-1]):
            value = self.madd(value, relative, coefficient)
        return self.mul(relative, value)

    def _color_adaptance_controls(self):
        color = self.prepared.color
        return tuple(color.anchors), tuple(float(any(value != 0. for value in row))
                                           for row in color.settings.adaptance)

    def _color_adaptance_support(self, height):
        """Preserve exactly zero cardinal intervals across linear atlas cells."""
        anchors, flags = self._color_adaptance_controls()
        enabled = flags[-1]
        for index in reversed(range(3)):
            interval = self.maximum(flags[index], flags[index+1])
            enabled = self.select(self.lt(height, anchors[index+1]), interval, enabled)
        enabled = self.select(self.lt(height, anchors[0]), flags[0], enabled)
        for anchor, flag in zip(anchors, flags):
            enabled = self.select(self.op('COMPARE', height, anchor, 0.), flag, enabled)
        return enabled

    def _color_adaptance_height(self, state, direct, achromatic, opponent_scale,
                                eccentricity, da, du, dw, factor_log):
        """Carry reflected H through a small response change without cancellation.

        H can be hundreds while sqrt(66C) is hundreds of millions. Rebuilding
        it from rounded E and C discards an authoritative coordinate. Analytic
        relative differences retain the small Adaptance request instead.
        """
        c = state.chroma
        ca, sa = self.div(state.a, c), self.div(state.b, c)
        requested_ua = self.div(self.div(du, opponent_scale), c)
        requested_ub = self.div(self.div(dw, opponent_scale), c)
        # Both candidates are evaluated by Blender Mix nodes. Keep this
        # small-change candidate finite even when the direct branch wins.
        # Eligibility still uses the original, unclamped response changes.
        ua = self.clamp(requested_ua, -.01, .01)
        ub = self.clamp(requested_ub, -.01, .01)
        radius_square_delta = self.madd(ua, ua, self.madd(ub, ub,
            self.mul(2., self.madd(ca, ua, self.mul(sa, ub)))))
        radius = self.sqrt(self.add(1., radius_square_delta))
        radius_delta = self.div(radius_square_delta, self.add(radius, 1.))
        dc = self.div(self.madd(-1., self.mul(ca, radius_delta), ua), radius)
        ds = self.div(self.madd(-1., self.mul(sa, radius_delta), ub), radius)
        dp = self._color_polynomial_delta((.2312, -.5388, -.2828, .3459, 1.0547), ca, dc)
        dq = self._color_polynomial_delta((.0768, .154, -.1, -.186), ca, dc)
        shifted = self.add(ca, dc)
        q = self.madd(self.madd(self.madd(.0768, shifted, .154), shifted, -.1), shifted, -.186)
        eccentricity_delta = self.add(dp, self.madd(sa, dq, self.mul(ds, q)))
        eccentricity_relative = self.div(eccentricity_delta, eccentricity)
        chroma_relative = self.add(radius_delta,
            self.madd(radius_delta, eccentricity_relative, eccentricity_relative))
        log = self.clamp(factor_log, -.1, .1)
        exponential = 1/math.factorial(9)
        for order in range(8, 0, -1):
            exponential = self.madd(exponential, log, 1/math.factorial(order))
        factor_delta = self.mul(log, exponential)
        chroma_relative = self.add(chroma_relative,
            self.madd(chroma_relative, factor_delta, factor_delta))
        requested_achromatic_relative = self.div(da, achromatic)
        achromatic_relative = self.clamp(requested_achromatic_relative, -1., 1.)
        achromatic_relative = self.add(achromatic_relative,
            self.madd(achromatic_relative, factor_delta, factor_delta))
        energy_relative = self._color_power_delta(achromatic_relative, 2*self.prepared.gamma)
        base = self.mul(SQRT_HK, self.sqrt(c))
        magnitude = self._color_magnitude(state.energy, c)
        er = self.div(self.mul(math.sqrt(self._color_energy_scale), self.sqrt(self.abs(state.energy))), magnitude)
        cr = self.div(base, magnitude)
        square_relative = self.madd(self.mul(er, er), energy_relative,
                                    self.mul(self.mul(cr, cr), chroma_relative))
        magnitude_delta = self.mul(magnitude,
            self.div(square_relative, self.add(self.sqrt(self.add(1., square_relative)), 1.)))
        base_delta = self.mul(base,
            self.div(chroma_relative, self.add(self.sqrt(self.add(1., chroma_relative)), 1.)))
        height_delta = self.select(self.lt(state.energy, 0.),
            self.madd(2., base_delta, self.mul(-1., magnitude_delta)), magnitude_delta)
        stable = self.add(state.H, height_delta)
        small = self.mul(self.lt(self.abs(achromatic_relative), .01),
                         self.lt(self.abs(chroma_relative), .01))
        small = self.mul(small, self.mul(self.lt(self.abs(factor_log), .1),
            self.mul(self.lt(self.abs(requested_ua), .01), self.lt(self.abs(requested_ub), .01))))
        small = self.mul(small, self.lt(self.abs(requested_achromatic_relative), 1.))
        small = self.mul(small, self.mul(self.lt(0., self.abs(achromatic)), self.lt(0., c)))
        return self.select(small, stable, direct)

    def _color_adaptance(self, state):
        prepared = self.prepared.color
        if not (self._color_full_topology or prepared.adaptance_active):
            return state
        table = prepared.adaptance_table
        s = self.mul(math.sqrt(self.prepared.aw/(3.05*400.)),
                     self.power(self.mul(.01, state.tonal_h), 1/(2*self.prepared.gamma)))
        x = self.mul(table.cells, self.div(s, self.add(1., s)))
        support = self._color_adaptance_support(state.tonal_h)
        fields = tuple(self.mul(support, value) for value in self.sample_field(table, x, 0))
        if self._color_source_squares_safe:
            a2 = self.mul(prepared.settings.adaptance_half_saturation**2, self.abs(state.source_energy))
            c2 = self.mul(state.source_chroma, state.source_chroma)
            scale = self.maximum(a2, c2)
            an, cn = self.div(a2, scale), self.div(c2, scale)
            a4, c4 = self.mul(an, an), self.mul(cn, cn)
        else:
            reach_a = self.mul(self._color_setting('adaptance_half_saturation'),
                self.mul(math.sqrt(self._color_energy_scale),
                         self.sqrt(self.abs(state.source_energy))))
            scale = self.maximum(reach_a, state.source_chroma)
            an, cn = self.div(reach_a, scale), self.div(state.source_chroma, scale)
            a2, c2 = self.mul(an, an), self.mul(cn, cn)
            a4, c4 = self.mul(a2, a2), self.mul(c2, c2)
        reach = self.select(self.lt(0., state.source_chroma), self.div(a4, self.add(a4, c4)), 1.)
        # Each atlas channel is convexly interpolated; its maximum is an exact
        # bound on the represented coefficient, independent of pixel values.
        logs = self.vscale(self.vector(fields[:3]), reach)
        log_bound = math.inf if self._color_full_topology else float(abs(table.pixels[..., :3]).max())
        gain_vector = (self.vector(tuple(self.op('EXPONENT', value) for value in self.split(logs)))
                       if log_bound > 1 else self.vop('POWER', (math.e,)*3, logs))
        maximum_log = math.inf if self._color_full_topology else max(0., float(table.pixels[..., :3].max()))
        if maximum_log < 88.:
            gain_flag = 0.
        else:
            gain_vector, gain_flag = self.vsaturate(gain_vector)
        factor_log = self.mul(reach, fields[3])
        factor, factor_flag = self._color_exp(factor_log,
                                            math.inf if self._color_full_topology else max(0., float(table.pixels[..., 3].max())))
        eccentricity, _ = self._eccentricity(state.a, state.b,
            robust=not self._color_bounded('pre_adaptance_C', limit=2.**58))
        input_eccentricity = eccentricity
        opponent_scale = self.div(self.prepared.aw/1204., eccentricity)
        achromatic = self.mul(self.prepared.aw/100.**(1/self.prepared.gamma),
            self.mul(self.sign(state.energy), self.mul(
                self.power(self.abs(state.energy), 1/(2*self.prepared.gamma)),
                self._color_energy_scale**(1/(2*self.prepared.gamma)))))
        # Keep the common neutral response separate until the last addition.
        # Scaling rounded opponent components before a cancelling row dot can
        # lose enough cone precision to amplify near the exterior pole.
        opponent = self.vadd(self.vscale(tuple(row[1] for row in INVERSE), state.a),
                             self.vscale(tuple(row[2] for row in INVERSE), state.b))
        neutral_response = self.mul(1/3.05, achromatic)
        response_vector, response_flag = self._color_vsat(self.vop('MULTIPLY_ADD', opponent,
            self.vector((opponent_scale,)*3), self.vector((neutral_response,)*3)), 'input_response')
        delta, transform_flag = self._color_response_delta(
            response_vector, logs, gain_vector, log_bound)
        flags = [state.saturated, factor_flag, transform_flag, response_flag, gain_flag]
        if self._color_bounded('response'):
            magnitude = 1.
            r, g, b = self.split(delta)
        else:
            absolute = self.split(self.vop('ABSOLUTE', delta))
            magnitude = self.maximum(absolute[0], self.maximum(*absolute[1:]))
            r, g, b = self.split(self.vdiv(delta, self.vector((magnitude,)*3)))
        da, fac = self._color_mul(magnitude, self.madd(2., r, self.madd(.05, b, g)), 'response')
        un = self.madd(1/11, self.sub(b, g), self.sub(r, g))
        wn = self.div(self.add(self.sub(r, b), self.sub(g, b)), 9.)
        du, fu = self._color_mul(magnitude, un, 'response')
        dw, fw = self._color_mul(magnitude, wn, 'response')
        ac = self.add(achromatic, da)
        u, w = self.madd(state.a, opponent_scale, du), self.madd(state.b, opponent_scale, dw)
        if not self._color_bounded('response'):
            ac, ac_flag = self.saturate(ac)
            u, u_flag = self.saturate(u)
            w, w_flag = self.saturate(w)
            flags.extend((ac_flag, u_flag, w_flag))
        ac, fscale_a = self._color_mul(ac, factor, 'response')
        u, fscale_u = self._color_mul(u, factor, 'response')
        w, fscale_w = self._color_mul(w, factor, 'response')
        flags.extend((fscale_a, fscale_u, fscale_w))
        eccentricity, _ = self._eccentricity(u, w,
            robust=not self._color_bounded('response', limit=2.**58))
        chroma_factor = self.mul(1204/self.prepared.aw, eccentricity)
        a, fa = self._color_mul(u, chroma_factor)
        b, fb = self._color_mul(w, chroma_factor)
        ja, fj = self._color_positive_mul(100., self.power(self.div(self.abs(ac), self.prepared.aw), self.prepared.gamma),
                                 'post_adaptance_H')
        root_scale = math.sqrt(self._color_energy_scale)
        normalized_ja = self.div(ja, root_scale)
        energy, fe = self._color_positive_mul(
            normalized_ja, normalized_ja, 'post_adaptance_energy')
        energy = self.mul(self.sign(ac), energy)
        # A calibrated neutral carries the original achromatic energy exactly.
        neutral = self.mul(self.sub(1., self.lt(0., state.source_chroma)),
                           self.sub(1., self.lt(0., state.chroma)))
        energy = self.safe_select(neutral, state.energy, energy)
        chroma, chroma_flag = self._color_norm_result(a, b)
        height = self._color_h(energy, chroma)
        height = self._color_adaptance_height(state, height, achromatic,
            opponent_scale, input_eccentricity, da, du, dw, factor_log)
        log_components = self.split(self.vop('ABSOLUTE', logs))
        changed_log = self.maximum(self.abs(factor_log), self.maximum(
            log_components[0], self.maximum(log_components[1], log_components[2])))
        active = self.mul(self.lt(0., changed_log), self.lt(0., state.tonal_h))
        changed = self._color_flag(*flags, fac, fu, fw, fa, fb, fj, fe, chroma_flag)
        result = replace(state, H=self.safe_select(active, height, state.H),
                       a=self.safe_select(active, a, state.a), b=self.safe_select(active, b, state.b),
                       energy=self.safe_select(active, energy, state.energy),
                       chroma_value=self.select(active, chroma, state.chroma), offset_value=None,
                       ja_value=self.safe_select(active,
                           self.safe_select(neutral, state.J_A, self.mul(self.sign(ac), ja)),
                           state.J_A),
                       saturated=self._color_flag(state.saturated, self.mul(active, changed)))
        return self._color_route(self._color_enabled('adaptance'), result, state)

    def _color_input(self, appearance):
        if appearance.graph is not self:
            raise ValueError('Appearance sockets belong to another Graph')
        source_energy = appearance.energy
        return ColorSockets(self, appearance.H, appearance.a, appearance.b, source_energy,
                             source_energy, appearance.magnitude, appearance.chroma, source_energy,
                             getattr(appearance, 'saturated', 0.), appearance.chroma,
                             self._color_offset(source_energy, appearance.magnitude,
                                      self.mul(SQRT_HK, self.sqrt(appearance.chroma))),
                             appearance.J_A)

    def color(self, appearance, *, guarded=False):
        state = self._color_input(appearance)
        prepared = self.prepared.color
        if not (self._color_full_topology or prepared.active):
            return self.hk_guard(state) if guarded else state
        state, scale, scale_flag = self._color_web(state)
        state = self._color_adaptance(state)
        if guarded:
            repaired = self.hk_guard(state)
            state = replace(state, H=repaired.H, a=repaired.a, b=repaired.b,
                            energy=repaired.energy, saturated=repaired.saturated,
                            chroma_value=repaired.chroma, offset_value=None,
                            ja_value=repaired.J_A)
        if self._color_full_topology or _active(prepared.settings.web.log_scale):
            state = self._color_scale(state, scale, scale_flag)
        return state

    def color_and_guard(self, appearance):
        """Repair frozen post-Tone energy once, before applying final Web Scale."""
        return self.color(appearance, guarded=True)

    def _color_scale(self, state, scale, scale_flag=0.):
        a, fa = self._color_mul(state.a, scale)
        b, fb = self._color_mul(state.b, scale)
        energy, fe1 = self._color_mul(state.energy, scale, 'energy')
        energy, fe2 = self._color_mul(energy, scale, 'energy')
        ja, fj = self._color_mul(state.J_A, scale, 'H')
        chroma, chroma_flag = self._color_norm_result(a, b)
        height = self._color_h(energy, chroma)
        same = self.op('COMPARE', scale, 1., 0.)
        return replace(state, H=self.select(same, state.H, height), a=a, b=b, energy=energy,
                       chroma_value=self.select(same, state.chroma, chroma), offset_value=None,
                       ja_value=ja,
                       saturated=self._color_flag(state.saturated, scale_flag, fa, fb, fe1, fe2, fj, chroma_flag))

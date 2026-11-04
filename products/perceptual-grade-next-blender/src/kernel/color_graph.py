"""Native Color stage with frozen selectors and independent signed energy.

Parameter atlases contain scalar functions of the original post-Tone height.
No RGB grading samples, Python pixel evaluation, or product imports are used.
"""
from dataclasses import dataclass, replace
from functools import cached_property
import math
from numbers import Real


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
    chroma_value: object = None
    offset_value: object = None

    @cached_property
    def chroma(self):
        return self.chroma_value if self.chroma_value is not None else self.graph._color_norm(self.a, self.b)

    @cached_property
    def J_A(self):
        g = self.graph
        return g.mul(g.sign(self.energy), g.sqrt(g.abs(self.energy)))

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
        return g.div(self.energy, g.add(magnitude, base))


def _active(values):
    return any(value != 0 for row in values for value in row)


class ColorGraph:
    """Mixin using Graph's cached arithmetic and caller-owned image sampling."""

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
        height = math.sqrt(ja*ja+66*c)
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

    def _color_dot4(self, values, weights):
        value = 0.
        for a, b in zip(values, weights):
            value = self.madd(a, b, value)
        return value

    def _color_h(self, energy, chroma):
        base = self.mul(SQRT_HK, self.sqrt(chroma))
        magnitude = self._color_magnitude(energy, chroma)
        return self.select(self.lt(energy, 0.), self.sub(self.mul(2., base), magnitude), magnitude)

    def _color_magnitude(self, energy, chroma):
        """sqrt(|E|+66C) without overflowing either weighted term.

        The normalized sum is at most 67. Its square root and the square
        root of the finite scale therefore remain directly representable.
        """
        absolute = self.abs(energy)
        # Stage handoffs carry finite (possibly saturated) E. With C<2^96,
        # 66C<2^103, half the final float32 ULP; even |E|=FLT_MAX therefore
        # rounds to a finite sum. This avoids unnecessary scaled arithmetic
        # when only the unchanged float64 energy bound exceeds float32.
        if self._color_safe or self._color_bounded('C', 'pre_adaptance_C', limit=2.**96):
            return self.sqrt(self.madd(66., chroma, absolute))
        scale = self.maximum(absolute, chroma)
        normalized = self.madd(66., self.div(chroma, scale), self.div(absolute, scale))
        return self.mul(self.sqrt(scale), self.sqrt(normalized))

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
        energy, flag = self._color_mul(offset, self.add(self.abs(offset), self.mul(2., new_b)),
                                       'pre_adaptance_energy')
        changed = self.maximum(self.lt(0., self.abs(dh)), self.lt(0., self.abs(db)))
        return (self.safe_select(changed, energy, state.energy),
                self._color_flag(state.saturated, self.mul(changed, flag)), offset)

    def _color_drivers(self, state):
        c = state.source_chroma
        if self._color_source_squares_safe:
            c2 = self.mul(c, c)
            r2 = self.mul((35./75.)**2, self.abs(state.source_energy))
            visible_square = self.add(c2, 4.)
            visibility_den = self.sqrt(visible_square)
            visibility = self.div(c2, visible_square)
        else:
            r = self.mul(35./75., self.sqrt(self.abs(state.source_energy)))
            scale = self.maximum(c, r)
            cn, rn = self.div(c, scale), self.div(r, scale)
            c2, r2 = self.mul(cn, cn), self.mul(rn, rn)
            visibility_den = self._color_norm(c, 2.)
            v = self.div(c, visibility_den)
            visibility = self.mul(v, v)
        den = self.add(c2, r2)
        return (self.mul(visibility, self.div(r2, den)),
                self.mul(visibility, self.div(c2, den)),
                self.div(state.a, visibility_den), self.div(state.b, visibility_den))

    def _color_terms(self, state):
        prepared = self.prepared.color
        if not (prepared.lightness_active or prepared.chroma_active):
            return state
        chroma_fields = _active(prepared.settings.chroma)
        if prepared.lightness_active or chroma_fields:
            x = self._color_height(prepared.coefficient_table, state.tonal_h)
            drivers = self._color_drivers(state)
        h, a, b, flag = state.H, state.a, state.b, state.saturated
        if prepared.lightness_active:
            values = self.sample_field(prepared.coefficient_table, x, 0)
            h = self.add(h, self._color_dot4(values, drivers))
        if prepared.chroma_active:
            exponent = prepared.settings.global_gain
            if chroma_fields:
                values = self.sample_field(prepared.coefficient_table, x, 1)
                exponent = self.add(exponent, self._color_dot4(values, drivers))
            upper = prepared.settings.global_gain + max(
                max(abs(row[0]), abs(row[1])) + math.hypot(*row[2:])
                for row in prepared.settings.chroma)
            gain, fs = self._color_exp(exponent, upper, 2.)
            a, fa = self._color_mul(a, gain)
            b, fb = self._color_mul(b, gain)
            flag = self._color_flag(flag, fs, fa, fb)
        chroma, chroma_flag = self._color_norm_result(a, b)
        flag = self._color_flag(flag, chroma_flag)
        energy, fe, offset = self._color_carry(state, h, chroma)
        # Original black is fixed even when tonal lightness coefficients exist.
        nonblack = self.lt(0., state.tonal_h)
        return replace(state, H=self.safe_select(nonblack, h, state.H),
                       a=self.safe_select(nonblack, a, state.a),
                       b=self.safe_select(nonblack, b, state.b),
                       energy=self.safe_select(nonblack, energy, state.energy),
                       chroma_value=chroma, offset_value=offset,
                       saturated=self._color_flag(state.saturated, self.mul(nonblack, self._color_flag(flag, fe))))

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
        if not prepared.web_active:
            return state, 1., 0.
        table = prepared.web_table
        x = self._color_height(table, state.tonal_h)
        toe_table = prepared.web_toe_table
        toes = self.sample_field(toe_table, self._color_height(toe_table, state.tonal_h), 0)
        angle = self.op('ARCTAN2', state.b, state.a)
        out_angle = angle
        hue_active = _active(prepared.settings.web.hue_degrees)
        chroma_active = _active(prepared.settings.web.log_chroma)
        scale_active = _active(prepared.settings.web.log_scale)
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
            out_angle = self.madd(fade, self.sub(value, local), angle)
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
                upper = math.log(2.)*max(v for row in prepared.settings.web.log_chroma for v in row)-math.log(.9)
                gc, fg = self._color_exp(chroma_log, max(0., upper))
                c1, fc = self._color_radial(c, gc, toes[1])
                flag = self._color_flag(flag, fg, fc)
            if scale_active:
                upper = math.log(2.)*max(v for row in prepared.settings.web.log_scale for v in row)-math.log(.9)
                gs, fg = self._color_exp(scale_log, max(0., upper))
                c2, fc = self._color_radial(c1, gs, toes[2])
                scale = self.select(self.lt(0., c1), self.div(c2, c1), 1.)
                scale_flag = self._color_flag(fg, fc)
            else:
                scale_flag = 0.
        else:
            scale_flag = 0.
        radial = self.select(self.lt(0., c), self.div(c1, c), 1.)
        if hue_active:
            a = self.mul(c1, self.op('COSINE', out_angle))
            b = self.mul(c1, self.op('SINE', out_angle))
            same = self.op('COMPARE', out_angle, angle, 0.)
            a = self.select(same, self.mul(state.a, radial), a)
            b = self.select(same, self.mul(state.b, radial), b)
        else:
            a, b = self.mul(state.a, radial), self.mul(state.b, radial)
        if chroma_active:
            energy, fe, offset = self._color_carry(state, state.H, c1)
            flag = self._color_flag(flag, fe)
        else:
            energy = state.energy
            offset = state.offset_value
        return replace(state, a=a, b=b, energy=energy, saturated=flag,
                       chroma_value=c1, offset_value=offset), scale, scale_flag

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
            threshold = self.vscale(u, 1/3.4028232635611926e38)
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
        if not self._color_bounded('transformed_response'):
            transformed, flag = self._color_response_vector(responses, gains)
            return self.vsub(transformed, responses), flag
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
        return self.vselect_components(mask, outer, inside), 0.

    def _color_adaptance(self, state):
        prepared = self.prepared.color
        if not prepared.adaptance_active:
            return state
        table = prepared.adaptance_table
        s = self.mul(math.sqrt(self.prepared.aw/(3.05*400.)),
                     self.power(self.mul(.01, state.tonal_h), 1/(2*self.prepared.gamma)))
        x = self.mul(table.cells, self.div(s, self.add(1., s)))
        fields = self.sample_field(table, x, 0)
        if self._color_source_squares_safe:
            a2 = self.mul(prepared.settings.adaptance_half_saturation**2, self.abs(state.source_energy))
            c2 = self.mul(state.source_chroma, state.source_chroma)
            scale = self.maximum(a2, c2)
            an, cn = self.div(a2, scale), self.div(c2, scale)
            a4, c4 = self.mul(an, an), self.mul(cn, cn)
        else:
            reach_a = self.mul(prepared.settings.adaptance_half_saturation,
                               self.sqrt(self.abs(state.source_energy)))
            scale = self.maximum(reach_a, state.source_chroma)
            an, cn = self.div(reach_a, scale), self.div(state.source_chroma, scale)
            a2, c2 = self.mul(an, an), self.mul(cn, cn)
            a4, c4 = self.mul(a2, a2), self.mul(c2, c2)
        reach = self.select(self.lt(0., state.source_chroma), self.div(a4, self.add(a4, c4)), 1.)
        # Each atlas channel is convexly interpolated; its maximum is an exact
        # bound on the represented coefficient, independent of pixel values.
        logs = self.vscale(self.vector(fields[:3]), reach)
        log_bound = float(abs(table.pixels[..., :3]).max())
        gain_vector = (self.vector(tuple(self.op('EXPONENT', value) for value in self.split(logs)))
                       if log_bound > 1 else self.vop('POWER', (math.e,)*3, logs))
        maximum_log = max(0., float(table.pixels[..., :3].max()))
        if maximum_log < 88.:
            gain_flag = 0.
        else:
            gain_vector, gain_flag = self.vsaturate(gain_vector)
        factor, factor_flag = self._color_exp(self.mul(reach, fields[3]),
                                            max(0., float(table.pixels[..., 3].max())))
        eccentricity, _ = self._eccentricity(state.a, state.b,
            robust=not self._color_bounded('pre_adaptance_C', limit=2.**58))
        opponent_scale = self.div(self.prepared.aw/1204., eccentricity)
        achromatic = self.mul(self.prepared.aw/100.**(1/self.prepared.gamma),
                             self.mul(self.sign(state.energy), self.power(self.abs(state.energy), 1/(2*self.prepared.gamma))))
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
        energy, fe = self._color_positive_mul(ja, ja, 'post_adaptance_energy')
        energy = self.mul(self.sign(ac), energy)
        # A calibrated neutral carries the original achromatic energy exactly.
        neutral = self.mul(self.sub(1., self.lt(0., state.source_chroma)),
                           self.sub(1., self.lt(0., state.chroma)))
        energy = self.safe_select(neutral, state.energy, energy)
        chroma, chroma_flag = self._color_norm_result(a, b)
        height = self._color_h(energy, chroma)
        active = self.mul(self.lt(0., reach), self.lt(0., state.tonal_h))
        changed = self._color_flag(*flags, fac, fu, fw, fa, fb, fj, fe, chroma_flag)
        return replace(state, H=self.safe_select(active, height, state.H),
                       a=self.safe_select(active, a, state.a), b=self.safe_select(active, b, state.b),
                       energy=self.safe_select(active, energy, state.energy),
                       chroma_value=self.select(active, chroma, state.chroma), offset_value=None,
                       saturated=self._color_flag(state.saturated, self.mul(active, changed)))

    def _color_input(self, appearance):
        if appearance.graph is not self:
            raise ValueError('Appearance sockets belong to another Graph')
        source_energy = appearance.energy
        return ColorSockets(self, appearance.H, appearance.a, appearance.b, source_energy,
                             source_energy, appearance.magnitude, appearance.chroma, source_energy,
                             getattr(appearance, 'saturated', 0.), appearance.chroma,
                             self.div(source_energy, self.add(appearance.magnitude,
                                      self.mul(SQRT_HK, self.sqrt(appearance.chroma)))))

    def color(self, appearance):
        state = self._color_input(appearance)
        prepared = self.prepared.color
        if not prepared.active:
            return state
        state = self._color_terms(state)
        state, scale, scale_flag = self._color_web(state)
        state = self._color_adaptance(state)
        if _active(prepared.settings.web.log_scale):
            state = self._color_scale(state, scale, scale_flag)
        return state

    def _color_scale(self, state, scale, scale_flag=0.):
        a, fa = self._color_mul(state.a, scale)
        b, fb = self._color_mul(state.b, scale)
        energy, fe1 = self._color_mul(state.energy, scale, 'energy')
        energy, fe2 = self._color_mul(energy, scale, 'energy')
        chroma, chroma_flag = self._color_norm_result(a, b)
        height = self._color_h(energy, chroma)
        same = self.op('COMPARE', scale, 1., 0.)
        return replace(state, H=self.select(same, state.H, height), a=a, b=b, energy=energy,
                       chroma_value=chroma, offset_value=None,
                       saturated=self._color_flag(state.saturated, scale_flag, fa, fb, fe1, fe2, chroma_flag))

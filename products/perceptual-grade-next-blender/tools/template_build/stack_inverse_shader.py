"""Invert Tone and Chroma after a bounded search over Warp inputs."""


INVERSE_SOURCE = r"""
float stack_max_abs(vec4 value) {
    vec4 a = abs(value);
    return max(max(a.x, a.y), max(a.z, a.w));
}

bool stack_finite(vec4 value) {
    return !any(isnan(value)) && !any(isinf(value));
}

float stack_ja(vec4 state) {
    return sign(state.w) * sqrt(abs(state.w));
}

vec4 stack_state(vec3 coordinates) {
    float ja = coordinates.x;
    float base = sqrt(66.0 * length(coordinates.yz));
    float magnitude = length(vec2(ja, base));
    float height = ja < 0.0 ? 2.0 * base - magnitude : magnitude;
    return vec4(height, coordinates.yz, ja * abs(ja));
}

float stack_inverse_radial_gain(float y, float knee, float low, float high) {
    if (knee == 0.0 || low == high) return 1.0 / high;
    float scale = max(y, knee);
    y /= scale;
    knee /= scale;
    float d = low * knee - y;
    float root = length(vec2(d, 2.0 * sqrt(high * knee) * sqrt(y)));
    return d >= 0.0 ? 2.0 * knee / (root + d) : (root - d) / (2.0 * high * y);
}

vec3 stack_undo_tone(vec3 point) {
    vec4 gains = texelFetch(grade_parameters, ivec2(stack_chroma_gain_slot, grade_index), 0);
    vec4 controls = texelFetch(grade_parameters, ivec2(stack_chroma_tone_slot, grade_index), 0);
    float chroma = length(point.yz);
    if (gains.w != 0.0 && chroma != 0.0) {
        float j = abs(point.x);
        float base = (35.0 / 75.0) * j;
        float offset = j / controls.z - 1.0;
        float t = min(abs(offset), 1.0);
        float tonal = exp2((offset < 0.0 ? controls.x : controls.y) * t * t * (3.0 - 2.0 * t));
        float gain = stack_inverse_radial_gain(chroma, base / 9.0, 1.0, tonal);
        gain *= stack_inverse_radial_gain(chroma * gain, base * gains.z, gains.x, gains.y);
        point.yz *= gain;
        chroma *= gain;
    }
    float chroma_term = 66.0 * chroma;
    float desired = length(vec2(point.x, sqrt(chroma_term)));
    if (desired == 0.0) return point;
    if (controls.w != 0.0) {
        vec4 tone = texelFetch(grade_parameters, ivec2(stack_tone_scalars_slot, grade_index), 0);
        float y = desired * 0.01;
        float position = 1.0;
        if (desired != 100.0 * tone.w) {
            // The positive linear slope bounds the inverse of the packed curve.
            float low = 0.0;
            float high = y / tone.z;
            for (int i = 0; i < 32; ++i) {
                float middle = low + 0.5 * (high - low);
                if (middle == low || middle == high) break;
                if (stack_tone_normalized(middle) < y) low = middle;
                else high = middle;
            }
            position = low + 0.5 * (high - low);
        }
        float compressed = position * tone.y;
        float source = 100.0 * compressed * stack_inverse_radial_gain(compressed, 2.0 * tone.x, 0.5, 1.0);
        if (chroma == 0.0) {
            point.x = sign(point.x) * source;
        } else {
            float ratio = source / desired;
            float c = chroma_term / desired / desired;
            float j = point.x / desired;
            point *= safe_divide(2.0 * ratio * ratio, length(vec2(c, 2.0 * j * ratio)) + c);
        }
    }
    return point;
}

vec4 stack_features(vec4 state) {
    return vec4(state.x, stack_ja(state), state.yz);
}

vec4 stack_inverse_residual(vec3 variables, vec3 scale, vec4 target, vec4 weights) {
    vec4 actual = stack_warp(stack_state(variables * scale));
    if (!stack_finite(actual)) return vec4(1e12);
    return clamp((stack_features(actual) - target) * weights, -1e12, 1e12);
}

vec3 stack_normal_step(vec4 j[3], vec4 residual, float damping) {
    float a = dot(j[0], j[0]), b = dot(j[1], j[1]), c = dot(j[2], j[2]);
    float ab = dot(j[0], j[1]), ac = dot(j[0], j[2]), bc = dot(j[1], j[2]);
    float lambda = damping * (1.0 + a + b + c);
    float l00 = sqrt(a + lambda), l10 = ab / l00, l20 = ac / l00;
    float l11 = sqrt(max(b + lambda - l10 * l10, lambda));
    float l21 = (bc - l20 * l10) / l11;
    float l22 = sqrt(max(c + lambda - l20 * l20 - l21 * l21, lambda));
    vec3 g = vec3(dot(j[0], residual), dot(j[1], residual), dot(j[2], residual));
    float y0 = g.x / l00, y1 = (g.y - l10 * y0) / l11;
    float y2 = (g.z - l20 * y0 - l21 * y1) / l22;
    float z2 = y2 / l22, z1 = (y1 - l21 * z2) / l11;
    return vec3((y0 - l10 * z1 - l20 * z2) / l00, z1, z2);
}

vec3 stack_inverse_fit(vec3 seed, vec4 target, vec4 weights) {
    vec3 scale = max(vec3(abs(seed.x), length(seed.yz), length(seed.yz)),
                     vec3(0.25));
    // Tone bounds achromatic lightness and the chroma before gain. Chroma
    // can then expand while the achromatic coordinate stays fixed.
    float height = stack_tone_magnitude(stack_max_magnitude);
    vec4 gains = texelFetch(grade_parameters, ivec2(stack_chroma_gain_slot, grade_index), 0);
    vec4 controls = texelFetch(grade_parameters, ivec2(stack_chroma_tone_slot, grade_index), 0);
    float max_gain = max(gains.x, gains.y) * exp2(max(0.0, max(controls.x, controls.y)));
    float c = (height * height / 66.0) * max_gain;
    vec3 bound = vec3(height, c, c) / scale;
    vec3 x = clamp(seed / scale, -bound, bound);
    vec4 r = stack_inverse_residual(x, scale, target, weights);
    float score = dot(r, r);
    float damping = 1e-4;
    bool refresh = true;
    vec4 jac[3];
    for (int iteration = 0; iteration < 12; ++iteration) {
        if (stack_max_abs(r) <= 2e-6) break;
        if (refresh) {
            for (int k = 0; k < 3; ++k) {
                vec3 delta = vec3(0.0);
                delta[k] = 0.002;
                vec3 high = min(x + delta, bound);
                vec3 low = max(x - delta, -bound);
                vec4 upper = stack_inverse_residual(high, scale, target, weights);
                vec4 lower = stack_inverse_residual(low, scale, target, weights);
                jac[k] = (upper - lower) / (high[k] - low[k]);
            }
        }
        vec3 step = stack_normal_step(jac, r, damping);
        step /= max(1.0, stack_max_abs(vec4(step, 0.0)) / 1.5);
        bool improved = false;
        for (int trial = 0; trial < 3; ++trial) {
            float fraction = trial == 0 ? 1.0 : (trial == 1 ? 0.5 : 0.125);
            vec3 next = clamp(x - fraction * step, -bound, bound);
            vec4 nr = stack_inverse_residual(next, scale, target, weights);
            float next_score = dot(nr, nr);
            if (next_score < score) {
                vec3 delta = next - x;
                vec4 change = nr - r - jac[0] * delta.x - jac[1] * delta.y - jac[2] * delta.z;
                float square = dot(delta, delta);
                if (square > 1e-20) {
                    for (int k = 0; k < 3; ++k) jac[k] += change * (delta[k] / square);
                }
                x = next;
                r = nr;
                score = next_score;
                improved = true;
                break;
            }
        }
        refresh = !improved;
        damping = improved ? max(1e-8, damping * 0.2) : min(1e3, damping * 10.0);
    }
    return x * scale;
}

float stack_reproduction_error(vec4 actual, vec4 target, bool appearance) {
    if (!stack_finite(actual)) return uintBitsToFloat(0x7f800000u);
    if (appearance) {
        vec4 wanted = stack_features(target);
        return stack_max_abs((stack_features(actual) - wanted) / (1.0 + abs(wanted))) / 1e-4;
    }
    vec3 rgb = stack_decode(actual);
    if (!stack_finite(vec4(rgb, 0.0))) return uintBitsToFloat(0x7f800000u);
    float peak = stack_max_abs(vec4(target.xyz, 0.0));
    return stack_max_abs(vec4(rgb - target.xyz, 0.0)) / max(3e-5, 1e-4 * peak);
}

void stack_choose_inverse(vec4 candidate, vec4 target, bool appearance,
                          inout vec4 best, inout float error) {
    if (!stack_finite(candidate) || !stack_finite(vec4(stack_decode_cones(candidate), 0.0))) return;
    float candidate_error = stack_reproduction_error(stack_grade(candidate), target, appearance);
    if (candidate_error < error) {
        best = candidate;
        error = candidate_error;
    }
}

vec4 stack_inverse(vec4 target, bool target_is_appearance, out float residual) {
    residual = uintBitsToFloat(0x7f800000u);
    if (!stack_finite(target)) return vec4(residual);
    vec4 wanted = target_is_appearance ? target : stack_target(target.xyz);
    if (!stack_finite(wanted)) return vec4(residual);
    vec4 best = vec4(0.0);
    vec3 post_tone = vec3(stack_ja(wanted), wanted.yz);
    stack_choose_inverse(stack_state(stack_undo_tone(post_tone)), target, target_is_appearance, best, residual);
    if (residual > 0.02) {
        vec4 features = stack_features(wanted);
        vec4 weights = 1.0 / (1.0 + abs(features));
        vec3 fitted = stack_inverse_fit(post_tone, features, weights);
        stack_choose_inverse(stack_state(stack_undo_tone(fitted)), target, target_is_appearance, best, residual);
    }
    if (residual > 1.0) {
        stack_choose_inverse(stack_state(post_tone), target, target_is_appearance, best, residual);
        stack_choose_inverse(vec4(0.0), target, target_is_appearance, best, residual);
    }
    return best;
}
"""

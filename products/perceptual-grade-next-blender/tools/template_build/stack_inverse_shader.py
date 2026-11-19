"""Bounded inverse search over signed pre-Tone appearance coordinates."""


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

vec3 stack_inverse_tone_seed(vec4 target) {
    float ja = stack_ja(target);
    vec2 ab = target.yz;
    float chroma_term = 66.0 * length(ab);
    float desired = sqrt(ja * ja + chroma_term);
    if (desired == 0.0) return vec3(0.0);
    // Recover the source magnitude before solving the coupled Color stages.
    // The bound covers the fully saturated CAT16 response cube.
    float low = 0.0;
    float high = stack_max_magnitude;
    for (int i = 0; i < 25; ++i) {
        float middle = 0.5 * (low + high);
        if (stack_tone_magnitude(middle) < desired) low = middle;
        else high = middle;
    }
    float source = 0.5 * (low + high);
    float gain = safe_divide(2.0 * source * source,
        length(vec2(chroma_term, 2.0 * ja * source)) + chroma_term);
    return gain * vec3(ja, ab);
}

vec4 stack_features(vec4 state) {
    return vec4(state.x, stack_ja(state), state.yz);
}

vec4 stack_inverse_residual(vec3 variables, vec3 scale, vec4 target, vec4 weights) {
    vec4 actual = stack_grade(stack_state(variables * scale));
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
    // Bound the trial coordinates independently of requested settings.
    // The forward evaluator can still carry signed energy and opponents.
    vec3 bound = stack_inverse_bound / scale;
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
    vec3 seed = vec3(stack_ja(wanted), wanted.yz);
    for (int attempt = 0; attempt < 4; ++attempt) {
        if (attempt == 1) seed = stack_inverse_tone_seed(wanted);
        else if (attempt == 2) {
            vec4 features = stack_features(wanted);
            vec4 weights = 1.0 / (1.0 + abs(features));
            seed = stack_inverse_fit(seed, features, weights);
        } else if (attempt == 3) {
            if (residual <= 1.0) break;
            seed = vec3(0.0);
        }
        stack_choose_inverse(stack_state(seed), target, target_is_appearance, best, residual);
        if (residual <= 0.02) break;
    }
    return best;
}
"""

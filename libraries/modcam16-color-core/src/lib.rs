//! Small browser-facing modCAM16-HK renderer.
//!
//! The public functions deliberately use flat arrays so they are cheap to
//! call from JavaScript workers.  The scene/display conversions here cover
//! the fixed HDR Rec.2020-limited, HDR/SDR P3-D65, SDR Rec.709, and direct
//! sRGB profiles used by the Python tool.
//! The ACES output forward and inverse paths are the ACES 2.0 fixed functions
//! exported by the bundled OpenColorIO processor.  The appearance equations are the
//! modCAM16-HK equations used by ``modcam16_palette.cam16_hk`` with its
//! default ``AppearanceConfig``.

pub mod aces_output;
pub mod picker;

use wasm_bindgen::prelude::*;

const WIDTH: usize = 512;
const HEIGHT: usize = 512;
const HK_COEFFICIENT: f64 = 66.0;
const SURROUND_C: f64 = 0.525;
const SURROUND_N_C: f64 = 0.8;
// Refl is an ACEScg-neutral control. The extension above unity keeps the
// brightest absolute ColorChecker references addressable and accommodates
// the Rec.709 100-nit inverse-view bridge (neutral sRGB 0.5 maps to about
// 1.169 ACEScg).
const REFLECTANCE_MAX: f64 = 1.2;
const BACKGROUND_MAX: f64 = 1.0;

const CAT16: [[f64; 3]; 3] = [
    [0.401288, 0.650173, -0.051461],
    [-0.250268, 1.204414, 0.045854],
    [-0.002079, 0.048952, 0.953127],
];

const CAT16_INVERSE: [[f64; 3]; 3] = [
    [1.862067855087233, -1.011254630531684, 0.149186775444452],
    [0.387526543236137, 0.621447441931475, -0.008973985167613],
    [-0.015841498849334, -0.034122938028516, 1.04996443687785],
];

const OPPONENT_TO_COMPRESSED: [[f64; 3]; 3] = [
    [460.0, 451.0, 288.0],
    [460.0, -891.0, -261.0],
    [460.0, -220.0, -6300.0],
];

const P3_TO_XYZ: [[f64; 3]; 3] = [
    [0.4865709486482161, 0.2656676931690931, 0.1982172852343625],
    [0.2289745640697488, 0.6917385218365063, 0.0792869140937450],
    [-0.00000000000000004, 0.0451133818589026, 1.043944368900976],
];

const REC709_TO_XYZ: [[f64; 3]; 3] = [
    [0.4123907992659595, 0.3575843393838780, 0.1804807884018343],
    [0.2126390058715104, 0.7151686787677560, 0.0721923153607337],
    [0.0193308187155919, 0.1191947797946259, 0.9505321522496607],
];

const REC2020_TO_XYZ: [[f64; 3]; 3] = [
    [0.636958048301291, 0.144616903586208, 0.168880975164172],
    [0.262700212011267, 0.677998071518871, 0.059301716469862],
    [0.0, 0.0280726930490874, 1.06098505771079],
];

const XYZ_TO_P3: [[f64; 3]; 3] = [
    [2.493496911941425, -0.931383617919124, -0.402710784450717],
    [-0.829488969561575, 1.762664060318347, 0.023624685841944],
    [0.035845830243784, -0.076172389268042, 0.956884524007687],
];

const XYZ_TO_REC709: [[f64; 3]; 3] = [
    [3.2409699419045226, -1.5373831775700935, -0.4986107602930034],
    [-0.9692436362808798, 1.8759675015077202, 0.0415550574071756],
    [0.0556300796969937, -0.2039769588889765, 1.0569715142428786],
];

const XYZ_TO_REC2020: [[f64; 3]; 3] = [
    [1.7166511879712680, -0.3556707837763925, -0.2533662813736599],
    [-0.6666843518324890, 1.6164812366349388, 0.0157685458139111],
    [0.0176398574453108, -0.0427706132578085, 0.9421031212354739],
];

// Linear ACEScg/AP1 (ACES white) from the D65 XYZ reference used by
// display-referred image adapters. This project-owned D65→ACES-white
// adaptation is CAT02; canonical ACES output-transform matrices remain in
// `aces_output.rs`.
const XYZ_D65_TO_ACESCG: [[f64; 3]; 3] = [
    [1.658854308471042, -0.311856975397419, -0.243156007125715],
    [-0.662283287107587, 1.612199570871322, 0.015859126603063],
    [0.011480566457477, -0.009236324924244, 0.916686513449130],
];

// Direct CIELAB-D50/XYZ-D50 to ACEScg/AP1 conversion. The matrix combines
// CAT02 adaptation from the CIE D50 white to the ACES white
// (x=.32168, y=.33767) with the ACEScg primary matrix. ColorChecker targets
// use this direct path; they do not pass through the display D65 boundary.
const XYZ_D50_TO_ACESCG: [[f64; 3]; 3] = [
    [1.598623729846882, -0.361202746046775, -0.218385830505367],
    [-0.669874208830724, 1.629840132527303, 0.019462969460427],
    [0.012473064126380, -0.005493376059907, 1.203927293516246],
];

// Linear ACEScg/AP1 (ACES white) to D65 XYZ. This is the inverse of
// `XYZ_D65_TO_ACESCG` and is used by the direct sRGB profile, where the
// ACES 2.0 output transform is intentionally bypassed.
const ACESCG_TO_XYZ_D65: [[f64; 3]; 3] = [
    [0.652418717671913, 0.127179925537538, 0.170857283842221],
    [0.268064059194271, 0.672464478992618, 0.059471461813111],
    [-0.005469928510498, 0.005182799976975, 1.089344879293401],
];

// All 24 patches from the official post-November-2014 X-Rite ColorChecker24
// Lab/D50 reference file, in its native A1..A4, B1..B4, ... F1..F4 order.
// The downloaded source and provenance metadata are checked in under
// references/colorchecker/.
const COLORCHECKER24_LAB_D50: [[f64; 3]; 24] = [
    [37.54, 14.37, 14.92],
    [62.73, 35.83, 56.50],
    [28.37, 15.42, -49.80],
    [95.19, -1.03, 2.93],
    [64.66, 19.27, 17.50],
    [39.43, 10.75, -45.17],
    [54.38, -39.72, 32.27],
    [81.29, -0.57, 0.44],
    [49.32, -3.82, -22.54],
    [50.57, 48.64, 16.67],
    [42.43, 51.05, 28.62],
    [66.89, -0.75, -0.06],
    [43.46, -12.74, 22.72],
    [30.10, 22.54, -20.87],
    [81.80, 2.67, 80.41],
    [50.76, -0.13, 0.14],
    [54.94, 9.61, -24.79],
    [71.77, -24.13, 58.19],
    [50.63, 51.28, -14.12],
    [35.63, -0.46, -0.48],
    [70.48, -32.26, -0.37],
    [71.51, 18.24, 67.37],
    [49.57, -29.71, -28.32],
    [20.64, 0.07, -0.46],
];

// Preserve the picker's established row-major chromatic-patch order while
// retaining the neutral column in the authoritative source table.
const COLORCHECKER_ACTIVE_INDICES: [usize; 18] = [
    0, 4, 8, 12, 16, 20, 1, 5, 9, 13, 17, 21, 2, 6, 10, 14, 18, 22,
];

const fn active_colorchecker_lab_d50() -> [[f64; 3]; 18] {
    let mut active = [[0.0; 3]; 18];
    let mut index = 0;
    while index < COLORCHECKER_ACTIVE_INDICES.len() {
        active[index] = COLORCHECKER24_LAB_D50[COLORCHECKER_ACTIVE_INDICES[index]];
        index += 1;
    }
    active
}

const COLORCHECKER_LAB_D50: [[f64; 3]; 18] = active_colorchecker_lab_d50();

const CAT02: [[f64; 3]; 3] = [
    [0.7328, 0.4296, -0.1624],
    [-0.7036, 1.6975, 0.0061],
    [0.0030, 0.0136, 0.9834],
];

const CAT02_INVERSE: [[f64; 3]; 3] = [
    [1.096123820835514, -0.278869000182015, 0.182745179382773],
    [0.454369041975359, 0.473533154307412, 0.072097803717229],
    [-0.009627608738429, -0.005698031216113, 1.015325639954543],
];

const D65_XY: [f64; 2] = [0.3127, 0.3290];

#[derive(Clone, Copy)]
struct Model {
    adaptation: [f64; 3],
    cam_a_w: f64,
    cam_f_l: f64,
    cam_z: f64,
}

#[derive(Clone, Copy)]
struct Sample {
    xyz: [f64; 3],
    source_rgb: [f64; 3],
    acescg: [f64; 3],
    valid: bool,
}

fn source_to_xyz(profile: u32, rgb: [f64; 3]) -> [f64; 3] {
    mat(
        if profile == 1 || profile == 3 {
            &REC709_TO_XYZ
        } else {
            &P3_TO_XYZ
        },
        rgb,
    )
}

fn xyz_to_source(profile: u32, xyz: [f64; 3]) -> [f64; 3] {
    mat(
        if profile == 1 || profile == 3 {
            &XYZ_TO_REC709
        } else {
            &XYZ_TO_P3
        },
        xyz,
    )
}

fn source_cone_valid(profile: u32, source_rgb: [f64; 3], xyz: [f64; 3]) -> bool {
    if min3(source_rgb) < -1.0e-6 {
        return false;
    }
    if profile == 3 {
        return max3(source_rgb) <= 1.0 + 1.0e-6;
    }
    // The Rec.2020-limited profile uses a P3 source constrained by the
    // selected ACES 2.0 Rec.2100 output path's narrower red boundary.
    profile != 0 || min3(mat(&XYZ_TO_REC2020, xyz)) >= -1.0e-6
}

// The normalized Cartesian picker models a target-gamut cone. Positive linear channels are therefore
// valid above 1.0; only negative channels (and the profile-0 P3-D65 limit)
// make a normalized sample unavailable.
fn normalized_cone_valid(profile: u32, source_rgb: [f64; 3], xyz: [f64; 3]) -> bool {
    finite3(source_rgb)
        && min3(source_rgb) >= -1.0e-8
        && (profile != 0 || min3(mat(&XYZ_TO_REC2020, xyz)) >= -1.0e-8)
}

fn mat(matrix: &[[f64; 3]; 3], value: [f64; 3]) -> [f64; 3] {
    [
        matrix[0][0] * value[0] + matrix[0][1] * value[1] + matrix[0][2] * value[2],
        matrix[1][0] * value[0] + matrix[1][1] * value[1] + matrix[1][2] * value[2],
        matrix[2][0] * value[0] + matrix[2][1] * value[1] + matrix[2][2] * value[2],
    ]
}

fn cct_uv(temp: f64) -> [f64; 2] {
    // Hernandez-Andres daylight/Planckian approximation, adequate over the
    // UI range. The published approximation uses a piecewise polynomial for
    // y(x); using the low-temperature branch everywhere produces a large
    // jump away from the exact D65 anchor near 6500 K.
    let t = if temp.is_finite() {
        temp.clamp(2000.0, 20000.0)
    } else {
        6500.0
    };
    let x = if t <= 4000.0 {
        -0.2661239e9 / t.powi(3) - 0.2343580e6 / t.powi(2) + 0.8776956e3 / t + 0.179910
    } else {
        -3.0258469e9 / t.powi(3) + 2.1070379e6 / t.powi(2) + 0.2226347e3 / t + 0.240390
    };
    let y = if t <= 2222.0 {
        -1.1063814 * x.powi(3) - 1.34811020 * x.powi(2) + 2.18555832 * x - 0.20219683
    } else if t <= 4000.0 {
        -0.9549476 * x.powi(3) - 1.37418593 * x.powi(2) + 2.09137015 * x - 0.16748867
    } else {
        3.0817580 * x.powi(3) - 5.87338670 * x.powi(2) + 3.75112997 * x - 0.37001483
    };
    let denom = -2.0 * x + 12.0 * y + 3.0;
    let mut u = if denom.abs() > 1.0e-9 {
        4.0 * x / denom
    } else {
        0.1978
    };
    let mut v = if denom.abs() > 1.0e-9 {
        6.0 * y / denom
    } else {
        0.3123
    };
    // The standard locus is a black-body/daylight approximation and does not
    // pass exactly through the profile white used by the appearance model.
    // Translate the locus in CIE 1960 uv so 6500 K is D65 while preserving its
    // local temperature behavior. This avoids a visible one-step jump at the
    // default control value.
    let anchor_t: f64 = 6500.0;
    let anchor_x = -3.0258469e9 / anchor_t.powi(3)
        + 2.1070379e6 / anchor_t.powi(2)
        + 0.2226347e3 / anchor_t
        + 0.240390;
    let anchor_y = 3.0817580 * anchor_x.powi(3) - 5.87338670 * anchor_x.powi(2)
        + 3.75112997 * anchor_x
        - 0.37001483;
    let anchor_denom = -2.0 * anchor_x + 12.0 * anchor_y + 3.0;
    let anchor_u = 4.0 * anchor_x / anchor_denom;
    let anchor_v = 6.0 * anchor_y / anchor_denom;
    let d65_denom = -2.0 * D65_XY[0] + 12.0 * D65_XY[1] + 3.0;
    let d65_u = 4.0 * D65_XY[0] / d65_denom;
    let d65_v = 6.0 * D65_XY[1] / d65_denom;
    u += d65_u - anchor_u;
    v += d65_v - anchor_v;
    [u, v]
}

fn white_xyz_from_cct(temp: f64, tint: f64) -> [f64; 3] {
    let temp = if temp.is_finite() {
        temp.clamp(2000.0, 20000.0)
    } else {
        6500.0
    };
    let tint = if tint.is_finite() {
        tint.clamp(-100.0, 100.0)
    } else {
        0.0
    };
    if (temp - 6500.0).abs() < 1.0e-12 && tint.abs() < 1.0e-12 {
        let x = D65_XY[0];
        return [x / D65_XY[1], 1.0, (1.0 - x - D65_XY[1]) / D65_XY[1]];
    }
    let mut uv = cct_uv(temp);
    // Tint is the signed displacement perpendicular to the CCT locus in CIE
    // 1960 uv.  The normal is oriented toward spectral magenta (positive u,
    // negative v) so the conventional UI scale is negative = green and
    // positive = magenta; shifting v alone would incorrectly describe a
    // blue/yellow change.
    if tint.abs() > 0.0 {
        let lower = (temp - 1.0).max(2000.0);
        let upper = (temp + 1.0).min(20000.0);
        let lower_uv = cct_uv(lower);
        let upper_uv = cct_uv(upper);
        let span = (upper - lower).max(1.0e-9);
        let tangent_u = (upper_uv[0] - lower_uv[0]) / span;
        let tangent_v = (upper_uv[1] - lower_uv[1]) / span;
        let tangent_length = tangent_u.hypot(tangent_v);
        let (magenta_u, magenta_v) = if tangent_length > 1.0e-12 {
            (-tangent_v / tangent_length, tangent_u / tangent_length)
        } else {
            (0.8, -0.6)
        };
        let distance = tint / 100.0 * 0.05;
        uv[0] += distance * magenta_u;
        uv[1] += distance * magenta_v;
    }
    // CIE 1960 uv inverse (v uses the 6y numerator, unlike CIE 1976 v').
    let uv_denom = 2.0 * uv[0] - 8.0 * uv[1] + 4.0;
    let (mut out_x, mut out_y) = if uv_denom.abs() > 1.0e-9 {
        (3.0 * uv[0] / uv_denom, 2.0 * uv[1] / uv_denom)
    } else {
        (D65_XY[0], D65_XY[1])
    };
    if !out_x.is_finite() || !out_y.is_finite() || out_y <= 1.0e-6 {
        out_x = D65_XY[0];
        out_y = D65_XY[1];
    }
    [out_x / out_y, 1.0, (1.0 - out_x - out_y) / out_y]
}

fn cat02_matrix(temp: f64, tint: f64) -> ([[f64; 3]; 3], [[f64; 3]; 3]) {
    let source = white_xyz_from_cct(6500.0, 0.0);
    let target = white_xyz_from_cct(temp, tint);
    let source_cone = mat(&CAT02, source);
    let target_cone = mat(&CAT02, target);
    let scale = [
        if source_cone[0].abs() > 1.0e-9 {
            target_cone[0] / source_cone[0]
        } else {
            1.0
        },
        if source_cone[1].abs() > 1.0e-9 {
            target_cone[1] / source_cone[1]
        } else {
            1.0
        },
        if source_cone[2].abs() > 1.0e-9 {
            target_cone[2] / source_cone[2]
        } else {
            1.0
        },
    ];
    let mut forward = [[0.0; 3]; 3];
    for row in 0..3 {
        for col in 0..3 {
            forward[row][col] = CAT02_INVERSE[row][0] * scale[0] * CAT02[0][col]
                + CAT02_INVERSE[row][1] * scale[1] * CAT02[1][col]
                + CAT02_INVERSE[row][2] * scale[2] * CAT02[2][col];
        }
    }
    let inverse_scale = [
        if scale[0].abs() > 1.0e-9 {
            1.0 / scale[0]
        } else {
            1.0
        },
        if scale[1].abs() > 1.0e-9 {
            1.0 / scale[1]
        } else {
            1.0
        },
        if scale[2].abs() > 1.0e-9 {
            1.0 / scale[2]
        } else {
            1.0
        },
    ];
    let mut inverse = [[0.0; 3]; 3];
    for row in 0..3 {
        for col in 0..3 {
            inverse[row][col] = CAT02_INVERSE[row][0] * inverse_scale[0] * CAT02[0][col]
                + CAT02_INVERSE[row][1] * inverse_scale[1] * CAT02[1][col]
                + CAT02_INVERSE[row][2] * inverse_scale[2] * CAT02[2][col];
        }
    }
    (forward, inverse)
}

fn adapt_xyz_preserve_j_hk(model: Model, xyz: [f64; 3], temp: f64, tint: f64) -> [f64; 3] {
    if !finite3(xyz) || ((temp - 6500.0).abs() < 1.0e-12 && tint.abs() < 1.0e-12) {
        return xyz;
    }
    let (matrix, _) = cat02_matrix(temp, tint);
    let adapted = mat(&matrix, xyz);
    let target = attributes(model, xyz).3;
    if !target.is_finite() || !finite3(adapted) {
        return adapted;
    }
    let scale = solve_j_hk_scale(model, adapted, target);
    [adapted[0] * scale, adapted[1] * scale, adapted[2] * scale]
}

fn unadapt_xyz(model: Model, xyz: [f64; 3], temp: f64, tint: f64) -> [f64; 3] {
    if !finite3(xyz) || ((temp - 6500.0).abs() < 1.0e-12 && tint.abs() < 1.0e-12) {
        return xyz;
    }
    let (_, inverse) = cat02_matrix(temp, tint);
    // Recover the pre-adaptation scale from the visible J_HK. This is the
    // inverse of the display-side normalization used above.
    let base = mat(&inverse, xyz);
    if !finite3(base) {
        return base;
    }
    let target = attributes(model, xyz).3;
    if !target.is_finite() {
        return base;
    }
    let scale = solve_j_hk_scale(model, base, target);
    [base[0] * scale, base[1] * scale, base[2] * scale]
}

/// Solve the positive scale that restores a color's J_HK after a linear
/// chromatic-adaptation matrix.  J_HK is monotone with exposure for the
/// non-negative colors used by the picker, but the required factor can be
/// arbitrarily close to zero for dark colors and can exceed four for extreme
/// white points.  Bracket adaptively instead of relying on a fixed [0.01, 4]
/// interval; otherwise inverse entry and low-reflectance samples silently lose
/// their original hue/saturation.
fn solve_j_hk_scale(model: Model, base: [f64; 3], target: f64) -> f64 {
    // Very dark samples can be attenuated by several orders of magnitude by
    // a strong white-point shift before their J_HK is restored. Keep a broad
    // but finite ceiling so those samples do not silently collapse to black.
    const MAX_SCALE: f64 = 1.0e6;
    if !target.is_finite() || !finite3(base) {
        return 1.0;
    }

    let at_zero = attributes(model, [0.0; 3]).3;
    if !at_zero.is_finite() || target <= at_zero {
        return 0.0;
    }

    // Find an upper endpoint whose J_HK reaches the target. Starting at one
    // preserves the usual case while the doubling handles both very dark
    // adapted colors (scale < 0.01) and strong white-point shifts (scale > 4).
    let mut low = 0.0;
    let mut high = 1.0;
    let mut high_j = attributes(model, base).3;
    while high_j.is_finite() && high_j < target && high < MAX_SCALE {
        low = high;
        high = (high * 2.0).min(MAX_SCALE);
        high_j = attributes(model, [base[0] * high, base[1] * high, base[2] * high]).3;
    }

    // If the target is beyond the representable scale range (or the model
    // becomes non-finite at the upper endpoint), use the largest safe factor.
    // Callers still perform their ordinary finite/gamut validation.
    if !high_j.is_finite() || high_j < target {
        return high.clamp(0.0, MAX_SCALE);
    }

    for _ in 0..60 {
        let mid = 0.5 * (low + high);
        let j = attributes(model, [base[0] * mid, base[1] * mid, base[2] * mid]).3;
        if j.is_finite() && j < target {
            low = mid;
        } else {
            high = mid;
        }
    }
    (0.5 * (low + high)).clamp(0.0, MAX_SCALE)
}

fn finite3(value: [f64; 3]) -> bool {
    value.iter().all(|component| component.is_finite())
}

fn min3(value: [f64; 3]) -> f64 {
    value[0].min(value[1]).min(value[2])
}

fn max3(value: [f64; 3]) -> f64 {
    value[0].max(value[1]).max(value[2])
}

fn unit_cube_valid(value: [f64; 3]) -> bool {
    finite3(value) && min3(value) >= -1.0e-6 && max3(value) <= 1.0 + 1.0e-6
}

// Normalized modCAM16-HK channel API. These constants are shared with the
// modCAM16-HK view shader and intentionally live beside the f64 reference
// implementation so browser controls and shader-authored Rec.2020 values agree.
const J_HK_PEAK: f64 = 183.7488220212894;
// Calculated to contain the Rec.2020 pure-blue endpoint
// s_max=203.64174424420062 while retaining smooth logarithmic interpolation.
const FITTED_RADIUS_K: f64 = 5.977038579617132;
const FITTED_RADIUS_D: f64 = 3.557365336640551;

fn normalized_j_scale(_profile: u32) -> f64 {
    J_HK_PEAK
}

fn normalized_xyz_scale(profile: u32) -> f64 {
    let _ = profile;
    1.0
}

fn normalized_model(_profile: u32) -> Model {
    let mut model = model();
    // Use the common D65/203-nit context for every
    // normalized profile.
    model.cam_f_l = 0.46646834500532247;
    model.cam_a_w = 31.7941491565276;
    model.cam_z = 1.48 + 0.10_f64.sqrt();
    model
}

fn decode_normalized_jhk(profile: u32, code: [f64; 3]) -> Option<(f64, f64, f64)> {
    decode_scaled_jhk(code, normalized_j_scale(profile))
}

fn decode_scaled_jhk(code: [f64; 3], j_scale: f64) -> Option<(f64, f64, f64)> {
    if !finite3(code)
        || code[0] < 0.0
        || code[0] > 1.0
        || code[1] < 0.0
        || code[1] > 1.0
        || code[2] < 0.0
        || code[2] > 1.0
    {
        return None;
    }
    let x = 2.0 * code[1] - 1.0;
    let y = 2.0 * code[2] - 1.0;
    let radius = x.hypot(y);
    if !radius.is_finite() || radius > 1.0 + 1.0e-12 {
        return None;
    }
    let saturation = FITTED_RADIUS_K * FITTED_RADIUS_D.mul_add(radius, 0.0).exp_m1();
    let h = code[0] * j_scale;
    let u = (0.007 / SURROUND_C) * saturation;
    let denominator = h.hypot(33.0 * u) + 33.0 * u;
    let j_a = if denominator > 0.0 {
        h * h / denominator
    } else {
        0.0
    };
    let chroma = u * j_a;
    if !h.is_finite()
        || !saturation.is_finite()
        || !j_a.is_finite()
        || !chroma.is_finite()
        || chroma < 0.0
        || HK_COEFFICIENT * chroma > h * h + 1.0e-10
    {
        return None;
    }
    // Normalized channels use `(x, y) = (-R(s) sin(h), R(s) cos(h))`.
    let hue = (-x).atan2(y).to_degrees().rem_euclid(360.0);
    Some((h, chroma, hue))
}

fn normalized_jhk_from_xyz(profile: u32, xyz: [f64; 3]) -> ([f64; 3], bool) {
    let model_xyz = xyz.map(|channel| channel / normalized_xyz_scale(profile));
    scaled_jhk_from_xyz(model_xyz, normalized_j_scale(profile))
}

fn scaled_jhk_from_xyz(model_xyz: [f64; 3], scale: f64) -> ([f64; 3], bool) {
    scaled_jhk_from_xyz_with_tolerance(model_xyz, scale, 1.0e-10)
}

fn scaled_jhk_from_xyz_with_tolerance(
    model_xyz: [f64; 3],
    scale: f64,
    tolerance: f64,
) -> ([f64; 3], bool) {
    let (_, chroma, hue, j_hk) = attributes(normalized_model(2), model_xyz);
    let j_a = (j_hk * j_hk - HK_COEFFICIENT * chroma).max(0.0).sqrt();
    let raw_saturation = if j_a > 0.0 && chroma.is_finite() {
        (SURROUND_C * chroma / (0.007 * j_a)).max(0.0)
    } else {
        0.0
    };
    let raw_j = j_hk / scale;
    let raw_radius = if raw_saturation.is_finite() {
        (1.0 + raw_saturation / FITTED_RADIUS_K).ln() / FITTED_RADIUS_D
    } else {
        f64::NAN
    };
    let radius = raw_radius.clamp(0.0, 1.0);
    let radians = hue.to_radians();
    let code = [
        raw_j.clamp(0.0, 1.0),
        0.5 - 0.5 * radius * radians.sin(),
        0.5 + 0.5 * radius * radians.cos(),
    ];
    let valid = raw_j.is_finite()
        && raw_j >= -tolerance
        && raw_j <= 1.0 + tolerance
        && raw_saturation.is_finite()
        && raw_saturation >= 0.0
        && chroma.is_finite()
        && chroma >= -1.0e-10
        && raw_radius.is_finite()
        && raw_radius <= 1.0 + tolerance;
    (code, valid)
}

fn normalized_sample(profile: u32, code: [f64; 3]) -> Sample {
    let Some((j_hk, chroma, hue)) = decode_normalized_jhk(profile, code) else {
        return Sample {
            xyz: [f64::NAN; 3],
            source_rgb: [f64::NAN; 3],
            acescg: [f64::NAN; 3],
            valid: false,
        };
    };
    let model = normalized_model(profile);
    let mut xyz = modcam_to_xyz(model, j_hk, chroma, hue);
    let xyz_scale = normalized_xyz_scale(profile);
    xyz = xyz.map(|channel| channel * xyz_scale);
    let acescg = transform_to_acescg(profile, xyz);
    let source_rgb = xyz_to_source(profile, xyz);
    let source_valid = normalized_cone_valid(profile, source_rgb, xyz);
    Sample {
        xyz,
        source_rgb,
        acescg,
        valid: finite3(xyz) && finite3(acescg) && source_valid,
    }
}

fn encode_extended_rgb(value: [f64; 3]) -> [f64; 3] {
    value.map(|channel| {
        if !channel.is_finite() {
            return f64::NAN;
        }
        let sign = channel.signum();
        let magnitude = channel.abs();
        sign * if magnitude <= 0.0031308 {
            12.92 * magnitude
        } else {
            1.055 * magnitude.powf(1.0 / 2.4) - 0.055
        }
    })
}

fn normalized_coordinates_from_xyz(profile: u32, xyz: [f64; 3]) -> Vec<f64> {
    let (code, domain_valid) = normalized_jhk_from_xyz(profile, xyz);
    let source = xyz_to_source(profile, xyz);
    let attrs = attributes(
        normalized_model(profile),
        xyz.map(|channel| channel / normalized_xyz_scale(profile)),
    );
    let valid = finite3(xyz)
        && normalized_cone_valid(profile, source, xyz)
        && code.iter().all(|v| v.is_finite())
        && attrs.3.is_finite()
        && domain_valid;
    vec![if valid { 1.0 } else { 0.0 }, code[0], code[1], code[2]]
}

/// Evaluate normalized `(J_HK, fitted-radius-x, fitted-radius-y)` controls.
/// Layout: `[valid, linear0..2, displayP3 RGB, display-sRGB RGB,
/// encoded-linear RGB, backgroundDisplayP3 RGB, backgroundDisplaySrgb RGB,
/// backgroundNeutral, j, x, y]`.
#[wasm_bindgen]
pub fn evaluate_normalized(
    profile: u32,
    j: f64,
    fitted_radius_x: f64,
    fitted_radius_y: f64,
    background: f64,
) -> Vec<f64> {
    let code = [j, fitted_radius_x, fitted_radius_y];
    let result = normalized_sample(profile, code);
    let background_value = if background.is_finite() {
        background.clamp(0.0, BACKGROUND_MAX)
    } else {
        0.0
    };
    let background_xyz = source_to_xyz(profile, [background_value; 3]);
    let background_p3 = display_xyz_f64(background_xyz, &XYZ_TO_P3);
    let background_srgb = display_xyz_f64(background_xyz, &XYZ_TO_REC709);
    let linear = if profile == 3 {
        result.source_rgb
    } else {
        result.acescg
    };
    let encoded = encode_extended_rgb(linear);
    let display_p3 = display_xyz_f64(result.xyz, &XYZ_TO_P3);
    let display_srgb = display_xyz_f64(result.xyz, &XYZ_TO_REC709);
    let neutral_j = j * normalized_j_scale(profile);
    let (background_neutral, _) =
        solve_output_neutral_for_j_hk(normalized_model(profile), profile, neutral_j);
    let mut out = vec![
        if result.valid { 1.0 } else { 0.0 },
        linear[0],
        linear[1],
        linear[2],
        display_p3[0],
        display_p3[1],
        display_p3[2],
        display_srgb[0],
        display_srgb[1],
        display_srgb[2],
        encoded[0],
        encoded[1],
        encoded[2],
        background_p3[0],
        background_p3[1],
        background_p3[2],
        background_srgb[0],
        background_srgb[1],
        background_srgb[2],
        background_neutral,
        j,
        fitted_radius_x,
        fitted_radius_y,
    ];
    if !result.valid {
        out[0] = 0.0;
    }
    out
}

#[wasm_bindgen]
pub fn normalized_coordinates_from_encoded(
    profile: u32,
    red: f64,
    green: f64,
    blue: f64,
) -> Vec<f64> {
    let encoded = [red, green, blue];
    let linear = encoded.map(decode_srgb);
    let xyz = if profile == 3 {
        source_to_xyz(3, linear)
    } else {
        mat(&ACESCG_TO_XYZ_D65, linear)
    };
    let mut coordinates = normalized_coordinates_from_xyz(profile, xyz);
    coordinates.extend_from_slice(&linear);
    coordinates
}

#[wasm_bindgen]
pub fn normalized_coordinates_from_acescg(
    profile: u32,
    red: f64,
    green: f64,
    blue: f64,
) -> Vec<f64> {
    let acescg = [decode_srgb(red), decode_srgb(green), decode_srgb(blue)];
    let xyz = if profile == 3 {
        mat(&ACESCG_TO_XYZ_D65, acescg)
    } else {
        transform_from_acescg(profile, acescg)
    };
    let mut coordinates = normalized_coordinates_from_xyz(profile, xyz);
    coordinates.extend_from_slice(&acescg);
    coordinates
}

/// Preserve the source workflow's actual linear value while changing profile.
/// ACES profiles carry ACEScg directly; profile 3 carries linear Rec.709 and
/// crosses the ACES 2.0 SDR Rec.709 view explicitly.
#[wasm_bindgen]
pub fn convert_normalized_profile(
    source_profile: u32,
    target_profile: u32,
    red: f64,
    green: f64,
    blue: f64,
) -> Vec<f64> {
    let retained = [red, green, blue];
    if !finite3(retained) {
        return vec![0.0, 0.0, 0.5, 0.5];
    }
    let (xyz, canonical) = if source_profile == 3 {
        if target_profile == 3 {
            (source_to_xyz(3, retained), retained)
        } else {
            let acescg = aces_output::inverse_from_xyz_d65(1, source_to_xyz(3, retained));
            (transform_from_acescg(target_profile, acescg), acescg)
        }
    } else if target_profile == 3 {
        let xyz = transform_from_acescg(1, retained);
        (xyz, xyz_to_source(3, xyz))
    } else {
        (transform_from_acescg(target_profile, retained), retained)
    };
    let mut coordinates = normalized_coordinates_from_xyz(target_profile, xyz);
    coordinates.extend_from_slice(&canonical);
    coordinates
}

#[wasm_bindgen]
pub fn convert_normalized_background(
    source_profile: u32,
    target_profile: u32,
    background: f64,
    source_j: f64,
    target_j: f64,
) -> Vec<f64> {
    if !background.is_finite() || !source_j.is_finite() || !target_j.is_finite() {
        return vec![0.0, 0.0];
    }
    let source_model = normalized_model(source_profile);
    let target_model = normalized_model(target_profile);
    let source_foreground = source_j.clamp(0.0, 1.0) * normalized_j_scale(source_profile);
    let target_foreground = target_j.clamp(0.0, 1.0) * normalized_j_scale(target_profile);
    let source_background = output_neutral_j_hk(
        source_model,
        source_profile,
        background.clamp(0.0, BACKGROUND_MAX),
    );
    let target = target_foreground + source_background - source_foreground;
    let (value, exact) = solve_output_neutral_for_j_hk(target_model, target_profile, target);
    vec![if exact { 1.0 } else { 0.0 }, value]
}

/// Diagnostic bridge used by the OCIO oracle test. The browser UI does not
/// call this export; it exposes the Rust port's raw ACES 2.0 forward result so
/// a Python OpenColorIO processor can remain the independent reference.
#[wasm_bindgen]
pub fn reference_forward_xyz(profile: u32, red: f64, green: f64, blue: f64) -> Vec<f64> {
    let value = transform_from_acescg(profile, [red, green, blue]);
    value.to_vec()
}

/// Diagnostic bridge used by the OCIO oracle test. See
/// [`reference_forward_xyz`] for why this is intentionally not used by the UI.
#[wasm_bindgen]
pub fn reference_inverse_acescg(profile: u32, x: f64, y: f64, z: f64) -> Vec<f64> {
    let value = transform_to_acescg(profile, [x, y, z]);
    value.to_vec()
}

#[wasm_bindgen]
pub fn render_rows_normalized(
    profile: u32,
    j: f64,
    width: u32,
    height: u32,
    y_start: u32,
    y_end: u32,
    display_p3: bool,
) -> Vec<u8> {
    let width = width.max(1) as usize;
    let height = height.max(1) as usize;
    let start = (y_start as usize).min(height);
    let end = (y_end as usize).min(height).max(start);
    let mut output = vec![0_u8; (end - start) * width * 4];
    for y in start..end {
        for x in 0..width {
            let sx = if width <= 1 {
                0.5
            } else {
                x as f64 / (width - 1) as f64
            };
            let sy = if height <= 1 {
                0.5
            } else {
                1.0 - y as f64 / (height - 1) as f64
            };
            let sample = normalized_sample(profile, [j, sx, sy]);
            let index = ((y - start) * width + x) * 4;
            if sample.valid {
                let rgb = if display_p3 {
                    display_rgb(sample.xyz, &XYZ_TO_P3)
                } else {
                    display_rgb(sample.xyz, &XYZ_TO_REC709)
                };
                output[index..index + 4].copy_from_slice(&[rgb[0], rgb[1], rgb[2], 255]);
            } else {
                let shade = if ((x / 7) + (y / 7)) % 2 == 0 { 22 } else { 15 };
                output[index..index + 4].copy_from_slice(&[shade, shade + 2, shade + 5, 255]);
            }
        }
    }
    output
}

/// Normalized ColorChecker records: `[j, x, y, displayP3 RGB, displaySrgb RGB,
/// available]` per patch.
#[wasm_bindgen]
pub fn colorchecker_points_normalized(profile: u32) -> Vec<f64> {
    let mut output = Vec::with_capacity(COLORCHECKER_LAB_D50.len() * 9);
    for lab in COLORCHECKER_LAB_D50 {
        let acescg = colorchecker_scene_target(lab);
        let profile_xyz = if profile == 3 {
            mat(&ACESCG_TO_XYZ_D65, acescg)
        } else {
            transform_from_acescg(profile, acescg)
        };
        let (code, domain_valid) = normalized_jhk_from_xyz(profile, profile_xyz);
        let p3 = display_xyz_f64(profile_xyz, &XYZ_TO_P3);
        let srgb = display_xyz_f64(profile_xyz, &XYZ_TO_REC709);
        let source = xyz_to_source(profile, profile_xyz);
        let available = normalized_cone_valid(profile, source, profile_xyz)
            && code.iter().all(|v| v.is_finite())
            && domain_valid;
        output.extend_from_slice(&[
            code[0],
            code[1],
            code[2],
            p3[0],
            p3[1],
            p3[2],
            srgb[0],
            srgb[1],
            srgb[2],
            if available { 1.0 } else { 0.0 },
        ]);
    }
    output
}

fn adapted_display_valid(profile: u32, xyz: [f64; 3], tolerance: f64) -> bool {
    let source_rgb = xyz_to_source(profile, xyz);
    let acescg = transform_to_acescg(profile, xyz);
    finite3(xyz)
        && finite3(source_rgb)
        // Adapted values use the same small boundary tolerance for the
        // continuous picker and pixel sampler so round-off cannot make a dot
        // unavailable while the underlying pixel is accepted.
        && min3(source_rgb) >= -tolerance
        && (profile != 3 || max3(source_rgb) <= 1.0 + tolerance)
        && (profile != 0 || min3(mat(&XYZ_TO_REC2020, xyz)) >= -tolerance)
        && if profile == 3 {
            true
        } else {
            finite3(acescg)
                && min3(acescg) >= -tolerance
                && max3(acescg) <= 1.0 + tolerance
        }
}

fn adaptation_is_identity(temp: f64, tint: f64) -> bool {
    (temp - 6500.0).abs() < 1.0e-12 && tint.abs() < 1.0e-12
}

fn clamp_unit(value: f64) -> f64 {
    if value.is_finite() {
        value.clamp(0.0, 1.0)
    } else {
        0.0
    }
}

fn signed_power(value: f64, exponent: f64) -> f64 {
    value.signum() * value.abs().powf(exponent)
}

fn response(value: f64, f_l: f64) -> f64 {
    let lower = 0.26;
    let upper = 150.0;
    let response_at_lower = hyperbolic_response(lower, f_l);
    let response_at_upper = hyperbolic_response(upper, f_l);
    let upper_slope = hyperbolic_derivative(upper, f_l);
    if value < lower {
        response_at_lower * value / lower + 0.1
    } else if value > upper {
        response_at_upper + upper_slope * (value - upper) + 0.1
    } else {
        hyperbolic_response(value, f_l) + 0.1
    }
}

fn inverse_response(value: f64, f_l: f64) -> f64 {
    let response_value = value - 0.1;
    let lower = 0.26;
    let upper = 150.0;
    let response_at_lower = hyperbolic_response(lower, f_l);
    let response_at_upper = hyperbolic_response(upper, f_l);
    let upper_slope = hyperbolic_derivative(upper, f_l);
    if response_value < response_at_lower {
        lower * response_value / response_at_lower
    } else if response_value > response_at_upper {
        upper + (response_value - response_at_upper) / upper_slope
    } else {
        let base = 27.13 * response_value / (400.0 - response_value);
        100.0 / f_l * base.powf(1.0 / 0.42)
    }
}

fn hyperbolic_response(value: f64, f_l: f64) -> f64 {
    let power = (f_l * value / 100.0).powf(0.42);
    400.0 * power / (27.13 + power)
}

fn hyperbolic_derivative(value: f64, f_l: f64) -> f64 {
    let normalized = f_l * value / 100.0;
    let power = normalized.powf(0.42);
    1.68 * 27.13 * f_l * normalized.powf(-0.58) / (27.13 + power).powi(2)
}

fn model() -> Model {
    let white = [
        0.3127 / 0.3290 * 100.0,
        100.0,
        (1.0 - 0.3127 - 0.3290) / 0.3290 * 100.0,
    ];
    let cam_white = mat(&CAT16, white);
    let adaptation = [
        100.0 / cam_white[0],
        100.0 / cam_white[1],
        100.0 / cam_white[2],
    ];
    let adapting_luminance: f64 = 20.0;
    let k = 1.0 / (5.0 * adapting_luminance + 1.0);
    let k4 = k.powi(4);
    let f_l = 0.2 * k4 * 5.0 * adapting_luminance
        + 0.1 * (1.0 - k4).powi(2) * (5.0 * adapting_luminance).cbrt();
    let compressed_white = [
        response(cam_white[0] * adaptation[0], f_l),
        response(cam_white[1] * adaptation[1], f_l),
        response(cam_white[2] * adaptation[2], f_l),
    ];
    let cam_a_w =
        2.0 * compressed_white[0] + compressed_white[1] + 0.05 * compressed_white[2] - 0.305;
    Model {
        adaptation,
        cam_a_w,
        cam_f_l: f_l,
        // AppearanceConfig.reference_background_ratio = 20 / 200 = 0.1.
        cam_z: 1.48 + (0.1_f64).sqrt(),
    }
}

fn eccentricity(hue: f64) -> f64 {
    let h = hue.to_radians();
    -0.0582 * h.cos() - 0.0258 * (2.0 * h).cos() - 0.1347 * (3.0 * h).cos()
        + 0.0289 * (4.0 * h).cos()
        - 0.1475 * h.sin()
        - 0.0308 * (2.0 * h).sin()
        + 0.0385 * (3.0 * h).sin()
        + 0.0096 * (4.0 * h).sin()
        + 1.0
}

fn attributes(model: Model, xyz: [f64; 3]) -> (f64, f64, f64, f64) {
    let sharpened = mat(&CAT16, [xyz[0] * 100.0, xyz[1] * 100.0, xyz[2] * 100.0]);
    let adapted = [
        sharpened[0] * model.adaptation[0],
        sharpened[1] * model.adaptation[1],
        sharpened[2] * model.adaptation[2],
    ];
    let compressed = [
        response(adapted[0], model.cam_f_l),
        response(adapted[1], model.cam_f_l),
        response(adapted[2], model.cam_f_l),
    ];
    let opponent_a = compressed[0] - 12.0 * compressed[1] / 11.0 + compressed[2] / 11.0;
    let opponent_b = (compressed[0] + compressed[1] - 2.0 * compressed[2]) / 9.0;
    let hue = (opponent_b.atan2(opponent_a).to_degrees() + 360.0) % 360.0;
    let achromatic = 2.0 * compressed[0] + compressed[1] + 0.05 * compressed[2] - 0.305;
    let j = 100.0 * signed_power(achromatic / model.cam_a_w, SURROUND_C * model.cam_z);
    let colorfulness = 43.0 * SURROUND_N_C * eccentricity(hue) * opponent_a.hypot(opponent_b);
    let chroma = 35.0 * colorfulness / model.cam_a_w;
    let j_hk = (j * j + HK_COEFFICIENT * chroma).max(0.0).sqrt();
    (j, chroma, hue, j_hk)
}

/// Return the modCAM16-HK lightness correlate for normalized D65 XYZ.
///
/// The decomposition worker uses this same appearance-model implementation as
/// the picker so its per-pixel exposure root has one numerical definition of
/// the neutral target and does not need to duplicate the model constants.
pub fn j_hk_from_xyz(xyz: [f64; 3]) -> f64 {
    attributes(model(), xyz).3
}

// This is the profile-side neutral curve used to construct D = F_p(C) for a
// slider state. Refl is solved against this curve for every ACES view profile.
fn neutral_j_hk(model: Model, profile: u32, reflectance: f64) -> f64 {
    let xyz = if profile == 3 {
        source_to_xyz(profile, [reflectance; 3])
    } else {
        transform_from_acescg(profile, [reflectance; 3])
    };
    attributes(model, xyz).3
}

fn output_neutral_j_hk(model: Model, profile: u32, value: f64) -> f64 {
    attributes(model, source_to_xyz(profile, [value; 3])).3
}

fn solve_output_neutral_for_j_hk(model: Model, profile: u32, target: f64) -> (f64, bool) {
    let mut lower = 0.0;
    let mut upper = BACKGROUND_MAX;
    let lower_j = output_neutral_j_hk(model, profile, lower);
    let upper_j = output_neutral_j_hk(model, profile, upper);
    if !target.is_finite() || !lower_j.is_finite() || !upper_j.is_finite() {
        return (
            if target.is_sign_negative() {
                lower
            } else {
                upper
            },
            false,
        );
    }
    if target < lower_j {
        return (lower, false);
    }
    if target > upper_j {
        return (upper, false);
    }
    if target == lower_j {
        return (lower, true);
    }
    if target == upper_j {
        return (upper, true);
    }
    for _ in 0..60 {
        let middle = 0.5 * (lower + upper);
        if output_neutral_j_hk(model, profile, middle) < target {
            lower = middle;
        } else {
            upper = middle;
        }
    }
    (0.5 * (lower + upper), true)
}

fn lab_d50_to_xyz(lab: [f64; 3]) -> [f64; 3] {
    let delta = 6.0 / 29.0;
    let f = [(lab[0] + 16.0) / 116.0, lab[1] / 500.0, -lab[2] / 200.0];
    let f = [f[0], f[0] + f[1], f[0] + f[2]];
    let inverse = |value: f64| {
        if value > delta {
            value.powi(3)
        } else {
            3.0 * delta * delta * (value - 4.0 / 29.0)
        }
    };
    let white = [0.34567 / 0.35850, 1.0, (1.0 - 0.34567 - 0.35850) / 0.35850];
    [
        white[0] * inverse(f[1]),
        white[1] * inverse(f[0]),
        white[2] * inverse(f[2]),
    ]
}

/// Convert one official post-November-2014 Lab/D50 patch directly to its
/// ACEScg scene-reference target. ColorChecker references intentionally do not
/// receive the RICD flare/scale or a separate HDR placement gain.
fn colorchecker_scene_target(lab_d50: [f64; 3]) -> [f64; 3] {
    mat(&XYZ_D50_TO_ACESCG, lab_d50_to_xyz(lab_d50))
}

/// Solve a profile-local neutral coordinate for a target J_HK.
///
/// The second tuple member distinguishes an exact in-range solve from a
/// finite boundary fallback. Keeping the fallback finite lets the UI display
/// and edit an unrepresentable conversion without manufacturing NaN slider
/// values.
fn solve_neutral_reflectance_for_j_hk(model: Model, profile: u32, target: f64) -> (f64, bool) {
    let mut lower = 0.0;
    let mut upper = REFLECTANCE_MAX;
    let lower_j = neutral_j_hk(model, profile, lower);
    let upper_j = neutral_j_hk(model, profile, upper);
    if !target.is_finite() || !lower_j.is_finite() || !upper_j.is_finite() {
        // A non-finite target has no meaningful direction. The upper bound is
        // the least surprising visible fallback for an over-range result.
        return (
            if target.is_sign_negative() {
                lower
            } else {
                upper
            },
            false,
        );
    }
    if target < lower_j {
        return (lower, false);
    }
    if target == lower_j {
        return (lower, true);
    }
    if target > upper_j {
        return (upper, false);
    }
    if target == upper_j {
        return (upper, true);
    }
    for _ in 0..60 {
        let middle = 0.5 * (lower + upper);
        if neutral_j_hk(model, profile, middle) < target {
            lower = middle;
        } else {
            upper = middle;
        }
    }
    (0.5 * (lower + upper), true)
}

// Keep the scalar helper available to callers inside this crate. It returns a
// finite boundary for an unreachable target; callers that need to distinguish
// a fallback use the tuple-returning solver above.
#[allow(dead_code)]
fn neutral_reflectance_for_j_hk(model: Model, profile: u32, target: f64) -> f64 {
    solve_neutral_reflectance_for_j_hk(model, profile, target).0
}

fn neutral_scalar(rgb: [f64; 3]) -> Option<f64> {
    if !finite3(rgb) {
        return None;
    }
    let value = (rgb[0] + rgb[1] + rgb[2]) / 3.0;
    let spread = max3([
        (rgb[0] - value).abs(),
        (rgb[1] - value).abs(),
        (rgb[2] - value).abs(),
    ]);
    if spread <= 2.0e-5 {
        Some(value)
    } else {
        None
    }
}

fn forward_acescg_neutral(profile: u32, value: f64) -> Option<f64> {
    if !value.is_finite() || !(0.0..=REFLECTANCE_MAX).contains(&value) {
        return None;
    }
    let xyz = if profile == 3 {
        source_to_xyz(profile, [value; 3])
    } else {
        transform_from_acescg(profile, [value; 3])
    };
    neutral_scalar(xyz_to_source(profile, xyz))
}

fn modcam_to_xyz(model: Model, j_hk: f64, chroma: f64, hue: f64) -> [f64; 3] {
    let radicand = j_hk * j_hk - HK_COEFFICIENT * chroma;
    let tolerance = 1.0e-12 * (1.0_f64).max(j_hk * j_hk);
    if !radicand.is_finite() || radicand < -tolerance || chroma < 0.0 {
        return [f64::NAN; 3];
    }
    let j = radicand.max(0.0).sqrt();
    let colorfulness = chroma * model.cam_a_w / 35.0;
    let opponent_radius = colorfulness / (43.0 * SURROUND_N_C * eccentricity(hue));
    let radians = hue.to_radians();
    let opponent = [
        model.cam_a_w * signed_power(j / 100.0, 1.0 / (SURROUND_C * model.cam_z)) + 0.305,
        opponent_radius * radians.cos(),
        opponent_radius * radians.sin(),
    ];
    let compressed = mat(&OPPONENT_TO_COMPRESSED, opponent);
    let compressed = [
        compressed[0] / 1403.0,
        compressed[1] / 1403.0,
        compressed[2] / 1403.0,
    ];
    let adapted = [
        inverse_response(compressed[0], model.cam_f_l),
        inverse_response(compressed[1], model.cam_f_l),
        inverse_response(compressed[2], model.cam_f_l),
    ];
    let sharpened = [
        adapted[0] / model.adaptation[0],
        adapted[1] / model.adaptation[1],
        adapted[2] / model.adaptation[2],
    ];
    let xyz = mat(&CAT16_INVERSE, sharpened);
    [xyz[0] / 100.0, xyz[1] / 100.0, xyz[2] / 100.0]
}

fn transform_to_acescg(profile: u32, xyz: [f64; 3]) -> [f64; 3] {
    if profile == 3 {
        mat(&XYZ_D65_TO_ACESCG, xyz)
    } else {
        aces_output::inverse_from_xyz_d65(profile, xyz)
    }
}

fn transform_from_acescg(profile: u32, acescg: [f64; 3]) -> [f64; 3] {
    if profile == 3 {
        mat(&ACESCG_TO_XYZ_D65, acescg)
    } else {
        aces_output::forward(profile, acescg)
    }
}

fn acescg_to_srgb_xyz(acescg: [f64; 3]) -> [f64; 3] {
    let target_rgb = aces_output::forward_target_rgb_from_ap0(
        1,
        aces_output::acescg_to_ap0(acescg),
    );
    mat(&REC709_TO_XYZ, [
        target_rgb[0].clamp(0.0, 1.0),
        target_rgb[1].clamp(0.0, 1.0),
        target_rgb[2].clamp(0.0, 1.0),
    ])
}

fn srgb_to_acescg(linear: [f64; 3]) -> [f64; 3] {
    aces_output::inverse_from_xyz_d65(1, source_to_xyz(3, linear))
}

fn decode_srgb(value: f64) -> f64 {
    if !value.is_finite() {
        return f64::NAN;
    }
    let sign = value.signum();
    let magnitude = value.abs();
    let linear = if magnitude <= 0.04045 {
        magnitude / 12.92
    } else {
        ((magnitude + 0.055) / 1.055).powf(2.4)
    };
    sign * linear
}

fn sample(model: Model, profile: u32, j_hk: f64, hue: f64, saturation: f64) -> Sample {
    let chroma = saturation / 100.0 * j_hk * j_hk / HK_COEFFICIENT;
    // The appearance inverse produces the target XYZ, then the selected ACES
    // view is evaluated to apply its profile-specific gamut mapping. This is
    // an intentional nonlinear reconstruction, not a redundant matrix bridge.
    let inverse_xyz = modcam_to_xyz(model, j_hk, chroma, hue);
    let acescg = transform_to_acescg(profile, inverse_xyz);
    let xyz = if profile == 3 {
        // The direct workflow has no nonlinear view to reconstruct; retain the
        // XYZ endpoint instead of applying the inverse CAT02 matrix pair.
        inverse_xyz
    } else {
        transform_from_acescg(profile, acescg)
    };
    let source_rgb = xyz_to_source(profile, xyz);
    let source_valid = finite3(source_rgb) && source_cone_valid(profile, source_rgb, xyz);
    let rendered_j_hk = attributes(model, xyz).3;
    let appearance_match =
        rendered_j_hk.is_finite() && j_hk.is_finite() && (rendered_j_hk - j_hk).abs() <= 2.0e-5;
    let valid = if profile == 3 {
        source_valid && appearance_match
    } else {
        source_valid && appearance_match && unit_cube_valid(acescg)
    };
    Sample {
        xyz,
        source_rgb,
        acescg,
        valid,
    }
}

fn maximum_saturation_inner(model: Model, profile: u32, j_hk: f64, hue: f64) -> f64 {
    let mut lower = 0.0;
    let mut upper = 100.0;
    if !sample(model, profile, j_hk, hue, lower).valid {
        return 0.0;
    }
    if sample(model, profile, j_hk, hue, upper).valid {
        return upper;
    }
    for _ in 0..40 {
        let middle = (lower + upper) * 0.5;
        if sample(model, profile, j_hk, hue, middle).valid {
            lower = middle;
        } else {
            upper = middle;
        }
    }
    lower
}

fn sample_adapted(
    model: Model,
    profile: u32,
    j_hk: f64,
    hue: f64,
    saturation: f64,
    temp: f64,
    tint: f64,
) -> Sample {
    let adapted_xyz = modcam_to_xyz(
        model,
        j_hk,
        saturation / 100.0 * j_hk * j_hk / HK_COEFFICIENT,
        hue,
    );
    // The viewport is expressed in adapted display-side coordinates. Invert
    // that display-side adaptation to recover the source color represented by
    // each pixel, then apply both source and adapted-side gamut checks. This
    // keeps the mask tied to the same pre-adaptation slider color while still
    // reflecting white-balance changes to the inverse/readout path.
    let preadapt_xyz = unadapt_xyz(model, adapted_xyz, temp, tint);
    let source_rgb = xyz_to_source(profile, preadapt_xyz);
    let acescg = transform_to_acescg(profile, preadapt_xyz);
    let rendered_j_hk = attributes(model, preadapt_xyz).3;
    let appearance_match =
        rendered_j_hk.is_finite() && j_hk.is_finite() && (rendered_j_hk - j_hk).abs() <= 2.0e-5;
    let source_valid = finite3(preadapt_xyz)
        && finite3(source_rgb)
        && source_cone_valid(profile, source_rgb, preadapt_xyz)
        && if profile == 3 {
            true
        } else {
            unit_cube_valid(acescg)
        };
    let display_tolerance = if adaptation_is_identity(temp, tint) {
        1.0e-6
    } else {
        1.0e-5
    };
    let valid = source_valid
        && appearance_match
        && adapted_display_valid(profile, adapted_xyz, display_tolerance);
    Sample {
        xyz: adapted_xyz,
        source_rgb,
        acescg,
        valid,
    }
}

fn encode_display_rgb(linear: [f64; 3]) -> [f64; 3] {
    let encode = |value: f64| {
        if !value.is_finite() {
            return 0.0;
        }
        let value = value.clamp(0.0, 1.0);
        let encoded = if value <= 0.0031308 {
            12.92 * value
        } else {
            1.055 * value.powf(1.0 / 2.4) - 0.055
        };
        encoded.clamp(0.0, 1.0)
    };
    [encode(linear[0]), encode(linear[1]), encode(linear[2])]
}

fn display_rgb(linear_rgb: [f64; 3], matrix: &[[f64; 3]; 3]) -> [u8; 3] {
    let encoded = encode_display_rgb(mat(matrix, linear_rgb));
    [
        (encoded[0] * 255.0 + 0.5).clamp(0.0, 255.0) as u8,
        (encoded[1] * 255.0 + 0.5).clamp(0.0, 255.0) as u8,
        (encoded[2] * 255.0 + 0.5).clamp(0.0, 255.0) as u8,
    ]
}

fn display_rgb_f64(linear_rgb: [f64; 3], matrix: &[[f64; 3]; 3]) -> [f64; 3] {
    encode_display_rgb(mat(matrix, linear_rgb))
}

fn display_xyz_f64(xyz: [f64; 3], matrix: &[[f64; 3]; 3]) -> [f64; 3] {
    display_rgb_f64(xyz, matrix)
}

/// Evaluate one color.
///
/// Returns `[valid, maximum_saturation, linear output (sRGB for profile 3,
/// ACEScg for ACES profiles),
/// source_r, source_g, source_b, source-preview display_p3_r, display_p3_g,
/// display_p3_b, neutral_display_p3_r, neutral_display_p3_g,
/// neutral_display_p3_b, source-preview display_srgb_r, display_srgb_g, display_srgb_b,
/// neutral_display_srgb_r, neutral_display_srgb_g, neutral_display_srgb_b,
/// encoded ACEScg/AP1_r, encoded ACEScg/AP1_g, encoded ACEScg/AP1_b,
/// forward-view neutral background]`.
#[wasm_bindgen]
pub fn evaluate(profile: u32, reflectance: f64, hue: f64, saturation: f64) -> Vec<f64> {
    evaluate_adapted(profile, reflectance, hue, saturation, 6500.0, 0.0, 0.5)[..24].to_vec()
}

/// Evaluate a color with display-side CAT02 adaptation. The first 24 values
/// The first 24 values use the established layout; values 24..26 and 27..29 are adapted background
/// Display-P3 and sRGB encodings, 30..32 retain the pre-adaptation source
/// encoding, and 33..36 carry adapted neutral/foreground polar coordinates.
#[wasm_bindgen]
pub fn evaluate_adapted(
    profile: u32,
    reflectance: f64,
    hue: f64,
    saturation: f64,
    temp: f64,
    tint: f64,
    background: f64,
) -> Vec<f64> {
    let model = model();
    let hue = hue.rem_euclid(360.0);
    let reflectance = reflectance.clamp(0.0, REFLECTANCE_MAX);
    let saturation = saturation.clamp(0.0, 100.0);
    let j_hk = neutral_j_hk(model, profile, reflectance);
    if !j_hk.is_finite() {
        return vec![0.0; 37];
    }
    let result = sample(model, profile, j_hk, hue, saturation);
    let neutral = sample(model, profile, j_hk, hue, 0.0);
    let maximum = maximum_saturation_inner(model, profile, j_hk, hue);
    // Readouts are always bounded to the unit interval. The validity bit
    // remains false when the underlying color had an out-of-range channel, so
    // the UI can show its unavailable state instead of presenting a valid
    // color for a clipped value.
    let adapted_xyz = adapt_xyz_preserve_j_hk(model, result.xyz, temp, tint);
    let adapted_neutral_xyz = adapt_xyz_preserve_j_hk(model, neutral.xyz, temp, tint);
    let acescg = transform_to_acescg(profile, adapted_xyz);
    let adapted_source_rgb = xyz_to_source(profile, adapted_xyz);
    // The overlay is positioned from these adapted polar coordinates, and the
    // raster evaluates that same inverse-polar sample. Use its validity bit so
    // the picked result cannot disagree with the pixel under the dot near a
    // gamut boundary or an appearance-model limit.
    let (_, adapted_chroma, adapted_hue, adapted_j_hk) = attributes(model, adapted_xyz);
    let adapted_sat = if adapted_j_hk > 0.0 {
        100.0 * HK_COEFFICIENT * adapted_chroma / (adapted_j_hk * adapted_j_hk)
    } else {
        0.0
    };
    let adapted_valid = adapted_j_hk.is_finite()
        && sample_adapted(model, profile, j_hk, adapted_hue, adapted_sat, temp, tint).valid;
    let linear_output = if profile == 3 {
        [
            clamp_unit(adapted_source_rgb[0]),
            clamp_unit(adapted_source_rgb[1]),
            clamp_unit(adapted_source_rgb[2]),
        ]
    } else {
        [
            clamp_unit(acescg[0]),
            clamp_unit(acescg[1]),
            clamp_unit(acescg[2]),
        ]
    };
    let neutral_display_p3 = if neutral.valid {
        display_xyz_f64(adapted_neutral_xyz, &XYZ_TO_P3)
    } else {
        [0.0; 3]
    };
    let display_p3 = if adapted_valid {
        display_xyz_f64(adapted_xyz, &XYZ_TO_P3)
    } else {
        [0.0; 3]
    };
    let display_srgb = if adapted_valid {
        display_xyz_f64(adapted_xyz, &XYZ_TO_REC709)
    } else {
        [0.0; 3]
    };
    let neutral_display_srgb = if neutral.valid {
        display_xyz_f64(adapted_neutral_xyz, &XYZ_TO_REC709)
    } else {
        [0.0; 3]
    };
    let acescg_srgb = encode_display_rgb(acescg);
    let background_neutral = forward_acescg_neutral(profile, reflectance).unwrap_or(f64::NAN);
    let background_value = if background.is_finite() {
        background.clamp(0.0, BACKGROUND_MAX)
    } else {
        0.0
    };
    let background_xyz = source_to_xyz(profile, [background_value; 3]);
    let adapted_background = adapt_xyz_preserve_j_hk(model, background_xyz, temp, tint);
    let background_display_p3 = display_xyz_f64(adapted_background, &XYZ_TO_P3);
    let background_display_srgb = display_xyz_f64(adapted_background, &XYZ_TO_REC709);
    let mut output = vec![
        if adapted_valid { 1.0 } else { 0.0 },
        maximum,
        linear_output[0],
        linear_output[1],
        linear_output[2],
        if adapted_valid {
            adapted_source_rgb[0]
        } else {
            0.0
        },
        if adapted_valid {
            adapted_source_rgb[1]
        } else {
            0.0
        },
        if adapted_valid {
            adapted_source_rgb[2]
        } else {
            0.0
        },
        display_p3[0],
        display_p3[1],
        display_p3[2],
        neutral_display_p3[0],
        neutral_display_p3[1],
        neutral_display_p3[2],
        display_srgb[0],
        display_srgb[1],
        display_srgb[2],
        neutral_display_srgb[0],
        neutral_display_srgb[1],
        neutral_display_srgb[2],
        acescg_srgb[0],
        acescg_srgb[1],
        acescg_srgb[2],
        background_neutral,
    ];
    output.extend_from_slice(&background_display_p3);
    output.extend_from_slice(&background_display_srgb);
    let retained_source = if profile == 3 {
        result.source_rgb
    } else {
        result.acescg
    };
    let retained_encoded = if finite3(retained_source) {
        encode_display_rgb(retained_source)
    } else {
        [f64::NAN; 3]
    };
    output.extend_from_slice(&retained_encoded);
    let (_, neutral_chroma, neutral_hue, neutral_j_hk) = attributes(model, adapted_neutral_xyz);
    let (_, result_chroma, result_hue, result_j_hk) = attributes(model, adapted_xyz);
    let neutral_sat = if neutral_j_hk > 0.0 {
        100.0 * HK_COEFFICIENT * neutral_chroma / (neutral_j_hk * neutral_j_hk)
    } else {
        0.0
    };
    let result_sat = if result_j_hk > 0.0 {
        100.0 * HK_COEFFICIENT * result_chroma / (result_j_hk * result_j_hk)
    } else {
        0.0
    };
    let neutral_hue = if neutral_hue.is_finite() {
        neutral_hue.rem_euclid(360.0)
    } else {
        0.0
    };
    let neutral_sat = if neutral_sat.is_finite() {
        neutral_sat.clamp(0.0, 100.0)
    } else {
        0.0
    };
    let result_hue = if result_hue.is_finite() {
        result_hue.rem_euclid(360.0)
    } else {
        0.0
    };
    let result_sat = if result_sat.is_finite() {
        result_sat.clamp(0.0, 100.0)
    } else {
        0.0
    };
    output.extend_from_slice(&[neutral_hue, neutral_sat, result_hue, result_sat]);
    output
}

/// Adapt a linear neutral through exact inverse and forward profile transforms.
/// The returned values are `[valid, bounded_target_neutral]`.
#[wasm_bindgen]
pub fn convert_neutral_profile(
    source_profile: u32,
    target_profile: u32,
    source_neutral: f64,
) -> Vec<f64> {
    if !source_neutral.is_finite() || !(0.0..=BACKGROUND_MAX).contains(&source_neutral) {
        return vec![0.0, f64::NAN];
    }
    if source_profile == target_profile {
        return vec![1.0, source_neutral];
    }
    let source_rgb = [source_neutral; 3];
    let acescg = if source_profile == 3 && target_profile != 3 {
        srgb_to_acescg(source_rgb)
    } else {
        transform_to_acescg(source_profile, source_to_xyz(source_profile, source_rgb))
    };
    let target_xyz = if target_profile == 3 && source_profile != 3 {
        acescg_to_srgb_xyz(acescg)
    } else {
        transform_from_acescg(target_profile, acescg)
    };
    let target_rgb = xyz_to_source(target_profile, target_xyz);
    let Some(target_neutral) = neutral_scalar(target_rgb) else {
        return vec![0.0, f64::NAN];
    };
    let valid = finite3(acescg) && target_neutral.is_finite() && target_neutral >= 0.0;
    vec![
        if valid { 1.0 } else { 0.0 },
        target_neutral.clamp(0.0, BACKGROUND_MAX),
    ]
}

/// Convert sRGB-encoded ACEScg/AP1 values back to the source appearance
/// coordinates used by the sliders. The returned values are
/// `[valid, profile_refl, hue, saturation]`. For ACES profiles, Refl is solved
/// against the selected profile's forward neutral curve.
#[wasm_bindgen]
pub fn set_from_acescg_srgb(profile: u32, red: f64, green: f64, blue: f64) -> Vec<f64> {
    set_from_acescg_srgb_adapted(profile, red, green, blue, 6500.0, 0.0)
}

#[wasm_bindgen]
pub fn set_from_acescg_srgb_adapted(
    profile: u32,
    red: f64,
    green: f64,
    blue: f64,
    temp: f64,
    tint: f64,
) -> Vec<f64> {
    let model = model();
    let acescg = [decode_srgb(red), decode_srgb(green), decode_srgb(blue)];
    let displayed_xyz = if profile == 3 {
        acescg_to_srgb_xyz(acescg)
    } else {
        transform_from_acescg(profile, acescg)
    };
    let xyz = unadapt_xyz(model, displayed_xyz, temp, tint);
    coordinates_from_rendered_xyz(model, profile, None, xyz)
}

/// Derive all three slider coordinates for an existing ACEScg color.
///
/// The returned values are `[valid, reflectance, hue, saturation]`.
#[wasm_bindgen]
pub fn set_profile_from_acescg_srgb(
    profile: u32,
    _reflectance: f64,
    red: f64,
    green: f64,
    blue: f64,
) -> Vec<f64> {
    let model = model();
    let acescg = [decode_srgb(red), decode_srgb(green), decode_srgb(blue)];
    let xyz = if profile == 3 {
        acescg_to_srgb_xyz(acescg)
    } else {
        transform_from_acescg(profile, acescg)
    };
    coordinates_from_rendered_xyz(model, profile, None, xyz)
}

fn output_srgb_to_xyz(red: f64, green: f64, blue: f64) -> ([f64; 3], [f64; 3]) {
    let linear = [decode_srgb(red), decode_srgb(green), decode_srgb(blue)];
    (linear, source_to_xyz(3, linear))
}

fn target_xyz_from_output_srgb(profile: u32, linear: [f64; 3], clamp_srgb: bool) -> [f64; 3] {
    let linear = if clamp_srgb {
        [
            linear[0].clamp(0.0, 1.0),
            linear[1].clamp(0.0, 1.0),
            linear[2].clamp(0.0, 1.0),
        ]
    } else {
        linear
    };
    if profile == 3 {
        source_to_xyz(3, linear)
    } else {
        // Direct sRGB is interpreted through the inverse ACES 2.0 Rec.709
        // 100-nit view before it is rendered by the selected ACES profile.
        let acescg = srgb_to_acescg(linear);
        transform_from_acescg(profile, acescg)
    }
}

fn target_xyz_from_retained_color(
    source_profile: u32,
    target_profile: u32,
    red: f64,
    green: f64,
    blue: f64,
) -> [f64; 3] {
    let encoded = [red, green, blue];
    if source_profile == 3 {
        let linear = [
            decode_srgb(encoded[0]),
            decode_srgb(encoded[1]),
            decode_srgb(encoded[2]),
        ];
        target_xyz_from_output_srgb(target_profile, linear, false)
    } else {
        let acescg = [
            decode_srgb(encoded[0]),
            decode_srgb(encoded[1]),
            decode_srgb(encoded[2]),
        ];
        if target_profile == 3 {
            acescg_to_srgb_xyz(acescg)
        } else {
            transform_from_acescg(target_profile, acescg)
        }
    }
}

/// Convert a profile's background slider around the retained foreground.
///
/// The slider is a neutral value, but its snap point is defined by the
/// foreground's J_HK. Preserve the source background's J_HK offset from that
/// foreground neutral and solve the equivalent target neutral coordinate.
#[wasm_bindgen]
pub fn convert_background_profile(
    source_profile: u32,
    target_profile: u32,
    source_background: f64,
    source_reflectance: f64,
    red: f64,
    green: f64,
    blue: f64,
) -> Vec<f64> {
    let model = model();
    if !source_background.is_finite()
        || !(0.0..=BACKGROUND_MAX).contains(&source_background)
        || !source_reflectance.is_finite()
        || !(0.0..=REFLECTANCE_MAX).contains(&source_reflectance)
    {
        return vec![0.0, f64::NAN];
    }
    let target_xyz =
        target_xyz_from_retained_color(source_profile, target_profile, red, green, blue);
    let target_foreground_j = attributes(model, target_xyz).3;
    let source_foreground_j = neutral_j_hk(model, source_profile, source_reflectance);
    let source_background_j = output_neutral_j_hk(model, source_profile, source_background);
    let target_j = target_foreground_j + source_background_j - source_foreground_j;
    let (target_background, _exact) =
        solve_output_neutral_for_j_hk(model, target_profile, target_j);
    let valid = target_foreground_j.is_finite()
        && source_foreground_j.is_finite()
        && source_background_j.is_finite()
        && target_background.is_finite();
    vec![
        if valid { 1.0 } else { 0.0 },
        target_background.clamp(0.0, BACKGROUND_MAX),
    ]
}

fn coordinates_from_rendered_xyz(
    model: Model,
    profile: u32,
    requested_reflectance: Option<f64>,
    xyz: [f64; 3],
) -> Vec<f64> {
    coordinates_from_rendered_xyz_mode(model, profile, requested_reflectance, xyz, true)
}

fn coordinates_from_rendered_xyz_mode(
    model: Model,
    profile: u32,
    requested_reflectance: Option<f64>,
    xyz: [f64; 3],
    solve_profile_refl: bool,
) -> Vec<f64> {
    let (_, chroma, hue, j_hk) = attributes(model, xyz);
    // Solve Refl from the target rendered J_HK. A requested value is only
    // accepted by the direct-target branch used by callers that need to
    // explicitly preserve a neutral; profile switches and color entry always
    // pass `None` so the target coordinates describe the rendered color.
    let (reflectance, neutral_match) =
        if solve_profile_refl && (profile != 3 || requested_reflectance.is_none()) {
            solve_neutral_reflectance_for_j_hk(model, profile, j_hk)
        } else {
            let requested = requested_reflectance.expect("checked above");
            let reflectance = if requested.is_finite() {
                requested.clamp(0.0, REFLECTANCE_MAX)
            } else if j_hk.is_sign_negative() {
                0.0
            } else {
                REFLECTANCE_MAX
            };
            let target_j_hk = neutral_j_hk(model, profile, reflectance);
            (
                reflectance,
                requested.is_finite()
                    && target_j_hk.is_finite()
                    && (j_hk - target_j_hk).abs() <= 2.0e-5,
            )
        };
    let saturation = if j_hk > 0.0 {
        100.0 * HK_COEFFICIENT * chroma / (j_hk * j_hk)
    } else if chroma.abs() <= 1.0e-12 {
        0.0
    } else {
        f64::NAN
    };
    let saturation = if saturation.abs() < 1.0e-4 {
        0.0
    } else {
        saturation
    };
    let target_j_hk = neutral_j_hk(model, profile, reflectance);
    let reconstructed = if target_j_hk.is_finite() && hue.is_finite() && saturation.is_finite() {
        sample(model, profile, target_j_hk, hue, saturation)
    } else {
        Sample {
            xyz: [f64::NAN; 3],
            source_rgb: [f64::NAN; 3],
            acescg: [f64::NAN; 3],
            valid: false,
        }
    };
    let reconstruction_error = max3([
        (reconstructed.xyz[0] - xyz[0]).abs(),
        (reconstructed.xyz[1] - xyz[1]).abs(),
        (reconstructed.xyz[2] - xyz[2]).abs(),
    ]);
    let model_match = neutral_match && reconstruction_error <= 2.0e-5;
    let source_rgb = xyz_to_source(profile, xyz);
    let valid = finite3(xyz)
        && finite3(source_rgb)
        && source_cone_valid(profile, source_rgb, xyz)
        && reflectance.is_finite()
        && (0.0..=REFLECTANCE_MAX).contains(&reflectance)
        && hue.is_finite()
        && saturation.is_finite()
        && (0.0..=100.0).contains(&saturation);
    let valid = valid && reconstructed.valid && model_match;
    let output_hue = if hue.is_finite() {
        hue.rem_euclid(360.0)
    } else {
        0.0
    };
    let output_saturation = if saturation.is_finite() {
        saturation.clamp(0.0, 100.0)
    } else {
        0.0
    };
    vec![
        if valid { 1.0 } else { 0.0 },
        reflectance.clamp(0.0, REFLECTANCE_MAX),
        output_hue,
        output_saturation,
    ]
}

/// Convert an sRGB-encoded Rec.709 value into the selected profile's slider
/// coordinates. This input is always the output sRGB color shown by the UI.
#[wasm_bindgen]
pub fn set_from_output_srgb(profile: u32, red: f64, green: f64, blue: f64) -> Vec<f64> {
    set_from_output_srgb_adapted(profile, red, green, blue, 6500.0, 0.0)
}

#[wasm_bindgen]
pub fn set_from_output_srgb_adapted(
    profile: u32,
    red: f64,
    green: f64,
    blue: f64,
    temp: f64,
    tint: f64,
) -> Vec<f64> {
    let model = model();
    let (linear, _) = output_srgb_to_xyz(red, green, blue);
    let displayed_xyz = if profile == 3 {
        source_to_xyz(
            3,
            [
                linear[0].clamp(0.0, 1.0),
                linear[1].clamp(0.0, 1.0),
                linear[2].clamp(0.0, 1.0),
            ],
        )
    } else {
        target_xyz_from_output_srgb(profile, linear, profile == 3)
    };
    let xyz = unadapt_xyz(model, displayed_xyz, temp, tint);
    coordinates_from_rendered_xyz(model, profile, None, xyz)
}

/// Convert an encoded ACEScg/AP1 value during a profile switch. ACES targets
/// solve all three coordinates from the retained ACEScg color; a direct sRGB
/// target remains on the separate clipped/output workflow.
#[wasm_bindgen]
pub fn set_profile_from_acescg_srgb_converted(
    profile: u32,
    _reflectance: f64,
    red: f64,
    green: f64,
    blue: f64,
) -> Vec<f64> {
    let model = model();
    let acescg = [decode_srgb(red), decode_srgb(green), decode_srgb(blue)];
    let xyz = if profile == 3 {
        acescg_to_srgb_xyz(acescg)
    } else {
        transform_from_acescg(profile, acescg)
    };
    // A direct sRGB target owns the output color, so derive its Refl/Hue/Sat
    // from the clipped target XYZ just like an output-color entry. Carrying
    // the ACES source Refl here can make an otherwise valid conversion look
    // invalid when the two neutral curves differ.
    coordinates_from_rendered_xyz(model, profile, None, xyz)
}

/// Convert an encoded output-sRGB value into slider coordinates for direct
/// editing. Refl is solved from the selected profile's native neutral curve.
#[wasm_bindgen]
pub fn set_profile_from_output_srgb(profile: u32, red: f64, green: f64, blue: f64) -> Vec<f64> {
    let model = model();
    let (linear, _) = output_srgb_to_xyz(red, green, blue);
    let xyz = target_xyz_from_output_srgb(profile, linear, profile == 3);
    coordinates_from_rendered_xyz(model, profile, None, xyz)
}

/// Convert a retained output-sRGB value during a profile switch. The retained
/// output color is first interpreted through the inverse Rec.709 100-nit view
/// whenever the target is an ACES profile, then all target coordinates are
/// solved from the resulting rendered color.
#[wasm_bindgen]
pub fn set_profile_from_output_srgb_converted(
    profile: u32,
    _reflectance: f64,
    red: f64,
    green: f64,
    blue: f64,
) -> Vec<f64> {
    let model = model();
    let (linear, _) = output_srgb_to_xyz(red, green, blue);
    let xyz = target_xyz_from_output_srgb(profile, linear, profile == 3);
    // The output-sRGB value is the canonical color for transitions sourced
    // from the direct profile. Re-solve all target coordinates from that
    // color so the target neutral curve uses its current J_HK.
    coordinates_from_rendered_xyz(model, profile, None, xyz)
}

/// Build one absolute-ACEScg ColorChecker reference record.
///
/// The source measurement is first converted to an absolute ACEScg value and
/// rendered through the selected profile. Hue, saturation, and the profile's
/// Refl coordinate are then derived from that rendered XYZ. `available`
/// reports whether the rendered reference has a usable nonnegative source
/// preimage; it never changes the coordinates or dot color.
fn colorchecker_record_from_acescg_adapted(
    model: Model,
    profile: u32,
    acescg_target: [f64; 3],
    temp: f64,
    tint: f64,
) -> [f64; 12] {
    let profile_xyz = transform_from_acescg(profile, acescg_target);
    let (j, chroma, raw_hue, j_hk) = attributes(model, profile_xyz);
    let hue = if raw_hue.is_finite() {
        raw_hue.rem_euclid(360.0)
    } else {
        0.0
    };
    let saturation = if j_hk.is_finite() && j_hk > 0.0 && chroma.is_finite() {
        100.0 * HK_COEFFICIENT * chroma / (j_hk * j_hk)
    } else {
        0.0
    };
    // Match the same target-profile neutral solve used by ACEScg entry and
    // profile switching. An out-of-range J_HK remains visible at a finite
    // slider boundary while `neutral_available` records that it is only a
    // fallback coordinate.
    let (profile_reflectance, neutral_available) =
        solve_neutral_reflectance_for_j_hk(model, profile, j_hk);
    let source_rgb = xyz_to_source(profile, profile_xyz);
    let target_j_hk = neutral_j_hk(model, profile, profile_reflectance);
    let neutral_representable = target_j_hk.is_finite() && (target_j_hk - j_hk).abs() <= 2.0e-5;
    let target_in_output_range = if profile == 3 {
        finite3(source_rgb) && min3(source_rgb) >= -1.0e-6 && max3(source_rgb) <= 1.0 + 1.0e-6
    } else {
        finite3(acescg_target)
            && min3(acescg_target) >= -1.0e-6
            && max3(acescg_target) <= 1.0 + 1.0e-6
    };
    let available = finite3(profile_xyz)
        && finite3(source_rgb)
        && finite3(acescg_target)
        && target_in_output_range
        && j.is_finite()
        && chroma.is_finite()
        && hue.is_finite()
        && saturation.is_finite()
        && neutral_available
        && neutral_representable
        && source_cone_valid(profile, source_rgb, profile_xyz);
    let adapted_xyz = adapt_xyz_preserve_j_hk(model, profile_xyz, temp, tint);
    let (_, adapted_chroma, adapted_hue, adapted_j_hk) = attributes(model, adapted_xyz);
    let adapted_saturation = if adapted_j_hk > 0.0 {
        100.0 * HK_COEFFICIENT * adapted_chroma / (adapted_j_hk * adapted_j_hk)
    } else {
        0.0
    };
    let adapted_hue = if adapted_hue.is_finite() {
        adapted_hue.rem_euclid(360.0)
    } else {
        hue
    };
    let adapted_saturation = if adapted_saturation.is_finite() {
        adapted_saturation.clamp(0.0, 100.0)
    } else {
        saturation
    };
    let display_p3 = display_xyz_f64(adapted_xyz, &XYZ_TO_P3);
    let display_srgb = display_xyz_f64(adapted_xyz, &XYZ_TO_REC709);
    [
        hue,
        saturation,
        profile_reflectance,
        display_p3[0],
        display_p3[1],
        display_p3[2],
        display_srgb[0],
        display_srgb[1],
        display_srgb[2],
        if available { 1.0 } else { 0.0 },
        adapted_hue,
        adapted_saturation,
    ]
}

#[allow(dead_code)]
fn colorchecker_record_from_acescg(
    model: Model,
    profile: u32,
    acescg_target: [f64; 3],
) -> [f64; 10] {
    let adapted =
        colorchecker_record_from_acescg_adapted(model, profile, acescg_target, 6500.0, 0.0);
    let mut record = [0.0; 10];
    record.copy_from_slice(&adapted[..10]);
    record
}

/// Calculate the absolute-ACEScg ColorChecker markers at runtime for one
/// profile.
///
/// Each ten-value record is `[hue, saturation, profile_refl, display_p3_r,
/// display_p3_g, display_p3_b, display_srgb_r, display_srgb_g, display_srgb_b,
/// available]`. The frontend supplies the corresponding patch names in the
/// same official dataset order.
#[wasm_bindgen]
pub fn colorchecker_points(profile: u32) -> Vec<f64> {
    let adapted = colorchecker_points_adapted(profile, 6500.0, 0.0);
    let mut output = Vec::with_capacity(COLORCHECKER_LAB_D50.len() * 10);
    for chunk in adapted.chunks_exact(12) {
        output.extend_from_slice(&chunk[..10]);
    }
    output
}

/// Adapted ColorChecker records append `adapted_hue` and `adapted_saturation`
/// to that ten-value layout.
#[wasm_bindgen]
pub fn colorchecker_points_adapted(profile: u32, temp: f64, tint: f64) -> Vec<f64> {
    let model = model();
    let mut output = Vec::with_capacity(COLORCHECKER_LAB_D50.len() * 12);
    for lab in COLORCHECKER_LAB_D50 {
        let acescg_target = colorchecker_scene_target(lab);
        output.extend_from_slice(&colorchecker_record_from_acescg_adapted(
            model,
            profile,
            acescg_target,
            temp,
            tint,
        ));
    }
    output
}

/// Return the maximum usable saturation for one reflectance/hue direction.
#[wasm_bindgen]
pub fn maximum_saturation(profile: u32, reflectance: f64, hue: f64) -> f64 {
    let model = model();
    let reflectance = reflectance.clamp(0.0, REFLECTANCE_MAX);
    maximum_saturation_inner(
        model,
        profile,
        neutral_j_hk(model, profile, reflectance),
        hue.rem_euclid(360.0),
    )
}

fn render_rows_inner(
    profile: u32,
    reflectance: f64,
    width: u32,
    height: u32,
    y_start: u32,
    y_end: u32,
    source_display_matrix: &[[f64; 3]; 3],
    temp: f64,
    tint: f64,
) -> Vec<u8> {
    let model = model();
    let width = width.max(1) as usize;
    let height = height.max(1) as usize;
    let center_x = (width as f64 - 1.0) / 2.0;
    let center_y = (height as f64 - 1.0) / 2.0;
    let max_radius = (width.min(height) as f64) / 2.0;
    let start = (y_start as usize).min(height);
    let end = (y_end as usize).min(height).max(start);
    let mut output = vec![0_u8; (end - start) * width * 4];
    let reflectance = reflectance.clamp(0.0, REFLECTANCE_MAX);
    let solved_j_hk = {
        let value = neutral_j_hk(model, profile, reflectance);
        value.is_finite().then_some(value)
    };
    for y in start..end {
        for x in 0..width {
            let dx = x as f64 - center_x;
            let dy = y as f64 - center_y;
            let radius = dx.hypot(dy);
            let index = ((y - start) * width + x) * 4;
            if radius > max_radius {
                continue;
            }
            // 0 degrees points up; positive angles travel counter-clockwise.
            let hue = (-dx).atan2(-dy).to_degrees().rem_euclid(360.0);
            let saturation = radius / max_radius * 100.0;
            let result = solved_j_hk
                .map(|j_hk| sample_adapted(model, profile, j_hk, hue, saturation, temp, tint));
            if result.is_some_and(|value| value.valid) {
                let rgb = display_rgb(result.unwrap().xyz, source_display_matrix);
                output[index..index + 4].copy_from_slice(&[rgb[0], rgb[1], rgb[2], 255]);
            } else {
                output[index..index + 4].copy_from_slice(&[0, 0, 0, 255]);
            }
        }
    }
    output
}

/// Render rows `[y_start, y_end)` of the 512x512 radial slice as Display P3
/// RGBA bytes.
#[wasm_bindgen]
pub fn render_rows(profile: u32, reflectance: f64, y_start: u32, y_end: u32) -> Vec<u8> {
    render_rows_inner(
        profile,
        reflectance,
        WIDTH as u32,
        HEIGHT as u32,
        y_start,
        y_end,
        &XYZ_TO_P3,
        6500.0,
        0.0,
    )
}

/// Render rows as sRGB RGBA bytes for browsers without Display P3 canvas
/// support.
#[wasm_bindgen]
pub fn render_rows_srgb(profile: u32, reflectance: f64, y_start: u32, y_end: u32) -> Vec<u8> {
    render_rows_inner(
        profile,
        reflectance,
        WIDTH as u32,
        HEIGHT as u32,
        y_start,
        y_end,
        &XYZ_TO_REC709,
        6500.0,
        0.0,
    )
}

/// Render rows of a square radial slice at the requested backing resolution.
/// The frontend uses this for responsive slider previews and the fixed-size
/// `render_rows` wrapper for settled 512x512 slices.
#[wasm_bindgen]
pub fn render_rows_scaled(
    profile: u32,
    reflectance: f64,
    width: u32,
    height: u32,
    y_start: u32,
    y_end: u32,
) -> Vec<u8> {
    render_rows_inner(
        profile,
        reflectance,
        width,
        height,
        y_start,
        y_end,
        &XYZ_TO_P3,
        6500.0,
        0.0,
    )
}

/// Render rows of a square radial slice at the requested backing resolution
/// as sRGB RGBA bytes.
#[wasm_bindgen]
pub fn render_rows_scaled_srgb(
    profile: u32,
    reflectance: f64,
    width: u32,
    height: u32,
    y_start: u32,
    y_end: u32,
) -> Vec<u8> {
    render_rows_inner(
        profile,
        reflectance,
        width,
        height,
        y_start,
        y_end,
        &XYZ_TO_REC709,
        6500.0,
        0.0,
    )
}

#[wasm_bindgen]
pub fn render_rows_adapted(
    profile: u32,
    reflectance: f64,
    y_start: u32,
    y_end: u32,
    temp: f64,
    tint: f64,
) -> Vec<u8> {
    render_rows_inner(
        profile,
        reflectance,
        WIDTH as u32,
        HEIGHT as u32,
        y_start,
        y_end,
        &XYZ_TO_P3,
        temp,
        tint,
    )
}

#[wasm_bindgen]
pub fn render_rows_scaled_adapted(
    profile: u32,
    reflectance: f64,
    width: u32,
    height: u32,
    y_start: u32,
    y_end: u32,
    temp: f64,
    tint: f64,
) -> Vec<u8> {
    render_rows_inner(
        profile,
        reflectance,
        width,
        height,
        y_start,
        y_end,
        &XYZ_TO_P3,
        temp,
        tint,
    )
}

#[wasm_bindgen]
pub fn render_rows_adapted_srgb(
    profile: u32,
    reflectance: f64,
    y_start: u32,
    y_end: u32,
    temp: f64,
    tint: f64,
) -> Vec<u8> {
    render_rows_inner(
        profile,
        reflectance,
        WIDTH as u32,
        HEIGHT as u32,
        y_start,
        y_end,
        &XYZ_TO_REC709,
        temp,
        tint,
    )
}

#[wasm_bindgen]
pub fn render_rows_scaled_adapted_srgb(
    profile: u32,
    reflectance: f64,
    width: u32,
    height: u32,
    y_start: u32,
    y_end: u32,
    temp: f64,
    tint: f64,
) -> Vec<u8> {
    render_rows_inner(
        profile,
        reflectance,
        width,
        height,
        y_start,
        y_end,
        &XYZ_TO_REC709,
        temp,
        tint,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn neutral_j_hk_is_monotonic() {
        let m = model();
        let values = [0.0, 0.01, 0.1, 0.5, 1.0];
        let mut previous = 0.0;
        for value in values {
            let current = neutral_j_hk(m, 0, value);
            assert!(current >= previous);
            previous = current;
        }
    }

    #[test]
    fn adaptation_4500_warms_display() {
        let d65 = evaluate_adapted(3, 0.5, 30.0, 40.0, 6500.0, 0.0, 0.5);
        let warm = evaluate_adapted(3, 0.5, 30.0, 40.0, 4500.0, 0.0, 0.5);
        assert!(
            warm[14] > warm[15],
            "warm adaptation should increase red relative to green"
        );
        assert!((d65[0] - warm[0]).abs() < 1.0e-9);
    }

    #[test]
    fn adaptation_preserves_j_hk() {
        let m = model();
        let xyz = transform_from_acescg(1, [0.3, 0.2, 0.1]);
        let adapted = adapt_xyz_preserve_j_hk(m, xyz, 4500.0, 0.0);
        assert!((attributes(m, xyz).3 - attributes(m, adapted).3).abs() < 1.0e-5);
    }

    #[test]
    fn adaptation_keeps_low_reflectance_samples_reachable() {
        for profile in [0, 1, 2, 3, 4] {
            for reflectance in [0.0001, 0.0005, 0.001] {
                let values = evaluate_adapted(profile, reflectance, 0.0, 0.0, 4500.0, 0.0, 0.5);
                assert!(
                    values[0] > 0.5,
                    "profile={profile} reflectance={reflectance}"
                );
                assert!(values[2..5]
                    .iter()
                    .all(|value| value.is_finite() && *value >= 0.0));
            }
        }
    }

    #[test]
    fn cat02_maps_d65_to_requested_white() {
        let source = white_xyz_from_cct(6500.0, 0.0);
        let target = white_xyz_from_cct(4500.0, 0.0);
        let (matrix, _) = cat02_matrix(4500.0, 0.0);
        let mapped = mat(&matrix, source);
        assert!(
            max3([
                (mapped[0] - target[0]).abs(),
                (mapped[1] - target[1]).abs(),
                (mapped[2] - target[2]).abs(),
            ]) < 1.0e-6
        );
    }

    #[test]
    fn tint_follows_green_magenta_axis() {
        let green = evaluate_adapted(3, 0.5, 0.0, 0.0, 6500.0, -100.0, 0.5);
        let magenta = evaluate_adapted(3, 0.5, 0.0, 0.0, 6500.0, 100.0, 0.5);
        assert!(
            green[15] > green[14] && green[15] > green[16],
            "negative tint should move the neutral toward green"
        );
        assert!(
            magenta[14] > magenta[15] && magenta[16] > magenta[15],
            "positive tint should move the neutral toward magenta"
        );
    }

    #[test]
    fn cct_curve_is_anchored_and_continuous_at_d65() {
        let d65 = white_xyz_from_cct(6500.0, 0.0);
        let expected = [
            D65_XY[0] / D65_XY[1],
            1.0,
            (1.0 - D65_XY[0] - D65_XY[1]) / D65_XY[1],
        ];
        assert!(
            max3([
                (d65[0] - expected[0]).abs(),
                (d65[1] - expected[1]).abs(),
                (d65[2] - expected[2]).abs(),
            ]) < 1.0e-12
        );
        let below = white_xyz_from_cct(6499.0, 0.0);
        let above = white_xyz_from_cct(6501.0, 0.0);
        let continuity = [
            (below[0] - d65[0]).abs(),
            (below[1] - d65[1]).abs(),
            (below[2] - d65[2]).abs(),
            (above[0] - d65[0]).abs(),
            (above[1] - d65[1]).abs(),
            (above[2] - d65[2]).abs(),
        ];
        assert!(continuity.iter().copied().fold(0.0, f64::max) < 1.0e-3);
    }

    #[test]
    fn adapted_background_changes_with_white_balance() {
        let d65 = evaluate_adapted(3, 0.5, 30.0, 20.0, 6500.0, 0.0, 0.35);
        let warm = evaluate_adapted(3, 0.5, 30.0, 20.0, 4500.0, 0.0, 0.35);
        assert!((d65[27] - warm[27]).abs() > 1.0e-4 || (d65[28] - warm[28]).abs() > 1.0e-4);
    }

    #[test]
    fn background_value_changes_display_surround() {
        let dark = evaluate_adapted(3, 0.5, 30.0, 20.0, 6500.0, 0.0, 0.1);
        let light = evaluate_adapted(3, 0.5, 30.0, 20.0, 6500.0, 0.0, 0.8);
        assert!(dark[27..30]
            .iter()
            .zip(light[27..30].iter())
            .all(|(low, high)| high > low));
    }

    #[test]
    fn invalid_adapted_inputs_keep_evaluation_finite() {
        let values = evaluate_adapted(3, 0.5, f64::NAN, 20.0, 4500.0, 0.0, 0.5);
        // The visible/readout and coordinate fields remain finite; the
        // retained pre-adaptation encoding is NaN here because the requested
        // hue itself was non-finite and cannot be used for a profile switch.
        assert!(values[..30].iter().all(|value| value.is_finite()));
        assert!(values[33..].iter().all(|value| value.is_finite()));
    }

    #[test]
    fn adapted_acescg_entry_round_trips_controls() {
        let values = evaluate_adapted(1, 0.4, 120.0, 25.0, 4500.0, 0.0, 0.5);
        assert!(values[0] > 0.5);
        let set = set_from_acescg_srgb_adapted(1, values[20], values[21], values[22], 4500.0, 0.0);
        assert!(set[0] > 0.5);
        assert!((set[1] - 0.4).abs() < 2.0e-3);
        assert!((set[2] - 120.0).abs() < 0.1);
        assert!((set[3] - 25.0).abs() < 0.1);
    }

    #[test]
    fn adapted_srgb_entry_round_trips_controls() {
        let values = evaluate_adapted(3, 0.4, 120.0, 25.0, 4500.0, 0.0, 0.5);
        assert!(values[0] > 0.5);
        let set = set_from_output_srgb_adapted(3, values[14], values[15], values[16], 4500.0, 0.0);
        assert!(set[0] > 0.5);
        assert!((set[1] - 0.4).abs() < 2.0e-3);
        assert!((set[2] - 120.0).abs() < 0.1);
        assert!((set[3] - 25.0).abs() < 0.1);
    }

    #[test]
    fn adapted_slice_keeps_aces_gamut_mask_at_d65() {
        let m = model();
        for profile in [0, 1, 2, 4] {
            let j_hk = neutral_j_hk(m, profile, 0.9);
            for hue in (0..360).step_by(30) {
                for saturation in [0.0, 20.0, 40.0, 60.0, 80.0, 100.0] {
                    assert_eq!(
                        sample(m, profile, j_hk, hue as f64, saturation).valid,
                        sample_adapted(m, profile, j_hk, hue as f64, saturation, 6500.0, 0.0).valid,
                        "profile={profile} hue={hue} saturation={saturation}"
                    );
                }
            }
        }
    }

    #[test]
    fn adapted_overlay_and_picker_share_p3_mask_boundary() {
        let model = model();
        let profile = 2;
        let reflectance = 0.2;
        let hue = 270.0;
        let saturation = 90.0;
        let j_hk = neutral_j_hk(model, profile, reflectance);
        let values = evaluate_adapted(profile, reflectance, hue, saturation, 4500.0, 0.0, 0.5);
        let raster_sample =
            sample_adapted(model, profile, j_hk, values[35], values[36], 4500.0, 0.0);
        assert!(values[0] > 0.5);
        assert!(raster_sample.valid);
    }

    #[test]
    fn neutral_j_hk_uses_the_forward_rendered_acescg_neutral() {
        let m = model();
        for profile in [0, 1, 2, 4] {
            for reflectance in [0.0, 0.5, 1.0, REFLECTANCE_MAX] {
                let expected = attributes(m, transform_from_acescg(profile, [reflectance; 3])).3;
                assert!((neutral_j_hk(m, profile, reflectance) - expected).abs() < 1.0e-12);
            }
        }
    }

    #[test]
    fn profile_refl_solves_unit_acescg_white() {
        let m = model();
        for profile in [0, 1, 2, 4] {
            let rendered = transform_from_acescg(profile, [1.0; 3]);
            let j_hk = attributes(m, rendered).3;
            let (reflectance, exact) = solve_neutral_reflectance_for_j_hk(m, profile, j_hk);
            assert!(exact, "profile={profile}");
            assert!((neutral_j_hk(m, profile, reflectance) - j_hk).abs() < 1.0e-10);
        }
    }

    #[test]
    fn neutral_refl_round_trips_through_the_profile() {
        let values = evaluate(0, 0.858, 0.0, 0.0);
        assert!(values[0] > 0.5);
        assert!((values[2] - 0.858).abs() < 2.0e-5);
        assert!((values[3] - 0.858).abs() < 2.0e-5);
        assert!((values[4] - 0.858).abs() < 2.0e-5);
        assert!((values[5] - 0.90996).abs() < 2.0e-4);
        assert!((values[6] - 0.90996).abs() < 2.0e-4);
        assert!((values[7] - 0.90996).abs() < 2.0e-4);
    }

    #[test]
    fn evaluated_forward_color_matches_the_neutral_j_hk_target() {
        let m = model();
        for profile in [0, 1, 2, 4] {
            for (reflectance, hue, saturation) in [(0.2, 15.0, 5.0), (0.5, 120.0, 30.0)] {
                let values = evaluate(profile, reflectance, hue, saturation);
                assert!(values[0] > 0.5, "profile={profile}");
                let acescg = [values[2], values[3], values[4]];
                let rendered = transform_from_acescg(profile, acescg);
                let actual = attributes(m, rendered).3;
                let expected = neutral_j_hk(m, profile, reflectance);
                assert!((actual - expected).abs() < 2.0e-5, "profile={profile}");
            }
        }
    }

    #[test]
    fn readouts_are_unit_bounded_when_refl_exceeds_unity() {
        let yellow = &colorchecker_points(1)[15 * 10..16 * 10];
        assert!((0.0..=REFLECTANCE_MAX).contains(&yellow[2]));
        let values = evaluate(1, yellow[2], yellow[0], yellow[1]);
        assert!(values[0] > 0.5);
        assert!(values[2..5]
            .iter()
            .all(|value| value.is_finite() && (0.0..=1.0).contains(value)));

        let values = evaluate(1, REFLECTANCE_MAX, 0.0, 0.0);
        assert!(values[0] <= 0.5);
        assert!(values[2..5]
            .iter()
            .all(|value| value.is_finite() && (0.0..=1.0).contains(value)));
    }

    #[test]
    fn colorchecker_points_are_absolute_acescg_references_for_each_profile() {
        let m = model();
        for profile in [0, 1, 2, 4] {
            let points = colorchecker_points(profile);
            assert_eq!(points.len(), 18 * 10);
            for (index, record) in points.chunks_exact(10).enumerate() {
                assert!(record[..9].iter().all(|value| value.is_finite()));
                assert!((0.0..360.0).contains(&record[0]));
                assert!(record[1] >= 0.0);
                assert!(
                    (0.0..=REFLECTANCE_MAX).contains(&record[2]),
                    "profile={profile} patch={index} refl={}",
                    record[2]
                );
                assert!(record[3..9].iter().all(|value| (0.0..=1.0).contains(value)));
                assert!(record[9] == 0.0 || record[9] == 1.0);

                let target = colorchecker_scene_target(COLORCHECKER_LAB_D50[index]);
                let rendered = transform_from_acescg(profile, target);
                let (_, chroma, hue, j_hk) = attributes(m, rendered);
                let expected_saturation = 100.0 * HK_COEFFICIENT * chroma / (j_hk * j_hk);
                assert!((record[0] - hue.rem_euclid(360.0)).abs() < 2.0e-8);
                assert!((record[1] - expected_saturation).abs() < 2.0e-8);
                let expected_refl = solve_neutral_reflectance_for_j_hk(m, profile, j_hk).0;
                assert!((record[2] - expected_refl).abs() < 2.0e-8);
                let expected_p3 = display_xyz_f64(rendered, &XYZ_TO_P3);
                let expected_srgb = display_xyz_f64(rendered, &XYZ_TO_REC709);
                for channel in 0..3 {
                    assert!((record[3 + channel] - expected_p3[channel]).abs() < 2.0e-12);
                    assert!((record[6 + channel] - expected_srgb[channel]).abs() < 2.0e-12);
                }
            }
        }
    }

    #[test]
    fn official_post_2014_reference_matches_active_patch_subset() {
        let source =
            include_str!("../references/colorchecker/ColorChecker24_After_Nov2014.txt");
        let mut in_data = false;
        let mut records = Vec::new();
        for line in source.lines() {
            let line = line.trim();
            if line == "BEGIN_DATA" {
                in_data = true;
                continue;
            }
            if line == "END_DATA" {
                break;
            }
            if !in_data || line.is_empty() {
                continue;
            }
            let fields: Vec<_> = line.split_whitespace().collect();
            assert_eq!(fields.len(), 4, "unexpected reference row: {line}");
            let parse = |value: &str| value.replace(',', ".").parse::<f64>().unwrap();
            records.push((
                fields[0],
                [parse(fields[1]), parse(fields[2]), parse(fields[3])],
            ));
        }
        assert_eq!(records.len(), 24);
        for (index, (_, official)) in records.iter().enumerate() {
            assert_eq!(
                *official, COLORCHECKER24_LAB_D50[index],
                "source record {index}"
            );
        }

        let active_names = [
            "A1", "B1", "C1", "D1", "E1", "F1", "A2", "B2", "C2", "D2", "E2", "F2", "A3", "B3",
            "C3", "D3", "E3", "F3",
        ];
        for (index, name) in active_names.into_iter().enumerate() {
            let (_, official) = records.iter().find(|record| record.0 == name).unwrap();
            assert_eq!(*official, COLORCHECKER_LAB_D50[index], "patch {name}");
        }
        for neutral in ["A4", "B4", "C4", "D4", "E4", "F4"] {
            assert!(records.iter().any(|record| record.0 == neutral));
            assert!(!active_names.contains(&neutral));
        }
    }

    #[test]
    fn colorchecker_uses_direct_cat02_d50_to_aces_white() {
        let xyz_d50 = lab_d50_to_xyz([100.0, 0.0, 0.0]);
        let acescg = mat(&XYZ_D50_TO_ACESCG, xyz_d50);
        for channel in acescg {
            assert!((channel - 1.0).abs() < 2.0e-12, "neutral channel={channel}");
        }
    }

    #[test]
    fn colorchecker_target_is_direct_acescg_without_ricd_or_hdr_gain() {
        let lab = COLORCHECKER_LAB_D50[0];
        let direct = mat(&XYZ_D50_TO_ACESCG, lab_d50_to_xyz(lab));
        assert_eq!(colorchecker_scene_target(lab), direct);
    }

    #[test]
    fn absolute_reference_coordinates_reconstruct_a_reachable_target() {
        let m = model();
        let target = [0.3, 0.4, 0.5];
        for profile in [0, 1, 2, 4] {
            let record = colorchecker_record_from_acescg(m, profile, target);
            assert!(record[..9].iter().all(|value| value.is_finite()));
            let rendered = transform_from_acescg(profile, target);
            let source_rgb = xyz_to_source(profile, rendered);
            if !source_cone_valid(profile, source_rgb, rendered) {
                assert_eq!(record[9], 0.0);
                continue;
            }
            let expected_refl =
                solve_neutral_reflectance_for_j_hk(m, profile, attributes(m, rendered).3).0;
            assert!((record[2] - expected_refl).abs() < 2.0e-8);
        }
    }

    #[test]
    fn colorchecker_references_keep_visible_forward_colors() {
        let points = colorchecker_points(0);
        assert!(points.chunks_exact(10).all(|record| {
            (record[9] == 0.0 || record[9] == 1.0)
                && record[..9].iter().all(|value| value.is_finite())
                && record[3..9].iter().any(|value| *value > 0.0)
        }));
    }

    #[test]
    fn center_pixel_is_valid_black_or_neutral() {
        let center_row = HEIGHT / 2;
        let bytes = render_rows(0, 0.5, (center_row - 1) as u32, (center_row + 1) as u32);
        let center = (WIDTH + WIDTH / 2) * 4;
        assert_eq!(bytes.len(), 2 * WIDTH * 4);
        assert!(bytes[center..center + 3].iter().any(|value| *value > 0));
    }

    #[test]
    fn rendered_rows_change_with_reflectance() {
        let center_row = HEIGHT / 2;
        let dark = render_rows(0, 0.2, (center_row - 1) as u32, (center_row + 1) as u32);
        let light = render_rows(0, 0.8, (center_row - 1) as u32, (center_row + 1) as u32);
        assert_ne!(dark, light);
    }

    #[test]
    fn scaled_render_rows_use_requested_dimensions() {
        let full = render_rows_scaled(0, 0.5, 64, 64, 0, 64);
        let partial = render_rows_scaled_srgb(1, 0.5, 64, 64, 31, 33);
        assert_eq!(full.len(), 64 * 64 * 4);
        assert_eq!(partial.len(), 2 * 64 * 4);
    }

    #[test]
    fn evaluate_reports_display_p3_and_srgb_encodings() {
        let values = evaluate(0, 0.5, 120.0, 30.0);
        assert_eq!(values.len(), 24);
        assert!(values[8..11]
            .iter()
            .zip(values[14..17].iter())
            .any(|(p3, srgb)| (p3 - srgb).abs() > 1.0e-4));
    }

    #[test]
    fn preview_uses_source_color_across_profiles() {
        // The same Refl/Hue/Sat controls describe different source colors when
        // the source gamut and inverse view profile change.
        let hdr = evaluate(0, 0.25, 120.0, 30.0);
        let sdr = evaluate(1, 0.25, 120.0, 30.0);
        assert!(hdr[0] > 0.5 && sdr[0] > 0.5);
        assert!(hdr[2..5]
            .iter()
            .zip(sdr[2..5].iter())
            .any(|(left, right)| (left - right).abs() > 1.0e-3));
        assert!(hdr[8..11]
            .iter()
            .zip(sdr[8..11].iter())
            .any(|(left, right)| (left - right).abs() > 1.0e-3));
        assert!(hdr[14..17]
            .iter()
            .zip(sdr[14..17].iter())
            .any(|(left, right)| (left - right).abs() > 1.0e-3));
    }

    #[test]
    fn unavailable_render_pixels_are_black() {
        // A non-finite requested ACEScg neutral is unavailable.
        let center_row = HEIGHT / 2;
        let bytes = render_rows_srgb(
            1,
            f64::NAN,
            (center_row - 1) as u32,
            (center_row + 1) as u32,
        );
        let center = (WIDTH + WIDTH / 2) * 4;
        assert_eq!(&bytes[center..center + 4], &[0, 0, 0, 255]);
    }

    #[test]
    fn acescg_srgb_set_round_trips_to_slider_coordinates() {
        let values = evaluate(0, 0.5, 120.0, 30.0);
        let set = set_from_acescg_srgb(0, values[20], values[21], values[22]);
        assert_eq!(set.len(), 4);
        assert!(set[0] > 0.5);
        let m = model();
        let target = [
            decode_srgb(values[20]),
            decode_srgb(values[21]),
            decode_srgb(values[22]),
        ];
        let rendered = transform_from_acescg(0, target);
        let expected_refl = solve_neutral_reflectance_for_j_hk(m, 0, attributes(m, rendered).3).0;
        assert!((set[1] - expected_refl).abs() < 1.0e-4);
        assert!((set[2] - 120.0).abs() < 1.0e-4);
        assert!((set[3] - 30.0).abs() < 1.0e-4);
    }

    #[test]
    fn profile_conversion_coordinates_solve_target_refl() {
        let source = evaluate(2, 0.5, 120.0, 30.0);
        assert!(source[0] > 0.5);
        let m = model();
        let acescg = [
            decode_srgb(source[20]),
            decode_srgb(source[21]),
            decode_srgb(source[22]),
        ];

        for profile in [0, 1, 2, 4] {
            let coordinates =
                set_profile_from_acescg_srgb(profile, 0.5, source[20], source[21], source[22]);
            let rendered = transform_from_acescg(profile, acescg);
            let expected =
                solve_neutral_reflectance_for_j_hk(m, profile, attributes(m, rendered).3).0;
            assert!(
                (coordinates[1] - expected).abs() < 1.0e-6,
                "profile={profile}"
            );
            assert!(coordinates[2].is_finite() && coordinates[3].is_finite());
        }
    }

    #[test]
    fn profile_conversion_uses_finite_boundary_for_unreachable_j_hk() {
        let mut found = false;
        'states: for source_profile in [0, 1, 2, 4] {
            for reflectance in [0.2, 0.5, 0.8, 1.0] {
                for hue in (0..360).step_by(15) {
                    for saturation in [15.0, 30.0, 50.0, 75.0, 100.0] {
                        let source = evaluate(source_profile, reflectance, hue as f64, saturation);
                        if source[0] <= 0.5 {
                            continue;
                        }
                        for target_profile in [0, 1, 2, 4] {
                            let coordinates = set_profile_from_acescg_srgb(
                                target_profile,
                                reflectance,
                                source[20],
                                source[21],
                                source[22],
                            );
                            assert!(coordinates[1].is_finite());
                            assert!((0.0..=REFLECTANCE_MAX).contains(&coordinates[1]));
                            assert!(coordinates[2].is_finite() && coordinates[3].is_finite());
                            if coordinates[0] <= 0.5 {
                                assert!(coordinates[1] == 0.0 || coordinates[1] == REFLECTANCE_MAX);
                                found = true;
                                break 'states;
                            }
                        }
                    }
                }
            }
        }
        assert!(found, "test state should exercise an unreachable target");
    }

    #[test]
    fn normalized_jhk_neutral_and_disk_contract() {
        for profile in [0, 1, 2, 3, 4] {
            let values = evaluate_normalized(profile, 0.3, 0.5, 0.5, 0.2);
            assert!(values.len() >= 23, "profile={profile}");
            assert!(
                values[1..4].iter().all(|value| value.is_finite()),
                "profile={profile}"
            );
            let invalid = evaluate_normalized(profile, 0.3, 1.0, 1.0, 0.2);
            assert!(invalid[0] <= 0.5, "profile={profile}");
        }
    }

    #[test]
    fn normalized_j_anchors_match_the_reference_context() {
        for profile in [0, 1, 2, 3, 4] {
            assert_eq!(normalized_j_scale(profile), J_HK_PEAK);
            assert!((normalized_model(profile).cam_z - (1.48 + 0.10_f64.sqrt())).abs() < 1.0e-15);
        }
        assert!((100.0 / J_HK_PEAK - 0.5442211759507979).abs() < 1.0e-15);
    }

    #[test]
    fn normalized_fitted_radius_round_trips_and_stays_fixed_as_j_changes() {
        for profile in [0, 1, 2, 3, 4] {
            for j in [0.15, 0.35, 0.7] {
                let expected = [j, 0.54, 0.47];
                let sample = normalized_sample(profile, expected);
                let (actual, domain_valid) = normalized_jhk_from_xyz(profile, sample.xyz);
                assert!(domain_valid, "profile={profile}, j={j}");
                for index in 0..3 {
                    assert!((actual[index] - expected[index]).abs() < 2.0e-7);
                }
            }
        }
    }

    #[test]
    fn normalized_fitted_radius_matches_shader_encoding() {
        let code = [0.3, 0.57, 0.46];
        let (j_hk, chroma, hue) = decode_normalized_jhk(3, code).expect("valid fitted radius");
        let radius = (2.0 * code[1] - 1.0).hypot(2.0 * code[2] - 1.0);
        let saturation = FITTED_RADIUS_K * (FITTED_RADIUS_D * radius).exp_m1();
        let u = (0.007 / SURROUND_C) * saturation;
        let expected_j_a = j_hk * j_hk / (j_hk.hypot(33.0 * u) + 33.0 * u);
        assert!((chroma - u * expected_j_a).abs() < 1.0e-12);
        assert!(
            (hue - (-(2.0 * code[1] - 1.0))
                .atan2(2.0 * code[2] - 1.0)
                .to_degrees()
                .rem_euclid(360.0))
            .abs()
                < 1.0e-12
        );

        let sample = normalized_sample(3, code);
        assert!(sample.valid);
        let (encoded, valid) = normalized_jhk_from_xyz(3, sample.xyz);
        assert!(valid);
        for index in 0..3 {
            assert!(
                (encoded[index] - code[index]).abs() < 2.0e-7,
                "channel={index}"
            );
        }
    }

    #[test]
    fn fitted_radius_unit_boundary_contains_rec2020_blue_endpoint() {
        let saturation = FITTED_RADIUS_K * FITTED_RADIUS_D.exp_m1();
        assert!((saturation - 203.64174424420062).abs() < 1.0e-12);
        let radius = (1.0 + saturation / FITTED_RADIUS_K).ln() / FITTED_RADIUS_D;
        assert!((radius - 1.0).abs() < 1.0e-15);
    }

    #[test]
    fn normalized_hdr_xyz_scale_matches_sdr_reference_scale() {
        let code = [0.3, 0.54, 0.47];
        let sdr = normalized_sample(1, code);
        let hdr = normalized_sample(2, code);
        for channel in 0..3 {
            assert!(
                (hdr.xyz[channel] - sdr.xyz[channel]).abs() < 1.0e-12
            );
        }
    }

    #[test]
    fn normalized_unit_disk_includes_its_axis_boundary() {
        assert!(decode_normalized_jhk(3, [0.3, 1.0, 0.5]).is_some());
        assert!(decode_normalized_jhk(3, [0.3, 0.5, 0.0]).is_some());
        assert!(decode_normalized_jhk(3, [0.3, 1.0, 1.0]).is_none());
        assert!(decode_normalized_jhk(3, [0.3, f64::NAN, 0.5]).is_none());
    }

    #[test]
    fn normalized_coordinates_round_trip_direct_workflow() {
        let values = evaluate_normalized(3, 0.3, 0.62, 0.47, 0.2);
        assert!(values[0] > 0.5);
        let xyz = source_to_xyz(3, [values[1], values[2], values[3]]);
        let coordinates = normalized_coordinates_from_xyz(3, xyz);
        assert!(coordinates[0] > 0.5);
        for index in 1..4 {
            assert!((coordinates[index] - [0.3, 0.62, 0.47][index - 1]).abs() < 2.0e-4);
        }
    }

    #[test]
    fn normalized_profile_conversion_retains_canonical_value() {
        let retained = [0.12, 0.23, 0.34];
        for source in [0, 1, 2, 4] {
            for target in [0, 1, 2, 4] {
                let converted = convert_normalized_profile(
                    source,
                    target,
                    retained[0],
                    retained[1],
                    retained[2],
                );
                assert!(converted.len() >= 7);
                for index in 4..7 {
                    assert!((converted[index] - retained[index - 4]).abs() < 1.0e-12);
                }
                assert!(converted[1..4].iter().all(|value| value.is_finite()));
            }
        }
    }

    #[test]
    fn normalized_direct_bridge_round_trips_through_the_rec709_sdr_view() {
        let acescg = [0.08, 0.12, 0.18];
        let direct = convert_normalized_profile(1, 3, acescg[0], acescg[1], acescg[2]);
        assert_eq!(direct.len(), 7);
        let restored = convert_normalized_profile(3, 4, direct[4], direct[5], direct[6]);
        assert_eq!(restored.len(), 7);
        for index in 0..3 {
            assert!((restored[index + 4] - acescg[index]).abs() < 3.0e-5);
        }
    }

    #[test]
    fn normalized_unavailable_conversion_keeps_finite_boundary_coordinates() {
        let converted = convert_normalized_profile(1, 0, 20.0, 0.05, 0.05);
        assert_eq!(converted.len(), 7);
        assert!(converted[1..4].iter().all(|value| value.is_finite()));
        assert!(converted[1..4]
            .iter()
            .all(|value| (0.0..=1.0).contains(value)));
    }

    #[test]
    fn normalized_colorchecker_records_are_bounded() {
        for profile in [0, 1, 2, 3, 4] {
            let points = colorchecker_points_normalized(profile);
            assert_eq!(points.len(), COLORCHECKER_LAB_D50.len() * 10);
            for record in points.chunks_exact(10) {
                assert!(record[..3].iter().all(|value| (0.0..=1.0).contains(value)));
            }
        }
    }

    #[test]
    fn normalized_cone_accepts_positive_values_above_one() {
        for profile in [0, 1, 2, 3, 4] {
            let source = [1.25, 0.4, 0.2];
            let xyz = source_to_xyz(profile, source);
            assert!(
                normalized_cone_valid(profile, source, xyz),
                "profile={profile}"
            );
        }
    }

    #[test]
    fn normalized_cone_rejects_negative_target_channels() {
        for profile in [0, 1, 2, 3, 4] {
            for channel in 0..3 {
                let mut source = [0.2, 0.3, 0.4];
                source[channel] = -1.0e-4;
                let xyz = source_to_xyz(profile, source);
                assert!(
                    !normalized_cone_valid(profile, source, xyz),
                    "profile={profile}, channel={channel}"
                );
            }
        }
    }

    #[test]
    fn normalized_rec2020_profile_is_p3_d65_limited() {
        let rec2020_red_xyz = [0.636958048301291, 0.262700212011267, 0.0];
        let p3 = xyz_to_source(0, rec2020_red_xyz);
        assert!(min3(p3) < 0.0);
        assert!(!normalized_cone_valid(0, p3, rec2020_red_xyz));

        let p3_white_xyz = source_to_xyz(0, [1.25, 1.25, 1.25]);
        assert!(min3(mat(&XYZ_TO_REC2020, p3_white_xyz)) >= -1.0e-8);
        assert!(normalized_cone_valid(0, [1.25, 1.25, 1.25], p3_white_xyz));
    }

    #[test]
    fn normalized_background_conversion_preserves_foreground_offset() {
        for source in [0, 1, 2, 3, 4] {
            for target in [0, 1, 2, 3, 4] {
                let source_j = 0.2;
                let target_j = 0.25;
                let background = 0.15;
                let source_foreground = source_j * normalized_j_scale(source);
                let target_foreground = target_j * normalized_j_scale(target);
                let source_background =
                    output_neutral_j_hk(normalized_model(source), source, background);
                let target_value = target_foreground + source_background - source_foreground;
                let (expected_value, expected_exact) =
                    solve_output_neutral_for_j_hk(normalized_model(target), target, target_value);
                let converted =
                    convert_normalized_background(source, target, background, source_j, target_j);
                assert_eq!(
                    converted[0] > 0.5,
                    expected_exact,
                    "source={source}, target={target}"
                );
                assert!((converted[1] - expected_value).abs() < 1.0e-12);
            }
        }
    }

    #[test]
    fn profile_conversion_matches_absolute_reference_hue_and_saturation() {
        let m = model();
        for profile in [0, 1, 2, 4] {
            for lab in COLORCHECKER_LAB_D50 {
                let target = colorchecker_scene_target(lab);
                let rendered = transform_from_acescg(profile, target);
                let coordinates = coordinates_from_rendered_xyz(m, profile, None, rendered);
                let reference = colorchecker_record_from_acescg(m, profile, target);
                assert!((coordinates[1] - reference[2]).abs() < 2.0e-8);
                assert!((coordinates[2] - reference[0]).abs() < 2.0e-8);
                assert!((coordinates[3] - reference[1]).abs() < 2.0e-8);
            }
        }
    }

    #[test]
    fn background_snap_is_the_forward_view_neutral() {
        for profile in [0, 1, 2, 4] {
            let values = evaluate(profile, 0.5, 120.0, 30.0);
            let expected = forward_acescg_neutral(profile, 0.5).expect("neutral view output");
            assert!((values[23] - expected).abs() < 1.0e-12);
        }
    }

    #[test]
    fn background_profile_conversion_uses_exact_transforms() {
        for source_neutral in [0.0, 0.5, 1.0] {
            for source_profile in [0, 1, 2, 3, 4] {
                for target_profile in [0, 1, 2, 3, 4] {
                    let converted =
                        convert_neutral_profile(source_profile, target_profile, source_neutral);
                    assert!(converted[0] > 0.5);
                    let expected = if source_profile == target_profile {
                        source_neutral
                    } else {
                        let source_xyz = source_to_xyz(source_profile, [source_neutral; 3]);
                        let acescg = if source_profile == 3 {
                            srgb_to_acescg([source_neutral; 3])
                        } else {
                            transform_to_acescg(source_profile, source_xyz)
                        };
                        let target_xyz = if target_profile == 3 {
                            acescg_to_srgb_xyz(acescg)
                        } else {
                            transform_from_acescg(target_profile, acescg)
                        };
                        neutral_scalar(xyz_to_source(target_profile, target_xyz))
                            .expect("neutral target")
                    };
                    assert!((converted[1] - expected.clamp(0.0, BACKGROUND_MAX)).abs() < 1.0e-12);
                }
            }
        }
    }

    #[test]
    fn background_conversion_tracks_target_foreground_snap_point() {
        let light_skin = &colorchecker_points(3)[10..13];
        let source = evaluate(3, light_skin[2], light_skin[0], light_skin[1]);
        let target_coordinates = set_profile_from_output_srgb_converted(
            2,
            light_skin[2],
            source[14],
            source[15],
            source[16],
        );
        let target = evaluate(
            2,
            target_coordinates[1],
            target_coordinates[2],
            target_coordinates[3],
        );
        let converted = convert_background_profile(
            3,
            2,
            source[23],
            light_skin[2],
            source[14],
            source[15],
            source[16],
        );
        assert!(converted[0] > 0.5);
        assert!((converted[1] - target[23]).abs() < 2.0e-5);
    }

    #[test]
    fn background_conversion_accepts_zero_boundary() {
        let source = evaluate(
            3,
            0.14775534710139587,
            39.25784549124876,
            26.203829648600536,
        );
        for profile in [0, 1, 2, 3, 4] {
            let converted = convert_background_profile(
                3,
                profile,
                0.0,
                0.14775534710139587,
                source[14],
                source[15],
                source[16],
            );
            assert!(converted[0] > 0.5, "profile={profile}");
            assert!(converted[1].is_finite(), "profile={profile}");
            assert!(
                (0.0..=BACKGROUND_MAX).contains(&converted[1]),
                "profile={profile}"
            );
        }
    }

    #[test]
    fn maximum_saturation_is_bounded() {
        let value = maximum_saturation(0, 0.5, 120.0);
        assert!(value.is_finite());
        assert!((0.0..=100.0).contains(&value));
    }

    #[test]
    fn rec709_profile_uses_its_source_matrix_and_transform() {
        let p3 = evaluate(0, 0.2, 120.0, 10.0);
        let rec709 = evaluate(1, 0.2, 120.0, 10.0);
        assert_eq!(rec709.len(), 24);
        assert!(p3[2..5]
            .iter()
            .zip(rec709[2..5].iter())
            .any(|(left, right)| (left - right).abs() > 1.0e-4));
        assert!(rec709[5..8].iter().all(|value| value.is_finite()));
    }

    #[test]
    fn rec709_neutral_uses_exact_aces2_forward_inverse() {
        let values = evaluate(1, 0.456, 0.0, 0.0);
        assert!(values[0] > 0.5);
        for value in &values[2..5] {
            assert!((*value - 0.456).abs() < 2.0e-5, "ACEScg channel={value}");
        }
        let set = set_from_acescg_srgb(1, values[20], values[21], values[22]);
        assert!(set[0] > 0.5);
        assert!((set[1] - 0.456).abs() < 1.0e-4);
        assert!(set[3].abs() < 1.0e-4);
    }

    #[test]
    fn rec2020_limited_profile_enforces_source_cone() {
        let xyz = mat(&P3_TO_XYZ, [1.0, 0.0, 0.0]);
        let p3_rgb = mat(&XYZ_TO_P3, xyz);
        let rec2020_rgb = mat(&XYZ_TO_REC2020, xyz);
        assert!(min3(p3_rgb) >= -1.0e-6);
        assert!(min3(rec2020_rgb) < -1.0e-6);
        assert!(!source_cone_valid(0, p3_rgb, xyz));
        assert!(source_cone_valid(2, p3_rgb, xyz));
    }

    #[test]
    fn hdr_profiles_have_stable_source_limits_at_neutral_hue() {
        let p3_max = maximum_saturation(2, 0.5, 0.0);
        let rec2020_max = maximum_saturation(0, 0.5, 0.0);
        assert!(p3_max.is_finite() && rec2020_max.is_finite());
        assert!((p3_max - rec2020_max).abs() < 5.0e-4);
    }

    #[test]
    fn direct_srgb_profile_is_one_to_one_for_neutral_output() {
        let values = evaluate(3, 0.5, 0.0, 0.0);
        assert!(values[0] > 0.5);
        assert!(values[5..8]
            .iter()
            .all(|value| (*value - 0.5).abs() < 2.0e-6));
        assert!(values[2..5]
            .iter()
            .all(|value| (*value - 0.5).abs() < 2.0e-6));
        let encoded = encode_display_rgb([0.5; 3]);
        for (actual, expected) in values[14..17].iter().zip(encoded) {
            assert!((*actual - expected).abs() < 2.0e-6);
        }
        let set = set_from_output_srgb(3, encoded[0], encoded[1], encoded[2]);
        assert!(set[0] > 0.5);
        assert!((set[1] - 0.5).abs() < 2.0e-5);
        assert!(set[3].abs() < 2.0e-5);
    }

    #[test]
    fn direct_srgb_profile_clamps_out_of_cube_samples() {
        let values = evaluate(3, 0.5, 0.0, 100.0);
        assert!(values[14..17]
            .iter()
            .all(|value| (0.0..=1.0).contains(value)));
        let set = set_profile_from_output_srgb(3, values[14], values[15], values[16]);
        assert!(set[0] > 0.5);
        assert!((0.0..=100.0).contains(&set[3]));
    }

    #[test]
    fn aces_profile_conversion_solves_coordinates_for_same_acescg_value() {
        let source = evaluate(2, 0.5, 120.0, 10.0);
        let coordinates =
            set_profile_from_acescg_srgb_converted(1, 0.5, source[20], source[21], source[22]);
        assert!(coordinates[0] > 0.5);
        assert!((coordinates[1] - 0.5269).abs() < 0.01);
        let target = evaluate(1, coordinates[1], coordinates[2], coordinates[3]);
        for channel in 0..3 {
            assert!((target[2 + channel] - source[2 + channel]).abs() < 4.0e-4);
        }
    }

    #[test]
    fn profile_conversion_accepts_a_representable_neutral_state() {
        let source = evaluate(2, 0.5, 0.0, 0.0);
        let coordinates =
            set_profile_from_acescg_srgb_converted(1, 0.5, source[20], source[21], source[22]);
        assert!(coordinates[0] > 0.5);
        assert!((coordinates[1] - 0.5).abs() < 1.0e-3);
        assert!(coordinates[3].abs() < 1.0e-5);
    }

    #[test]
    fn direct_srgb_refl_is_the_linear_srgb_neutral_j_hk_target() {
        let m = model();
        for reflectance in [0.05, 0.5, 1.0] {
            let expected = attributes(m, source_to_xyz(3, [reflectance; 3])).3;
            assert!((neutral_j_hk(m, 3, reflectance) - expected).abs() < 1.0e-12);
            let values = evaluate(3, reflectance, 127.0, 0.0);
            assert!(values[0] > 0.5);
            for channel in &values[2..5] {
                assert!((*channel - reflectance).abs() < 2.0e-5);
            }
        }
    }

    #[test]
    fn aces_to_srgb_switch_uses_the_rec709_100nit_view() {
        // Use an in-gamut ACEScg value whose SDR-view result is visibly
        // different from a direct ACEScg-to-XYZ conversion.
        let source = [0.3, 0.4, 0.2];
        let encoded = encode_display_rgb(source);
        let coordinates =
            set_profile_from_acescg_srgb_converted(3, 0.5, encoded[0], encoded[1], encoded[2]);
        assert!(coordinates[0] > 0.5);
        let values = evaluate(3, coordinates[1], coordinates[2], coordinates[3]);
        let retained = [
            decode_srgb(encoded[0]),
            decode_srgb(encoded[1]),
            decode_srgb(encoded[2]),
        ];
        let expected_xyz = acescg_to_srgb_xyz(retained);
        let expected_rgb = xyz_to_source(3, expected_xyz);
        for channel in 0..3 {
            assert!((values[5 + channel] - expected_rgb[channel]).abs() < 2.0e-5);
        }
        let direct_xyz = mat(&ACESCG_TO_XYZ_D65, retained);
        let direct_rgb = xyz_to_source(3, direct_xyz);
        assert!(
            max3([
                (expected_rgb[0] - direct_rgb[0]).abs(),
                (expected_rgb[1] - direct_rgb[1]).abs(),
                (expected_rgb[2] - direct_rgb[2]).abs(),
            ]) > 1.0e-3
        );
    }

    #[test]
    fn srgb_to_aces_switch_uses_the_inverse_rec709_100nit_view() {
        let linear = [0.1, 0.2, 0.3];
        let encoded = encode_display_rgb(linear);
        let acescg = srgb_to_acescg(linear);
        for profile in [0, 1, 2, 4] {
            let coordinates = set_profile_from_output_srgb_converted(
                profile, 0.5, encoded[0], encoded[1], encoded[2],
            );
            assert!(coordinates[0] > 0.5, "profile={profile}");
            let values = evaluate(profile, coordinates[1], coordinates[2], coordinates[3]);
            let expected_xyz = transform_from_acescg(profile, acescg);
            let expected_rgb = xyz_to_source(profile, expected_xyz);
            for channel in 0..3 {
                assert!(
                    (values[5 + channel] - expected_rgb[channel]).abs() < 2.0e-5,
                    "profile={profile} channel={channel}"
                );
            }
        }
    }

    #[test]
    fn srgb_to_aces_switch_reports_out_of_range_readout_as_unavailable() {
        // Neutral 0.5 linear sRGB maps above the ACEScg unit cube through the
        // inverse Rec.709 view. The profile switch still returns finite
        // boundary slider values, while evaluation exposes its unavailable
        // state and clamps the readout to the unit interval.
        let encoded = encode_display_rgb([0.5; 3]);
        for profile in [0, 1, 2, 4] {
            let coordinates = set_profile_from_output_srgb_converted(
                profile, 0.5, encoded[0], encoded[1], encoded[2],
            );
            assert!(coordinates[1..4].iter().all(|value| value.is_finite()));
            assert!((0.0..=REFLECTANCE_MAX).contains(&coordinates[1]));
            assert!((0.0..=360.0).contains(&coordinates[2]));
            assert!((0.0..=100.0).contains(&coordinates[3]));
            assert!(coordinates[0] <= 0.5, "profile={profile}");
            let values = evaluate(profile, coordinates[1], coordinates[2], coordinates[3]);
            assert!(values[0] <= 0.5, "profile={profile}");
            assert!(values[2..5]
                .iter()
                .all(|value| value.is_finite() && (0.0..=1.0).contains(value)));
        }
    }

    #[test]
    fn linear_readouts_are_unit_bounded_when_colors_are_unavailable() {
        let direct = evaluate(3, REFLECTANCE_MAX, 0.0, 0.0);
        assert!(direct[0] <= 0.5);
        assert!(direct[2..5]
            .iter()
            .all(|value| value.is_finite() && (0.0..=1.0).contains(value)));
        for profile in [0, 1, 2, 4] {
            let values = evaluate(profile, REFLECTANCE_MAX, 0.0, 0.0);
            assert!(values[0] <= 0.5, "profile={profile}");
            assert!(values[2..5]
                .iter()
                .all(|value| value.is_finite() && (0.0..=1.0).contains(value)));
        }
    }

    #[test]
    fn p3_hdr_inverse_regression_vector() {
        let acescg = transform_to_acescg(2, [0.1, 0.1, 0.1]);
        let expected = [0.14822204, 0.13269136, 0.12742696];
        for (actual, reference) in acescg.iter().zip(expected.iter()) {
            assert!(
                (actual - reference).abs() < 2.0e-6,
                "actual={actual}, reference={reference}"
            );
        }
    }

    #[test]
    fn p3_sdr_forward_and_inverse_regression_vectors() {
        let xyz = transform_from_acescg(4, [0.1, 0.2, 0.3]);
        let expected_xyz = [0.076201893, 0.098404169, 0.190585598];
        for (actual, reference) in xyz.iter().zip(expected_xyz.iter()) {
            assert!(
                (actual - reference).abs() < 2.0e-6,
                "actual={actual}, reference={reference}"
            );
        }

        // The inverse processor consumes display-referred XYZ-D65 directly.
        // Passing XYZ_TO_P3 * xyz here would convert the value a second time
        // and compare against a different (P3 RGB-shaped) input domain.
        let acescg = transform_to_acescg(4, [0.2, 0.3, 0.4]);
        let expected_acescg = [0.2197569157, 0.6639465161, 0.6819892161];
        for (actual, reference) in acescg.iter().zip(expected_acescg.iter()) {
            assert!(
                (actual - reference).abs() < 2.0e-6,
                "actual={actual}, reference={reference}"
            );
        }
    }

    #[test]
    fn p3_sdr_uses_p3_source_gamut_and_profile_local_neutral() {
        let m = model();
        let white = transform_from_acescg(4, [0.5; 3]);
        assert!(source_cone_valid(4, xyz_to_source(4, white), white));
        let j_hk = neutral_j_hk(m, 4, 0.5);
        let (refl, exact) = solve_neutral_reflectance_for_j_hk(m, 4, j_hk);
        assert!(exact);
        assert!((refl - 0.5).abs() < 2.0e-5);
        let values = evaluate(4, 0.5, 120.0, 30.0);
        assert!(values[0] > 0.5);
        assert!(values[2..5].iter().all(|value| value.is_finite()));
    }
}

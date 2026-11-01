//! Fixed HDR-Rec.2020 authoring. View IDs affect presentation only.
//! Normalized Cartesian picker exports coexist with the profile helpers in
//! lib.rs for the public WASM surface.
use super::*;

const HDR203_DIFFUSE_WHITE_SCALE: f64 = 2.03;
const AUTHORING_REC2020_PEAK: f64 = 10.0 / HDR203_DIFFUSE_WHITE_SCALE;
const SOURCE_BACKGROUND_MAX: f64 = 1.0;
// modCAM16-HK of neutral source Rec.2020 = 1000/203, independently checked in Python.
const PICKER_J_PEAK: f64 = 217.2768649129496;
fn source_valid(rgb: [f64; 3]) -> bool {
    finite3(rgb) && min3(rgb) >= -1.0e-8 && max3(rgb) <= AUTHORING_REC2020_PEAK + 1.0e-7
}

fn rec2020_authored_valid(xyz: [f64; 3], full_rec2020: bool) -> bool {
    let rec2020 = mat(&XYZ_TO_REC2020, xyz);
    let p3 = mat(&XYZ_TO_P3, xyz);
    source_valid(rec2020) && (full_rec2020 || source_valid(p3))
}

fn source_valid_with_peak(rgb: [f64; 3], peak: f64) -> bool {
    // Prepared rasters are f32 and may have passed through a 16-bit PQ
    // round-trip plus two color-space matrices. Allow the resulting few ulps
    // of upper-bound overshoot while still rejecting negative or genuinely
    // above-peak source values.
    finite3(rgb) && min3(rgb) >= -1.0e-8 && max3(rgb) <= peak + 5.0e-5
}

fn source_sample_mode(code: [f64; 3], full_rec2020: bool) -> Sample {
    let xyz = match decode_scaled_jhk(code, PICKER_J_PEAK) {
        Some((j, c, h)) => modcam_to_xyz(normalized_model(2), j, c, h),
        None => [f64::NAN; 3],
    };
    let source_rgb = mat(&XYZ_TO_REC2020, xyz);
    let valid = finite3(xyz) && rec2020_authored_valid(xyz, full_rec2020);
    // Never present a clipped inverse as the scene value of an invalid pick.
    let acescg = if valid {
        aces_output::inverse_from_xyz_d65(0, xyz)
    } else {
        [f64::NAN; 3]
    };
    Sample {
        xyz,
        source_rgb,
        acescg,
        valid: valid && finite3(acescg),
    }
}

#[cfg(test)]
fn source_sample(code: [f64; 3]) -> Sample {
    source_sample_mode(code, true)
}

fn view_rgb(view: u32, acescg: [f64; 3]) -> [f64; 3] {
    let matrix = match view {
        0 => &XYZ_TO_REC2020,
        2 | 4 => &XYZ_TO_P3,
        _ => &XYZ_TO_REC709,
    };
    // OCIO view XYZ is Y=1 at 100 nits, including HDR views.
    mat(matrix, aces_output::forward(view, acescg))
}

fn neutral_source(j: f64) -> f64 {
    let xyz = modcam_to_xyz(normalized_model(2), j * PICKER_J_PEAK, 0.0, 0.0);
    xyz[1].clamp(0.0, AUTHORING_REC2020_PEAK)
}

/// Layout (all floating point):
/// 0 valid; 1..3 canonical ACEScg; 4..6 source-preview display P3;
/// 7..9 source-preview sRGB; 10..12 sRGB-transfer-encoded AP1;
/// 13..18 reserved; 19 foreground-matching normalized J';
/// 20..22 Rec.2020-authored J'/x'/y'; 23..25 linear Rec.2020 authoring values
/// (reference-white units, where 1.0 is 203 nits);
/// 26..28 picked view linear RGB (HDR reference-white units);
/// 29..31 surround view linear RGB (HDR reference-white units); 32 reserved.
#[wasm_bindgen]
pub fn picker_evaluate_mode(
    view: u32,
    j: f64,
    x: f64,
    y: f64,
    background_j: f64,
    full_rec2020: bool,
) -> Vec<f64> {
    let sample = source_sample_mode([j, x, y], full_rec2020);
    let requested_background_j = if background_j.is_finite() {
        background_j.clamp(0.0, SOURCE_BACKGROUND_MAX)
    } else {
        0.0
    };
    let background_source = neutral_source(requested_background_j);
    let background_xyz = mat(&REC2020_TO_XYZ, [background_source; 3]);
    let background_scene = aces_output::inverse_from_xyz_d65(0, background_xyz);
    let mut out = vec![if sample.valid { 1.0 } else { 0.0 }];
    out.extend(sample.acescg);
    out.extend(display_xyz_f64(sample.xyz, &XYZ_TO_P3));
    out.extend(display_xyz_f64(sample.xyz, &XYZ_TO_REC709));
    out.extend(encode_extended_rgb(sample.acescg));
    out.extend([0.0; 6]);
    out.extend([j, j, x, y]);
    out.extend(sample.source_rgb);
    out.extend(if sample.valid {
        view_rgb(view, sample.acescg)
    } else {
        [0.0; 3]
    });
    out.extend(view_rgb(view, background_scene));
    out.push(0.0);
    out
}

#[wasm_bindgen]
pub fn picker_evaluate(view: u32, j: f64, x: f64, y: f64, background_j: f64) -> Vec<f64> {
    picker_evaluate_mode(view, j, x, y, background_j, true)
}

/// Import sRGB-transfer encoded AP1 and solve coordinates in fixed HDR Rec.2020.
/// The caller evaluates the solved coordinates again: they determine ACEScg.
#[wasm_bindgen]
pub fn picker_from_encoded_mode(red: f64, green: f64, blue: f64, full_rec2020: bool) -> Vec<f64> {
    let scene = [red, green, blue].map(decode_srgb);
    let xyz = aces_output::forward(0, scene);
    let (code, domain_valid) = scaled_jhk_from_xyz(xyz, PICKER_J_PEAK);
    let valid = domain_valid && rec2020_authored_valid(xyz, full_rec2020);
    vec![if valid { 1.0 } else { 0.0 }, code[0], code[1], code[2]]
}

#[wasm_bindgen]
pub fn picker_from_encoded(red: f64, green: f64, blue: f64) -> Vec<f64> {
    picker_from_encoded_mode(red, green, blue, true)
}

fn picker_analyze_xyz_d65_with_reference_white_encoded_as_linear_203_impl(
    raster_xyz: [f64; 3],
    reference_white_encoded_as_linear_203: bool,
) -> Vec<f64> {
    let source_xyz = if reference_white_encoded_as_linear_203 {
        raster_xyz.map(|v| v / HDR203_DIFFUSE_WHITE_SCALE)
    } else {
        raster_xyz
    };
    let source_rgb = mat(&XYZ_TO_REC2020, source_xyz);
    let (code, domain_valid) =
        super::scaled_jhk_from_xyz_with_tolerance(source_xyz, PICKER_J_PEAK, 1.0e-4);
    let acescg = if finite3(source_xyz)
        && source_valid_with_peak(source_rgb, AUTHORING_REC2020_PEAK)
    {
        aces_output::inverse_from_xyz_d65(0, source_xyz)
    } else {
        [f64::NAN; 3]
    };
    let valid = finite3(source_xyz)
        && finite3(acescg)
        && domain_valid
        && source_valid_with_peak(source_rgb, AUTHORING_REC2020_PEAK);
    let mut out = Vec::with_capacity(7);
    out.push(if valid { 1.0 } else { 0.0 });
    out.extend(acescg);
    out.extend(code);
    out
}

/// Analyze a prepared display-referred XYZ-D65 sample. This is the canonical
/// display-image input path; RGB sources must be adapted to XYZ-D65 before
/// reaching it, while ACEScg/AP0 remain scene-reference-only formats.
#[wasm_bindgen]
pub fn picker_analyze_xyz_d65_with_reference_white_encoded_as_linear_203(
    x: f64,
    y: f64,
    z: f64,
    reference_white_encoded_as_linear_203: bool,
) -> Vec<f64> {
    picker_analyze_xyz_d65_with_reference_white_encoded_as_linear_203_impl(
        [x, y, z],
        reference_white_encoded_as_linear_203,
    )
}

#[wasm_bindgen]
pub fn picker_analyze_xyz_d65_with_display_linear_one_as_hdr203_white(
    x: f64,
    y: f64,
    z: f64,
    reference_white_encoded_as_linear_203: bool,
) -> Vec<f64> {
    picker_analyze_xyz_d65_with_reference_white_encoded_as_linear_203(
        x,
        y,
        z,
        reference_white_encoded_as_linear_203,
    )
}

/// Analyze a prepared scene-linear ACES2065-1/AP0 sample. The AP0-to-ACEScg
/// matrix is applied directly: no display-linear multiplier, inverse view
/// transform, or RGB clamp is involved. The existing ACEScg-to-J′/x′/y′ solve
/// remains authoritative for coordinate availability.
///
/// Return layout: [valid coordinates, ACEScg R/G/B, J′, x′, y′].
#[wasm_bindgen]
pub fn picker_analyze_scene_ap0(red: f64, green: f64, blue: f64) -> Vec<f64> {
    let ap0 = [red, green, blue];
    let acescg = aces_output::ap0_to_acescg(ap0);
    let code = if finite3(ap0) && finite3(acescg) {
        let xyz = aces_output::forward_from_ap0(0, ap0);
        picker_code_from_forward_xyz(acescg, xyz)
    } else {
        vec![0.0, f64::NAN, f64::NAN, f64::NAN]
    };
    let mut out = Vec::with_capacity(7);
    out.push(code[0]);
    out.extend(acescg);
    out.extend_from_slice(&code[1..4]);
    out
}

/// Convert prepared display-referred XYZ-D65 pixels to the selected view.
#[wasm_bindgen]
pub fn picker_display_rgb_xyz_d65_batch(
    pixels: &[f32],
    view: u32,
    reference_white_encoded_as_linear_203: bool,
) -> Vec<f32> {
    if pixels.len() % 3 != 0 {
        return Vec::new();
    }
    let scale = if reference_white_encoded_as_linear_203 {
        1.0 / HDR203_DIFFUSE_WHITE_SCALE
    } else {
        1.0
    };
    let mut output = Vec::with_capacity(pixels.len());
    for pixel in pixels.chunks_exact(3) {
        let xyz = [
            pixel[0] as f64 * scale,
            pixel[1] as f64 * scale,
            pixel[2] as f64 * scale,
        ];
        let acescg = aces_output::inverse_from_xyz_d65(0, xyz);
        output.extend(view_rgb(view, acescg).into_iter().map(|v| v as f32));
    }
    output
}

/// Present prepared scene-linear ACES2065-1/AP0 through the selected forward
/// ACES view. Input scene channels are matrix-converted to ACEScg without
/// clamping before the view transform.
#[wasm_bindgen]
pub fn picker_display_rgb_scene_ap0_batch(pixels: &[f32], view: u32) -> Vec<f32> {
    if pixels.len() % 3 != 0 {
        return Vec::new();
    }
    let mut output = Vec::with_capacity(pixels.len());
    for pixel in pixels.chunks_exact(3) {
        let xyz = aces_output::forward_from_ap0(
            view,
            [pixel[0] as f64, pixel[1] as f64, pixel[2] as f64],
        );
        let matrix = match view {
            0 => &XYZ_TO_REC2020,
            2 | 4 => &XYZ_TO_P3,
            _ => &XYZ_TO_REC709,
        };
        output.extend(mat(matrix, xyz).into_iter().map(|v| v as f32));
    }
    output
}

/// Solve canonical normalized J′/x′/y′ coordinates from an averaged ACEScg
/// scene-linear colour.  Image-locator averages are intentionally performed
/// in ACEScg before this nonlinear forward solve.
#[wasm_bindgen]
pub fn picker_code_from_acescg(red: f64, green: f64, blue: f64) -> Vec<f64> {
    let acescg = [red, green, blue];
    let xyz = aces_output::forward(0, acescg);
    picker_code_from_forward_xyz(acescg, xyz)
}

fn picker_code_from_forward_xyz(acescg: [f64; 3], xyz: [f64; 3]) -> Vec<f64> {
    let source_xyz = xyz;
    let source_rgb = mat(&XYZ_TO_REC2020, source_xyz);
    let (code, domain_valid) = scaled_jhk_from_xyz(source_xyz, PICKER_J_PEAK);
    let valid = finite3(acescg) && finite3(xyz) && domain_valid && source_valid(source_rgb);
    let mut out = Vec::with_capacity(4);
    out.push(if valid { 1.0 } else { 0.0 });
    out.extend(code);
    out
}

/// Fixed source slice: view switches never alter the mask or its coordinates.
#[wasm_bindgen]
pub fn picker_render_rows(
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
    let mut output = vec![0; (end - start) * width * 4];
    for y in start..end {
        for x in 0..width {
            let sx = if width == 1 {
                0.5
            } else {
                x as f64 / (width - 1) as f64
            };
            let sy = if height == 1 {
                0.5
            } else {
                1.0 - y as f64 / (height - 1) as f64
            };
            // Raster needs source validity, not the expensive ACES inverse.
            let xyz = decode_scaled_jhk([j, sx, sy], PICKER_J_PEAK)
                .map(|(jh, c, h)| modcam_to_xyz(normalized_model(2), jh, c, h))
                .unwrap_or([f64::NAN; 3]);
            let rgb = if source_valid(mat(&XYZ_TO_REC2020, xyz)) {
                display_rgb(
                    xyz,
                    if display_p3 {
                        &XYZ_TO_P3
                    } else {
                        &XYZ_TO_REC709
                    },
                )
            } else {
                let shade = if ((x / 7) + (y / 7)) % 2 == 0 { 22 } else { 15 };
                [shade, shade + 2, shade + 5]
            };
            let offset = ((y - start) * width + x) * 4;
            output[offset..offset + 4].copy_from_slice(&[rgb[0], rgb[1], rgb[2], 255]);
        }
    }
    output
}

/// Render selected-view display-linear RGB for one Cartesian slice row range.
///
/// Each pixel is `[R, G, B, valid]`. This is the deterministic fallback for
/// the WebGPU slice renderer and follows the same fixed Rec.2020 authoring pipeline as
/// [`picker_evaluate`]: modCAM16-HK -> linear Rec.2020-D65 authoring RGB -> fixed inverse
/// fixed Rec.2020 ACES 2.0 inverse -> selected forward ACES 2.0 view.
#[wasm_bindgen]
pub fn picker_render_linear_rows_mode(
    view: u32,
    j: f64,
    width: u32,
    height: u32,
    y_start: u32,
    y_end: u32,
    full_rec2020: bool,
) -> Vec<f32> {
    let width = width.max(1) as usize;
    let height = height.max(1) as usize;
    let start = (y_start as usize).min(height);
    let end = (y_end as usize).min(height).max(start);
    let mut output = vec![0.0_f32; (end - start) * width * 4];
    for y in start..end {
        for x in 0..width {
            let sx = if width == 1 {
                0.5
            } else {
                x as f64 / (width - 1) as f64
            };
            let sy = if height == 1 {
                0.5
            } else {
                1.0 - y as f64 / (height - 1) as f64
            };
            let sample = source_sample_mode([j, sx, sy], full_rec2020);
            let index = ((y - start) * width + x) * 4;
            if sample.valid {
                let rgb = view_rgb(view, sample.acescg);
                output[index] = rgb[0] as f32;
                output[index + 1] = rgb[1] as f32;
                output[index + 2] = rgb[2] as f32;
                output[index + 3] = 1.0;
            }
        }
    }
    output
}

#[wasm_bindgen]
pub fn picker_render_linear_rows(
    view: u32,
    j: f64,
    width: u32,
    height: u32,
    y_start: u32,
    y_end: u32,
) -> Vec<f32> {
    picker_render_linear_rows_mode(view, j, width, height, y_start, y_end, true)
}

/// ACES fixed-function parameters and reach/cusp tables for the WGSL slice
/// implementation. Values originate in the checked-in official OCIO config;
/// the CPU implementation and independent OCIO oracle define its ordering.
#[wasm_bindgen]
pub fn picker_gpu_parameters() -> Vec<f32> {
    aces_output::gpu_parameter_blob()
}

/// Fixed 18 seven-float records: canonical J'/x'/y', selected-view display
/// linear RGB for the dot fill, and always-available.
#[wasm_bindgen]
pub fn picker_colorchecker_mode(view: u32) -> Vec<f64> {
    let mut output = Vec::with_capacity(126);
    for lab in COLORCHECKER_LAB_D50 {
        let scene = colorchecker_scene_target(lab);
        let xyz = aces_output::forward(0, scene);
        let (code, _domain_valid) = scaled_jhk_from_xyz(xyz, PICKER_J_PEAK);
        output.extend(code);
        output.extend(view_rgb(view, scene));
        output.push(1.0);
    }
    output
}

#[wasm_bindgen]
pub fn picker_colorchecker() -> Vec<f64> {
    let mut output = Vec::with_capacity(180);
    for lab in COLORCHECKER_LAB_D50 {
        let scene = colorchecker_scene_target(lab);
        let xyz = aces_output::forward(0, scene);
        let (code, domain_valid) = scaled_jhk_from_xyz(xyz, PICKER_J_PEAK);
        output.extend(code);
        output.extend(display_xyz_f64(xyz, &XYZ_TO_P3));
        output.extend(display_xyz_f64(xyz, &XYZ_TO_REC709));
        output.push(if domain_valid && source_valid(mat(&XYZ_TO_REC2020, xyz)) {
            1.0
        } else {
            0.0
        });
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn views_share_coordinates_scene_and_background_marker() {
        let base = picker_evaluate(2, 0.38, 0.86, 0.62, 0.15);
        for view in [0, 1, 2, 4] {
            let other = picker_evaluate(view, 0.38, 0.86, 0.62, 0.15);
            assert_eq!(&other[..26], &base[..26]);
        }
    }

    #[test]
    fn physical_white_endpoints_and_neutral_surround_match() {
        for (nits, j) in [
            (0.0, 0.0),
            (100.0, 76.02655940839014 / PICKER_J_PEAK),
            (1000.0, 1.0),
        ] {
            for view in [0, 1, 2, 4] {
                let value = picker_evaluate(view, j, 0.5, 0.5, j);
                assert_eq!(value[0], 1.0);
                for channel in 0..3 {
                    assert!((value[23 + channel] * 203.0 - nits).abs() < 1e-5);
                    assert!((value[26 + channel] - value[29 + channel]).abs() < 1e-7);
                }
            }
        }
    }

    #[test]
    fn background_j_is_normalized_and_invalid_picks_have_no_scene() {
        let zero = picker_evaluate(2, 0.3, 0.5, 0.5, 0.0);
        let peak = picker_evaluate(2, 0.3, 0.5, 0.5, 1.0);
        assert_eq!(zero[32], 0.0);
        assert_eq!(peak[32], 0.0);
        assert!(peak[29..32].iter().all(|v| v.is_finite()));
        assert!(peak[29] > zero[29]);
        let invalid = picker_evaluate(2, 0.9, 0.01, 0.01, 0.15);
        assert_eq!(invalid[0], 0.0);
        assert!(invalid[1..4].iter().all(|v| v.is_nan()));
    }

    #[test]
    fn rec2020_authoring_validity_uses_rec2020_instead_of_p3() {
        let sample = source_sample([0.12, 0.35, 0.1875]);
        let p3 = mat(&XYZ_TO_P3, sample.xyz);
        let rec2020 = mat(&XYZ_TO_REC2020, sample.xyz);
        assert!(min3(p3) < -1.0e-4, "sample should be outside P3: {p3:?}");
        assert!(
            source_valid(rec2020),
            "sample should be inside Rec.2020: {rec2020:?}"
        );
        assert!(sample.valid, "Rec.2020-valid authored sample was rejected");

        let outside = source_sample([0.2, 0.0, 0.0]);
        assert!(!source_valid(mat(&XYZ_TO_REC2020, outside.xyz)));
        assert!(
            !outside.valid,
            "Rec.2020-invalid authored sample was accepted"
        );
    }

    #[test]
    fn full_off_requires_p3_containment_for_limited_rec2020_authoring() {
        let code = [0.12, 0.35, 0.1875];
        let full = picker_evaluate_mode(0, code[0], code[1], code[2], 0.0, true);
        let restricted = picker_evaluate_mode(0, code[0], code[1], code[2], 0.0, false);
        assert_eq!(full[0], 1.0);
        assert_eq!(restricted[0], 0.0);

        let above_p3_peak = [0.624, 0.9125, 0.55];
        let sample = source_sample(above_p3_peak);
        let p3 = mat(&XYZ_TO_P3, sample.xyz);
        assert!(
            sample.valid,
            "sample must remain valid in full Rec.2020 mode"
        );
        assert!(
            min3(p3) >= 0.0 && max3(p3) > AUTHORING_REC2020_PEAK,
            "expected P3 upper-cube violation: {p3:?}"
        );
        let restricted = picker_evaluate_mode(
            0,
            above_p3_peak[0],
            above_p3_peak[1],
            above_p3_peak[2],
            0.0,
            false,
        );
        assert_eq!(restricted[0], 0.0);

        let neutral = picker_evaluate_mode(0, 0.8, 0.5, 0.5, 0.0, false);
        assert_eq!(neutral[0], 1.0);
        assert!(neutral[23..26].iter().all(|value| *value > 1.0));
    }

    #[test]
    fn colorchecker_mode_retains_every_patch() {
        let points = picker_colorchecker_mode(0);
        assert_eq!(points.len(), 18 * 7);
        assert!(points.chunks_exact(7).all(|record| {
            record[6] == 1.0
                && record[3..6].iter().all(|value| value.is_finite())
                && record[3..6].iter().any(|value| value.abs() > 1.0e-9)
        }));
    }

    #[test]
    fn image_unit_interpretation_preserves_physical_analysis() {
        let xyz = mat(&REC2020_TO_XYZ, [0.18, 0.07, 0.03]);
        let unchecked_analysis = picker_analyze_xyz_d65_with_display_linear_one_as_hdr203_white(
            xyz[0], xyz[1], xyz[2], false,
        );
        assert_eq!(unchecked_analysis[0], 1.0);
        // The checked representation declares display-linear 2.03 as the
        // 203-nit diffuse white. Dividing it recovers the same canonical 1.0
        // reference-white representation before inverse ACES.
        let checked_physical = xyz.map(|v| v * HDR203_DIFFUSE_WHITE_SCALE);
        let checked_analysis = picker_analyze_xyz_d65_with_display_linear_one_as_hdr203_white(
            checked_physical[0],
            checked_physical[1],
            checked_physical[2],
            true,
        );
        for i in 1..7 {
            assert!(
                (checked_analysis[i] - unchecked_analysis[i]).abs() < 2.0e-8,
                "analysis channel {i}: {} vs {}",
                checked_analysis[i],
                unchecked_analysis[i]
            );
        }
        let unchecked_display = picker_display_rgb_xyz_d65_batch(
            &[xyz[0] as f32, xyz[1] as f32, xyz[2] as f32],
            4,
            false,
        );
        let checked_display = picker_display_rgb_xyz_d65_batch(
            &checked_physical.map(|value| value as f32),
            4,
            true,
        );
        for channel in 0..3 {
            assert!(
                (checked_display[channel] - unchecked_display[channel]).abs() < 2.0e-6,
                "display channel {channel}: {} vs {}",
                checked_display[channel],
                unchecked_display[channel]
            );
        }
    }

    #[test]
    fn scene_ap0_analysis_preserves_unclamped_acescg() {
        let expected = [1.4, -0.2, 0.25];
        let ap0 = aces_output::acescg_to_ap0(expected);
        let analysis = picker_analyze_scene_ap0(ap0[0], ap0[1], ap0[2]);
        assert_eq!(
            analysis[0], 1.0,
            "this signed scene sample remains representable"
        );
        for channel in 0..3 {
            assert!(
                (analysis[channel + 1] - expected[channel]).abs() < 2.0e-12,
                "scene channel {channel}: {} vs {}",
                analysis[channel + 1],
                expected[channel]
            );
        }
    }

    #[test]
    fn scene_ap0_display_uses_the_forward_view_directly() {
        let scene = [0.31, 0.12, 0.04];
        let ap0 = aces_output::acescg_to_ap0(scene);
        for view in [0, 1, 2, 4] {
            let actual = picker_display_rgb_scene_ap0_batch(
                &[ap0[0] as f32, ap0[1] as f32, ap0[2] as f32],
                view,
            );
            let expected = view_rgb(view, scene);
            for channel in 0..3 {
                assert!(
                    (actual[channel] as f64 - expected[channel]).abs() < 2.0e-6,
                    "view {view} channel {channel}: {} vs {}",
                    actual[channel],
                    expected[channel]
                );
            }
        }
    }

    #[test]
    fn unchecked_unit_white_is_valid_but_above_peak_is_rejected() {
        // Both representations normalize to the authored 10/2.03 peak before
        // inverse ACES; the checked form stores that value multiplied by 2.03.
        let rec2020_white = [AUTHORING_REC2020_PEAK; 3];
        let xyz_white = mat(&REC2020_TO_XYZ, rec2020_white);
        let valid = picker_analyze_xyz_d65_with_display_linear_one_as_hdr203_white(
            xyz_white[0],
            xyz_white[1],
            xyz_white[2],
            false,
        );
        assert_eq!(valid[0], 1.0);
        let checked_xyz_white = xyz_white.map(|value| value * HDR203_DIFFUSE_WHITE_SCALE);
        let checked = picker_analyze_xyz_d65_with_display_linear_one_as_hdr203_white(
            checked_xyz_white[0],
            checked_xyz_white[1],
            checked_xyz_white[2],
            true,
        );
        assert_eq!(checked[0], 1.0);
        let rounded_xyz = xyz_white.map(|value| value as f32 as f64);
        let rounded = picker_analyze_xyz_d65_with_display_linear_one_as_hdr203_white(
            rounded_xyz[0],
            rounded_xyz[1],
            rounded_xyz[2],
            false,
        );
        assert_eq!(rounded[0], 1.0);
        let above = xyz_white.map(|v| v * 1.001);
        let invalid = picker_analyze_xyz_d65_with_display_linear_one_as_hdr203_white(
            above[0], above[1], above[2], false,
        );
        assert_eq!(invalid[0], 0.0);
    }

    #[test]
    fn linear_slice_center_matches_picker_evaluation_in_every_view() {
        for view in [0, 1, 2, 4] {
            let rows = picker_render_linear_rows(view, 0.38, 3, 3, 1, 2);
            let center = &rows[4..8];
            let evaluated = picker_evaluate(view, 0.38, 0.5, 0.5, 0.15);
            assert_eq!(center[3], 1.0);
            for channel in 0..3 {
                assert!((center[channel] as f64 - evaluated[26 + channel]).abs() < 2.0e-6);
            }
        }
    }
}

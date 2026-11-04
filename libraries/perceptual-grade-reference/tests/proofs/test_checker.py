"""Kernel proof acceptance and negative controls for the axiom audit."""
from importlib.resources import files
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from verification.color_model import check, ALLOWED_AXIOMS

RESOURCES = files('tests.proofs')
LEAN = Path(str(RESOURCES / 'lean'))
DEPENDENCIES = Path(str(RESOURCES / 'dependencies'))


class ProofTests(unittest.TestCase):
    def test_project_report_covers_core_theorems(self):
        report = json.loads((RESOURCES / 'checked.json').read_text())
        self.assertEqual(report['toolchain'], '4.35.0')
        self.assertLessEqual(set(report['axioms']), ALLOWED_AXIOMS)
        required = {'kernel_strictMono', 'tone_strictMono', 'drivers_complement', 'disk_inverse',
                    'visibility_bounds', 'membership_bounds', 'membership_scale',
                    'membership_crossover', 'membership_abs_crossover',
                    'driver_black', 'driver_neutral', 'drivers_crossover', 'low_driver_gt_high_iff',
                    'signed_hk_unique', 'signed_hk_continuous',
                    'hk_coordinate_inverse', 'signed_root_continuous', 'carried_energy_reset',
                    'signed_compression_inverse', 'signed_pow_inverse', 'signed_achromatic_roundtrip',
                    'onset_profile_c2', 'bounded_response_inverse',
                    'input_lift_nonnegative', 'input_lift_black', 'input_lift_luminance',
                    'input_lift_continuous', 'input_repair_bounds', 'input_repair_identity',
                    'input_repair_idempotent', 'input_repair_continuous',
                    'positive_cubic_c2', 'rounded_hinge_c2', 'rounded_corner_c2',
                    'corner_cubic_monotone', 'corner_cubic_inverse_unique',
                    'finite_spindle_c2', 'finite_spindle_derivative', 'finite_spindle_second_derivative',
                    'finite_spindle_endpoints', 'finite_spindle_strict_mono', 'finite_spindle_bounds',
                    'finite_spindle_slope_bounds', 'finite_spindle_inverse_exists',
                    'finite_spindle_inverse_unique', 'normalized_cone_bounds',
                    'finite_spindle_compress_zero', 'finite_spindle_compress_identity',
                    'finite_spindle_compress_stable_eq', 'finite_spindle_direct_inverse_root',
                    'finite_spindle_release_compress', 'finite_spindle_compress_release',
                    'finite_spindle_compress_bounds', 'finite_spindle_compress_c2',
                    'finite_spindle_compress_cubic_bound', 'finite_spindle_cartesian_cubic_bound',
                    'finite_spindle_cartesian_inverse_cubic_bound',
                    'finite_spindle_cartesian_neutral_derivative',
                    'finite_spindle_cartesian_inverse_neutral_derivative',
                    'hard_spindle_idempotent', 'hard_spindle_continuous', 'finite_spindle_reset', 'linear_first_reset',
                    'appearance_pair_roundtrip', 'matching_stack_pair_result', 'matching_stack_pair_reset',
                    'spindle_release_cube', 'guarded_response_domain',
                    'pole_spindle_denominator_pos', 'pole_spindle_radicand_pos',
                    'pole_spindle_profile_coefficients', 'pole_spindle_profile_numerator_pos',
                    'pole_spindle_profile_endpoints', 'pole_spindle_blend_eq_profile',
                    'pole_spindle_c2', 'pole_spindle_release_derivative',
                    'pole_spindle_neutral_derivative', 'pole_spindle_neutral_second_derivative',
                    'pole_spindle_endpoint_derivative', 'pole_spindle_release_tendsto_pole',
                    'pole_spindle_release_zero', 'pole_spindle_release_one', 'pole_spindle_identity',
                    'pole_spindle_slope_ge_one', 'pole_spindle_strict_mono', 'pole_spindle_bounds',
                    'pole_spindle_global_compression', 'pole_spindle_inverse_exists',
                    'pole_cubic_discriminant', 'pole_cubic_largest_correct', 'pole_cubic_middle_correct',
                    'pole_spindle_cubic_pole_value', 'pole_spindle_cubic_pole_derivative',
                    'pole_cubic_upper_extremum_rationalization', 'pole_cubic_upper_extremum_evaluation',
                    'pole_cubic_lower_extremum_value', 'pole_cubic_extrema_invariant',
                    'pole_cubic_monic_invariant', 'pole_extrema_point_ordinate',
                    'pole_extrema_angle_invariant', 'pole_extrema_angle_eq_arccos',
                    'pole_cubic_extrema_largest_eq',
                    'pole_spindle_inverse_polynomial', 'pole_spindle_inverse_square_correct',
                    'pole_spindle_compress_release', 'pole_spindle_release_compress',
                    'pole_spindle_compress_le', 'pole_spindle_factored_sqrt', 'pole_spindle_reset',
                    'pole_spindle_release_compress_extended', 'pole_spindle_compress_tendsto_pole',
                    'pole_spindle_signed_inverse_c2', 'pole_spindle_signed_inverse_derivative',
                    'pole_spindle_inverse_neutral_derivative', 'pole_spindle_inverse_neutral_second_derivative',
                    'pole_spindle_compress_c2_on', 'pole_spindle_compress_neutral_derivative',
                    'pole_spindle_compress_stable_eq', 'pole_spindle_stable_branch_domain',
                    'pole_spindle_stable_compress_c2_on',
                    'pole_spindle_stable_inverse_cartesian_neutral_derivative',
                    'pole_spindle_cartesian_cubic_bound', 'pole_spindle_cartesian_neutral_derivative',
                    'pole_spindle_closed_inverse_cartesian_neutral_derivative',
                    'piecewise_spindle_denominator_lower', 'piecewise_spindle_parameters_safe',
                    'piecewise_spindle_c2', 'piecewise_spindle_join_jets',
                    'piecewise_spindle_endpoints', 'piecewise_spindle_core_neutral',
                    'piecewise_spindle_tail_derivative', 'piecewise_spindle_tail_second_derivative',
                    'piecewise_spindle_tail_strict_mono', 'piecewise_spindle_tail_curvature_nonneg',
                    'piecewise_spindle_exterior_join_jets', 'piecewise_spindle_exterior_strict_mono',
                    'piecewise_spindle_exterior_tendsto_pole',
                    'piecewise_cardano_root', 'piecewise_cubic_inverse_root',
                    'piecewise_core_inverse_root', 'piecewise_core_inverse_roundtrip',
                    'piecewise_tail_discriminant_positive', 'piecewise_tail_inverse_roundtrip_admissible',
                    'piecewise_exterior_inverse_bounds', 'piecewise_exterior_release_inverse',
                    'piecewise_spindle_extended_c2', 'piecewise_spindle_strict_mono',
                    'piecewise_spindle_physical_curvature_nonneg',
                    'piecewise_spindle_compress_release', 'piecewise_spindle_release_compress',
                    'piecewise_spindle_reset', 'piecewise_spindle_cartesian_cubic_bound',
                    'piecewise_spindle_cartesian_inverse_cubic_bound',
                    'piecewise_spindle_cartesian_neutral_derivative',
                    'piecewise_spindle_cartesian_inverse_neutral_derivative'}
        required.update({
            'hk_guard_delta_bounds', 'hk_guard_delta_stable', 'hk_guard_delta_monotone',
            'hk_guard_energy_identity', 'hk_guard_energy_nonnegative', 'hk_guard_energy_positive',
            'hk_guard_energy_above_request', 'hk_guard_energy_le_height',
            'hk_guard_energy_c2', 'hk_guard_normalized_knee_jets',
            'hk_guard_allocation_bounds', 'hk_guard_allocation_monotone',
            'hk_guard_projection_energy', 'hk_guard_projection_chroma_bounds',
            'hk_guard_projection_lightness_bounds', 'hk_guard_hue_preserved',
            'hk_guard_reset_energy', 'hk_guard_neutral_energy',
            'hk_guard_inverse_parameter', 'hk_guard_inverse_d_antitone',
            'hk_guard_inverse_residual_strict_mono', 'hk_guard_inverse_unique', 'hk_guard_inverse_exists',
            'hk_guard_inverse_energy_roundtrip', 'hk_guard_inverse_bracket',
            'hk_guard_inverse_request_roundtrip', 'hk_guard_forward_inverse_residual',
            'hk_guard_active_branch_separation', 'hk_guard_signed_deficit_nonnegative_branch',
            'hk_guard_signed_deficit_negative_branch',
        })
        required.update({
            'web_s5_endpoint_jets', 'web_s5_unit_bounds', 'web_s5_clamped_c2',
            'web_blend_anchors', 'web_blend_reset', 'web_radial_derivative',
            'web_radial_slope_positive', 'web_radial_strict_mono', 'web_radial_c2',
            'web_radial_reset', 'web_radial_zero', 'web_radial_neutral_slope',
            'web_radial_calibrates', 'web_radial_calibration_positive',
            'web_toe_error_bound', 'web_radial_cartesian_neutral_derivative',
            'web_signed_saturation_scale', 'web_staged_jacobian_positive',
            'web_angular_fade_derivative_positive', 'web_mean_slope_positive',
            'web_mean_slope_fourth', 'web_mean_slope_bound', 'web_quintic_gap_positive',
            'web_bezier_derivative', 'web_bezier_slope_positive',
            'web_hue_sector_endpoints', 'web_hue_sector_slope_positive',
            'web_hue_sector_jets', 'web_hue_join_c2',
            'web_angular_delta_neutral_derivative', 'web_angular_cartesian_neutral_derivative',
            'web_full_neutral_derivative',
        })
        required.update({
            'selective_physical_cone_equivalence', 'selective_signed_identity',
            'selective_signed_group', 'selective_signed_inverse',
            'selective_signed_strict_mono', 'selective_normalized_inverse',
            'selective_boundary_value_and_slope', 'selective_boundary_second_jet',
            'selective_negative_boundary_jets', 'selective_calibration_positive',
            'selective_calibration_target', 'selective_normalization_neutral',
            'selective_reach_bounds', 'selective_reach_half', 'selective_reach_scale',
            'selective_reach_neutral_derivative', 'selective_reach_high_chroma_limit',
            'linear_saturation_scale', 'linear_saturation_center_target',
        })
        required.update({
            'warp_carried_zero_threshold', 'warp_carried_negative_threshold',
            'warp_compact_hue_preserved', 'warp_compact_radius_bounds',
            'warp_compact_radius_on_raw_rim', 'warp_compact_radius_strict_interior',
            'warp_guarded_raw_rim_moves_interior', 'warp_guarded_chart_interior',
            'web_negative_scale_height_factor', 'web_negative_scale_height_positive_iff',
            'web_negative_scale_height_derivative',
            'web_negative_scale_slope_nonnegative_iff',
            'web_negative_scale_slope_zero_iff',
            'web_negative_scale_increasing_positive',
            'web_negative_scale_physical_ceiling',
            'web_negative_scale_signed_hk', 'web_negative_scale_turning_point',
            'web_negative_scale_final_state_ceiling',
        })
        required.update({
            'hk_repaired_energy_positive', 'hk_repaired_ray_energy', 'hk_repaired_ray_ja_positive',
            'hk_repaired_coordinates_energy', 'hk_repaired_ray_chroma_bounds',
            'hk_repaired_zero_reference_counterexample', 'hk_zero_reference_cube_black',
            'encoded_positive_energy_nonblack', 'encoded_positive_energy_luminance',
            'hk_ideal_cube_positive_luminance', 'hk_cube_ray_guard_positive_luminance',
            'hk_cube_ray_guard_positive_luminance_from_prefix',
            'cube_guard_positive_energy', 'hk_cube_guard_positive_luminance',
        })
        self.assertLessEqual({'PerceptualGrade.'+name for name in required}, set(report['theorems']))
        correspondence = (RESOURCES / 'README.md').read_text().partition('## Machine-checked theorem correspondence')[2]
        documented = re.findall(r'`([a-z]+(?:_[a-z0-9]+)+)`', correspondence)
        self.assertTrue(documented)
        self.assertLessEqual({'PerceptualGrade.'+name for name in documented}, set(report['theorems']))

    def fixture(self, root, text):
        sources = root / 'sources'
        (sources / 'PerceptualGrade').mkdir(parents=True)
        (sources / 'PerceptualGrade' / 'Control.lean').write_text(text)
        return sources

    def test_false_and_unfinished_statements_rejected(self):
        cases = [('theorem false_claim : False := by exact True.intro', RuntimeError),
                 ('theorem false_claim : False := by sorry', ValueError),
                 ('axiom fabricated : False\ntheorem false_claim : False := fabricated', ValueError)]
        for body, error in cases:
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                sources = self.fixture(root, 'namespace PerceptualGrade\n'+body+'\nend PerceptualGrade\n')
                with self.assertRaises(error):
                    check(LEAN, DEPENDENCIES, sources, root / 'output')

    def test_transitive_custom_axiom_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'output'
            output.mkdir()
            external = output / 'External.lean'
            external.write_text('axiom externalFalse : False\n')
            subprocess.run([str(LEAN / 'bin/lean'), '--root='+str(output), '-o', str(output / 'External.olean'),
                            str(external)], check=True, capture_output=True, text=True)
            sources = self.fixture(root, 'import External\nnamespace PerceptualGrade\n'
                                   'theorem false_claim : False := externalFalse\nend PerceptualGrade\n')
            with self.assertRaisesRegex(ValueError, 'Unexpected theorem axioms: externalFalse'):
                check(LEAN, DEPENDENCIES, sources, output)

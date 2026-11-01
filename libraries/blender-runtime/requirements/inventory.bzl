"""Required checked claims, independent of .inv declaration admission."""

LEAF_REQUIREMENTS = {
    "native_evaluation": {
        "properties": [
            "out_of_order_observation_preserves_state",
            "foreign_generation_preserves_authority",
            "ordered_foreign_observation_is_consumed",
            "begin_preserves_every_prior_lease",
            "finish_removes_only_exact_validated_lease",
            "unmatched_finish_cannot_release",
            "pending_ingress_blocks_readiness",
            "outstanding_lease_blocks_readiness",
            "native_job_blocks_readiness",
            "failed_or_closed_blocks_readiness",
            "readiness_requires_current_generation",
            "failure_is_sticky_until_validated_replacement",
            "replacement_requires_validated_current_observation",
            "closed_preserves_authority",
            "rejected_current_begin_fences_readiness",
            "ordered_observation_advances_once",
        ],
        "witnesses": [
            "first_native_lease_is_admitted",
            "last_exact_completion_restores_readiness",
            "overlapping_reader_remains_blocked",
            "validated_replacement_recovers_failed_state",
        ],
        "mutations": [
            "admission_ignores_pending_ingress",
            "admission_ignores_active_lease",
            "admission_ignores_native_job",
            "foreign_receipt_changes_authority",
            "finish_skips_retirement_validation",
            "replacement_skips_validation",
        ],
    },
    "attempt": {
        "properties": [
            "foreign_attempt_ignored",
            "cancellation_retains_occupancy",
            "retirement_is_explicit",
            "retired_attempt_is_absorbing",
            "start_requires_current_interest",
            "rejected_attempt_preserves_state",
        ],
        "witnesses": [
            "start_admitted",
            "cancellation_is_still_occupied",
        ],
        "mutations": [
            "detach_releases_running_attempt",
        ],
    },
    "edge_effect": {
        "properties": [
            "foreign_effect_does_not_change_state",
            "retired_effect_is_absorbing",
            "arm_revokes_known_value",
            "failed_compensation_retains_uncertainty",
            "commit_requires_known_applied_value",
            "compensation_restores_original_edge",
            "edge_count_exact",
        ],
        "witnesses": [
            "arm_is_possible",
            "compensation_is_possible",
        ],
        "mutations": [
            "arm_keeps_old_authority",
        ],
    },
    "gpu": {
        "properties": [
            "validation_binds_probe",
            "probing_disables_gpu",
            "generation_never_regresses",
            "restored_availability_requires_validation",
            "rejected_gpu_receipt_preserves_state",
        ],
        "witnesses": [
            "probe_admitted",
            "validation_admitted",
        ],
        "mutations": [
            "unvalidated_probe_is_accepted",
        ],
    },
    "ownership": {
        "properties": [
            "recovery_waits_for_borrows",
            "recovery_requires_current_safe_token",
            "unsafe_state_cannot_retain_or_borrow",
            "unsafe_replacement_is_sticky",
            "replacement_records_outstanding_native_ownership",
            "replacement_begin_advances_epoch",
            "fenced_ownership_blocks_capture",
            "resolution_requires_current_safe_epoch",
            "replacement_revokes_old_resolution",
            "fenced_or_failed_cannot_resolve",
            "accounting_preserves_resolution",
            "retry_requires_failed_current_safe_generation",
            "retry_preserves_native_ownership_and_epoch",
            "retry_rejection_preserves_state",
        ],
        "witnesses": [
            "clean_recovery_admitted",
            "replacement_detects_borrow",
            "active_resolution_possible",
            "rebind_resolution_possible",
            "failed_rebind_can_retry",
        ],
        "mutations": [
            "recovery_ignores_borrows",
            "resolution_ignores_epoch",
            "resolution_ignores_unsafe",
            "resolution_ignores_phase",
            "retry_ignores_generation",
            "retry_ignores_borrows",
        ],
    },
    "retry": {
        "properties": [
            "crash_retry_bounded",
            "deterministic_failure_not_retried",
            "rebind_preserves_budget",
            "accepted_crash_consumes_one_retry",
            "retry_budget_never_decreases",
        ],
        "witnesses": [
            "first_crash_retry",
        ],
        "mutations": [
            "crash_does_not_consume_budget",
        ],
    },
    "startup": {
        "properties": [
            "startup_budget_bounded",
            "failed_start_is_recorded",
            "dispatch_resets_budget",
            "exhausted_failure_cannot_restart",
        ],
        "witnesses": [
            "first_failed_start_retries",
            "second_failed_start_rejected",
        ],
        "mutations": [
            "exhausted_start_is_retried",
        ],
    },
}

LEAF_PROOFS = ["//libraries/blender-runtime:proof_" + name for name in LEAF_REQUIREMENTS]

"""Mandatory coordinator proof claims and controls."""

COORDINATOR_REQUIREMENTS = {
    "scope_demand": {
        "properties": [
            "capture_requires_unpaused_free_slot",
            "publication_requires_exact_compatible_receipt",
            "pending_demand_keeps_active_snapshot",
            "publication_is_monotonic",
            "pause_revokes_active_authority",
            "foreign_epoch_cannot_publish",
            "failure_does_not_restart_same_demand",
            "newest_pending_starts",
        ],
        "witnesses": [
            "compatible_progress_precedes_newest",
        ],
        "mutations": [
            "paused_capture",
            "foreign_capture_publishes",
            "incompatible_capture_publishes",
        ],
    },
    "bake": {
        "properties": [
            "publish_only_current_candidate",
            "retiring_candidate_does_not_publish",
            "preview_requires_current_candidate",
            "candidate_only_stages",
            "manual_request_is_frozen",
            "manual_has_no_preview",
            "closing_cannot_publish",
        ],
        "witnesses": [
            "staging_is_possible",
            "foreground_publication_is_possible",
        ],
        "mutations": [
            "candidate_publishes_without_foreground_permission",
            "manual_request_is_replaced",
        ],
    },
    "scope": {
        "properties": [
            "publication_requires_current_valid_payload",
            "late_receipt_after_cancel_ignored",
            "registration_ack_must_match_current_capture",
            "capture_cancellation_waits_for_retirement",
            "close_waits_for_capture_retirement",
            "seed_receipt_binds_native_source",
        ],
        "witnesses": [
            "capturing_cancel_is_possible",
            "registered_seed_compute_is_possible",
        ],
        "mutations": [
            "capture_cancel_drops_retirement",
        ],
    },
    "exact": {
        "properties": [
            "invoke_needs_preparation",
            "native_callback_is_not_completion",
            "changed_intent_requires_preparation",
            "failed_cleanup_requires_verified_close",
            "explicit_next_frame_is_preserved",
            "native_cancel_requires_stop_receipt",
        ],
        "witnesses": [
            "native_stop_can_complete",
            "negative_frame_is_supported",
        ],
        "mutations": [
            "completion_skips_stop_validation",
            "next_frame_assumes_unit_stride",
        ],
    },
    "publication": {
        "properties": [
            "publish_only_verified_current",
            "failure_is_conservative",
            "stopping_never_publishes",
            "ready_requires_publication_receipt",
            "repaired_baseline_never_certifies",
            "closing_cannot_erase_debt",
            "debt_release_requires_verified_terminal_receipt",
            "supersession_requires_actual_new_generation",
            "no_write_abort_cannot_certify",
            "verified_no_write_abort_releases_debt",
            "relinquishment_is_current_and_never_certifies",
        ],
        "witnesses": [
            "repair_releases_owned_baseline",
            "verified_publication_is_possible",
            "closing_repair_can_finish",
            "no_write_abort_after_candidate_readback",
            "runtime_reconciliation_relinquishes_debt",
        ],
        "mutations": [
            "failed_write_erases_repair_debt",
            "close_discards_backup_debt",
            "no_write_abort_ignores_validation",
            "relinquishment_ignores_validation",
        ],
    },
    "scope_input": {
        "properties": [
            "native_start_requires_current_authority",
            "automatic_requests_never_start_native",
            "authority_is_consumed_once",
            "running_request_cannot_reuse_authority",
            "duplicate_request_is_ignored",
            "source_invalidation_revokes_authority",
            "generation_fence_rejects_receipts",
            "candidate_requires_exact_validated_receipt",
            "obsolete_or_duplicate_candidate_is_ignored",
            "failed_request_requires_new_request",
            "retirement_is_required_for_release",
            "physical_lease_survives_until_retirement",
            "capture_candidate_keeps_physical_lease",
            "closing_cannot_publish_or_start",
            "cancel_keeps_physical_lease",
        ],
        "witnesses": [
            "automatic_acquisition_is_possible",
            "native_capture_is_possible",
            "failure_can_retry_after_fresh_request",
            "close_waits_for_exact_retirement",
        ],
        "mutations": [
            "unauthorized_native_start",
            "reused_capture_authority",
            "invalidated_authority_survives",
            "obsolete_source_can_publish",
            "cancelled_candidate_can_publish",
            "failed_authority_survives",
            "release_without_physical_confirmation",
        ],
    },
    "bake_queue": {
        "properties": [
            "admission_reserves_one_free_target",
            "dispatch_requires_frozen_head_and_free_lane",
            "destination_publication_follows_click_order",
            "physical_release_needs_validated_retirement",
            "reservation_release_needs_terminal_receipt",
            "cancel_preserves_physical_lease",
            "foreign_generation_has_no_effect",
            "closing_cannot_admit_dispatch_or_publish",
            "unrelated_entries_remain_unchanged",
            "frozen_request_identity_survives_queueing",
        ],
        "witnesses": [
            "two_destinations_can_run",
            "shared_destination_can_wait",
            "retired_worker_frees_lane_before_publication",
        ],
        "mutations": [
            "duplicate_target_admitted",
            "busy_worker_reused",
            "retirement_ignores_validation",
            "finish_ignores_physical_lease",
            "cancel_drops_worker_lease",
            "shared_destination_starts_out_of_order",
        ],
    },
    "recovery": {
        "properties": [
            "stale_receipt_ignored",
            "physical_retirement_requires_receipt",
            "journal_retirement_requires_native_replacement",
            "adoption_never_certifies_output",
            "one_owner_settles_once",
            "accepted_work_reduces_remaining",
            "failure_retains_obligations",
            "activation_requires_complete_worklist",
            "failed_retry_needs_new_generation",
            "wrapper_restoration_requires_ordered_receipt",
            "wrapper_restoration_follows_adoption",
        ],
        "witnesses": [
            "empty_project_completes",
            "owner_restores_before_activation",
        ],
        "mutations": [
            "retirement_without_receipt",
            "stale_generation_accepted",
            "adoption_mints_certificate",
            "wrapper_restoration_ignores_validation",
        ],
    },
}

COORDINATOR_PROOFS = ["//libraries/perceptual-grade-core/proofs:proof_bake_coordinator", "//libraries/perceptual-grade-core/proofs:proof_scope_coordinator", "//libraries/perceptual-grade-core/proofs:proof_exact_coordinator", "//libraries/perceptual-grade-core/proofs:proof_publication_coordinator", "//libraries/perceptual-grade-core/proofs:proof_scope_input_coordinator", "//libraries/perceptual-grade-core/proofs:proof_scope_demand_coordinator", "//libraries/perceptual-grade-core/proofs:proof_bake_queue_coordinator", "//libraries/perceptual-grade-core/proofs:proof_recovery_coordinator"]

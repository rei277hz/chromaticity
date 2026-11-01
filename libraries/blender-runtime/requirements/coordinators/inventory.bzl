"""Mandatory coordinator proof claims and controls."""

COORDINATOR_REQUIREMENTS = {
    "execution": {
        "properties": [
            "deliver_waits_for_physical_retirement",
            "stale_attempt_cannot_deliver",
            "probe_never_retries_or_falls_back",
            "cancelled_attempt_cannot_deliver",
            "startup_rebind_preserves_job_budget",
            "local_rejection_never_falls_back",
        ],
        "witnesses": [
            "delivery_is_possible",
            "probe_failure_finishes_without_retry",
            "confirmed_startup_rebind_is_possible",
            "local_payload_rejection_is_possible",
        ],
        "mutations": [
            "delivery_ignores_terminal_receipt",
            "probe_failure_falls_back",
            "rebind_consumes_job_retry",
        ],
    },
    "lifecycle": {
        "properties": [
            "native_replacement_requires_quiescence",
            "activation_requires_inspection",
            "closed_requires_physical_release",
            "external_replacement_never_authorizes_replacement",
            "disable_release_waits_for_every_worker_and_debt",
            "external_post_requires_recorded_pre",
            "manual_inspection_does_not_advance_generation",
        ],
        "witnesses": [
            "replacement_can_retire_detached_workers_later",
            "clean_disable_can_release",
            "manual_inspection_is_possible",
        ],
        "mutations": [
            "replacement_ignores_repair_debt",
        ],
    },
}

COORDINATOR_PROOFS = ["//libraries/blender-runtime:proof_execution_coordinator", "//libraries/blender-runtime:proof_lifecycle_coordinator"]

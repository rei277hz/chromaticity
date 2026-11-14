"""Consume fixed-bank publication effects in their authorized order."""

# pg-book: technical-report/en#next-policy.bank-publication

from dataclasses import dataclass
from typing import Literal

from ..policy import bank_publication as policy


@dataclass(frozen=True)
class PublicationResult:
    outcome: Literal["committed", "failed_closed", "indeterminate"]
    errors: tuple[Exception, ...]


def run_bank_publication(active_bank, candidate_bank, operations, *, admitted,
                         active_valid):
    state = policy.new()
    event = policy.Event("begin", active_bank, candidate_bank,
                         admitted=bool(admitted), active_valid=bool(active_valid))
    failures = []
    fail_closed_attempts = 0
    committed = False
    closed = False
    while True:
        state, effects = policy.step(state, event)
        action = effects.action
        if action is None:
            outcome = "committed" if committed else (
                "failed_closed" if closed else "indeterminate"
            )
            return PublicationResult(outcome, tuple(failures))
        operation_error = None
        try:
            observation = operations[action](effects.bank, tuple(failures)) or {}
        except Exception as error:
            operation_error = error
            failures.append(error)
            observation = {}

        if action in ("stage", "repair"):
            clean = bool(observation.get("clean"))
            if not clean and operation_error is None:
                failures.append(RuntimeError("Banked helper image could not be packed cleanly"))
            event = policy.Event("staged", active_bank, candidate_bank,
                                 clean=clean,
                                 failed=operation_error is not None)
        elif action == "select":
            event = policy.Event("selected", active_bank, candidate_bank,
                                 selected_bank=observation.get("selected_bank"),
                                 failed=operation_error is not None)
        elif action == "deliver":
            delivered = bool(observation.get("delivered"))
            if not delivered and operation_error is None:
                failures.append(RuntimeError("Grade publication delivery was not confirmed"))
            event = policy.Event("delivered", active_bank, candidate_bank,
                                 failed=operation_error is not None or not delivered)
            committed = operation_error is None and delivered
        elif action == "restore_selector":
            restored = observation.get("selected_bank") == active_bank
            if not restored and operation_error is None:
                failures.append(RuntimeError(
                    "Grade bank selector restoration was not confirmed"
                ))
            event = policy.Event("restored", active_bank, candidate_bank,
                                 selected_bank=observation.get("selected_bank"),
                                 failed=operation_error is not None or not restored)
        else:
            fail_closed_attempts += 1
            if fail_closed_attempts > 2:
                failures.append(RuntimeError("Could not establish the banked failure output"))
                return PublicationResult("indeterminate", tuple(failures))
            confirmed = bool(observation.get("closed"))
            if not confirmed and operation_error is None:
                failures.append(RuntimeError("Grade failure output was not confirmed"))
            closed = closed or (operation_error is None and confirmed)
            event = policy.Event(
                "closed", active_bank, candidate_bank,
                failed=operation_error is not None or not confirmed,
            )

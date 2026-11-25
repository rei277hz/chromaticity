"""Consume fixed-bank publication effects in their authorized order."""

# pg-book: technical-report/en#next-policy.bank-publication

from dataclasses import dataclass
from typing import Literal

from .policy import bank_publication as policy


@dataclass(frozen=True)
class PublicationResult:
    outcome: Literal["committed", "failed_closed", "indeterminate"]
    errors: tuple[Exception, ...]


def run_bank_publication(active_bank, operations, *, admitted, active_valid):
    state = policy.new()
    event = policy.Event("begin", active_bank=active_bank,
                         admitted=bool(admitted), active_valid=bool(active_valid))
    failures = []
    while True:
        state, effects = policy.step(state, event)
        if effects.outcome is not None:
            if effects.outcome == "indeterminate":
                failures.append(RuntimeError("Could not establish the banked failure output"))
            return PublicationResult(effects.outcome, tuple(failures))
        action = effects.action
        if action is None:
            raise RuntimeError("Bank publication policy returned no operation or outcome")
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
            event = policy.Event("staged", clean=clean,
                                 failed=operation_error is not None)
        elif action == "select":
            event = policy.Event("selected",
                                 selected_bank=observation.get("selected_bank"),
                                 failed=operation_error is not None)
        elif action == "deliver":
            delivered = bool(observation.get("delivered"))
            if not delivered and operation_error is None:
                failures.append(RuntimeError("Grade publication delivery was not confirmed"))
            event = policy.Event("delivered",
                                 failed=operation_error is not None or not delivered)
        elif action == "restore_selector":
            restored = observation.get("selected_bank") == effects.bank
            if not restored and operation_error is None:
                failures.append(RuntimeError(
                    "Grade bank selector restoration was not confirmed"
                ))
            event = policy.Event("restored")
        else:
            confirmed = bool(observation.get("closed"))
            if not confirmed and operation_error is None:
                failures.append(RuntimeError("Grade failure output was not confirmed"))
            event = policy.Event("closed", failed=operation_error is not None or not confirmed)

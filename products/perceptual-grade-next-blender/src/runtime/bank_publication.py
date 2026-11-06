"""Consume fixed-bank publication effects in their authorized order."""

from ..policy import bank_publication as policy


def run_bank_publication(active_bank, candidate_bank, operations):
    state = policy.new()
    event = policy.Event("begin", active_bank, candidate_bank)
    failures = []
    fail_closed_attempts = 0
    while True:
        state, effects = policy.step(state, event)
        action = effects.action
        if action is None:
            return tuple(failures)
        operation_error = None
        try:
            observation = operations[action](effects.bank, tuple(failures)) or {}
        except Exception as error:
            operation_error = error
            failures.append(error)
            observation = {}

        if action == "stage":
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
            event = policy.Event("delivered", active_bank, candidate_bank,
                                 failed=operation_error is not None)
        elif action == "restore_selector":
            event = policy.Event("restored", active_bank, candidate_bank,
                                 selected_bank=observation.get("selected_bank"),
                                 failed=operation_error is not None)
        else:
            fail_closed_attempts += 1
            if fail_closed_attempts > 2:
                failures.append(RuntimeError("Could not establish the banked failure output"))
                return tuple(failures)
            event = policy.Event("closed", active_bank, candidate_bank,
                                 failed=operation_error is not None)

"""Consume immutable parameter-publication effects; never restore old pixels."""

# pg-book: technical-report/en#next-policy.parameter-publication

from ..policy import parameter_publication as policy


def run_parameter_publication(operations):
    state = policy.new()
    event = policy.Event()
    failures = []
    while True:
        state, effects = policy.step(state, event)
        action = effects.action
        if action is None:
            return tuple(failures)
        try:
            observation = operations[action](tuple(failures))
            event = policy.Event(**(observation or {}))
            if action == "stage" and not event.clean:
                failures.append(RuntimeError("Grade parameter candidate could not be packed"))
                event = policy.Event(failed=True)
        except Exception as error:
            failures.append(error)
            event = policy.Event(failed=True)

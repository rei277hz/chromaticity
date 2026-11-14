"""Execute only resource operations authorized by the retirement policy."""

# pg-book: technical-report/en#next-policy.resources

from ..policy import resources as policy


def run_resource_lifecycle(operations, *, disposal=False):
    state = policy.new_disposal() if disposal else policy.new_retirement()
    event = policy.Event()
    failures = []
    while True:
        state, effects = policy.step(state, event)
        action = effects.action
        if action is None:
            return tuple(failures)
        try:
            observation = operations[action]()
            event = policy.Event(**(observation or {}))
        except Exception as error:
            failures.append(error)
            event = policy.Event(failed=True)

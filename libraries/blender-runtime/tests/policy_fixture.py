"""Dynamic policy contracts for source-free runtime test fixtures only."""
from color_tools.invariant import AdmissionError, ContractError, Machine

DomainError = ContractError


class PolicyContracts:
    """Domain checks for in-memory fixture modules without generated contracts."""
    def __init__(self, module):
        self.module = module

    def bind(self, module):
        if module is not self.module:
            raise TypeError('policy contracts belong to their exact module')
        return self

    def validate_before(self, name, arguments):
        if name == 'step':
            self.validate_state(arguments['state'])
            valid = self.module.event_valid(arguments['state'], arguments['event'])
            if type(valid) is not bool or not valid:
                raise AdmissionError('event is outside its declared domain')

    def validate_after(self, name, arguments, result):
        if name == 'step':
            self.validate_state(result[0])

    def validate_state(self, state):
        valid = self.module.state_valid(state)
        if type(valid) is not bool or not valid:
            raise ContractError('state is outside its declared domain')


def bind_policy(module, *, initializers=('new',), queries=(), contracts=None, default_initializer=None):
    return Machine(module, contracts=PolicyContracts(module) if contracts is None else contracts,
                   initializers=initializers, queries=queries, default_initializer=default_initializer)

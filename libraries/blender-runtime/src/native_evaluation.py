"""Exact lease bookkeeping around the scalar native-evaluation policy."""
from dataclasses import dataclass
from typing import Literal, Optional

from .policies import native_evaluation as policy


@dataclass(frozen=True)
class State:
    generation: int = 1
    revision: int = 0
    serial: int = 0
    tokens: tuple[int, ...] = ()
    failed: bool = False
    closed: bool = False


@dataclass(frozen=True)
class Event:
    kind: Literal['begin', 'finish', 'replace', 'fail', 'close']
    generation: int = 1
    revision: int = 0
    lease: Optional[int] = None
    index: Optional[int] = None
    proposed_tokens: tuple[int, ...] = ()
    validated: bool = False


Effects = policy.Effects


def new(tokens: tuple[int, ...] = ()) -> State:
    if tokens:
        raise ValueError('Native evaluation starts with an empty lease ledger')
    return State()


def _authority(state: State) -> policy.State:
    return policy.State(state.generation, state.revision, state.serial,
                        state.failed, state.closed)


def available(state: State, generation: int, revision: int,
              native_busy: bool = False) -> bool:
    return policy.available(_authority(state), generation, revision,
                            bool(state.tokens), native_busy)


def step(state: State, event: Event) -> tuple[State, Effects]:
    known = event.lease in state.tokens
    if event.kind == 'begin':
        ledger_valid = event.proposed_tokens == state.tokens + (event.lease,)
    elif event.kind == 'finish':
        index = event.index
        ledger_valid = (index is not None and 0 <= index < len(state.tokens)
                        and state.tokens[index] == event.lease
                        and event.proposed_tokens == state.tokens[:index] + state.tokens[index + 1:])
    else:
        ledger_valid = event.kind == 'replace' and not event.proposed_tokens
    authority, effects = policy.step(_authority(state), policy.Event(
        event.kind, event.generation, event.revision, event.lease,
        known=known, ledger_valid=ledger_valid, validated=event.validated,
    ))
    tokens = (event.proposed_tokens
              if effects.accepted and event.kind in ('begin', 'finish', 'replace')
              else state.tokens)
    return State(authority.generation, authority.revision, authority.serial,
                 tokens, authority.failed, authority.closed), effects

"""Scalar authority for ordered native observations and validated retirement.

The adapter owns the exact lease ledger. Membership, proposed edits, and native
job observations enter this policy as facts; collection algorithms are tested
in the adapter rather than included in the proof boundary.
"""
from dataclasses import dataclass, replace
from typing import Literal, Optional


@dataclass(frozen=True)
class State:
    generation: int = 1
    revision: int = 0
    serial: int = 0
    failed: bool = False
    closed: bool = False


@dataclass(frozen=True)
class Event:
    kind: Literal['begin', 'finish', 'replace', 'fail', 'close']
    generation: int = 1
    revision: int = 0
    lease: Optional[int] = None
    known: bool = False
    ledger_valid: bool = False
    validated: bool = False


@dataclass(frozen=True)
class Effects:
    consumed: bool = False
    accepted: bool = False


def new() -> State:
    return State()


def available(state: State, generation: int, revision: int,
              readers: bool, native_busy: bool = False) -> bool:
    return (generation == state.generation and revision == state.revision
            and not readers and not state.failed and not state.closed
            and not native_busy)


def step(state: State, event: Event) -> tuple[State, Effects]:
    if event.revision != state.revision + 1:
        return state, Effects()
    next_state = replace(state, revision=event.revision)
    if event.generation != state.generation or state.closed:
        return next_state, Effects(consumed=True)
    if event.kind == 'close':
        return replace(next_state, closed=True), Effects(True, True)
    if event.kind == 'fail':
        return replace(next_state, failed=True), Effects(True, True)
    if event.kind == 'replace':
        if event.validated and event.ledger_valid:
            return replace(next_state, generation=state.generation + 1,
                           failed=False), Effects(True, True)
        return next_state, Effects(consumed=True)
    if event.kind == 'begin':
        if event.lease is not None and event.lease > state.serial and event.ledger_valid:
            return replace(next_state, serial=event.lease), Effects(True, True)
        return replace(next_state, failed=True), Effects(consumed=True)
    if not event.known:
        return next_state, Effects(consumed=True)
    if event.ledger_valid and event.validated:
        return next_state, Effects(True, True)
    return replace(next_state, failed=True), Effects(consumed=True)

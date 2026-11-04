"""Scalar bake admission, physical lease, and publication decisions.

The queue adapter supplies observations about other reservations; this module
does not scan, select, or update the reservation collection.
"""
from dataclasses import dataclass, replace
from typing import Literal


@dataclass(frozen=True)
class Entry:
    request: int = 0
    target: int = 0
    destination: int = 0
    phase: Literal['empty', 'freezing', 'queued', 'running', 'ready', 'publishing', 'cancelled'] = 'empty'
    lane: int = 0
    physical: bool = False


@dataclass(frozen=True)
class State:
    generation: int = 1
    serial: int = 0
    closing: bool = False
    entry: Entry = Entry()


@dataclass(frozen=True)
class Event:
    kind: Literal['admit', 'frozen', 'start', 'complete', 'publish', 'cancel', 'retired', 'finish', 'close']
    generation: int = 1
    slot: int = 0
    request: int = 0
    target: int = 0
    destination: int = 0
    lane: int = 0
    validated: bool = False
    target_busy: bool = False
    lane_busy: bool = False
    destination_waits: bool = False


@dataclass(frozen=True)
class Effects:
    accepted: bool = False
    action: Literal['none', 'freeze', 'queue', 'dispatch', 'stage', 'publish', 'cancel', 'retire', 'release', 'cancel_all'] = 'none'
    lane: int = 0


def new() -> State:
    return State()


def earlier(entry: Entry, request: int, destination: int) -> bool:
    return entry.request > 0 and entry.request < request and entry.destination == destination


def cancel_entry(entry: Entry) -> Entry:
    return replace(entry, phase='cancelled') if entry.request > 0 else entry


def step(state: State, event: Event) -> tuple[State, Effects]:
    if event.generation != state.generation:
        return state, Effects()
    if event.kind == 'close':
        return replace(state, closing=True, entry=cancel_entry(state.entry)), Effects(True, 'cancel_all')
    if not 0 <= event.slot < 8:
        return state, Effects()
    entry = state.entry
    if event.kind == 'admit':
        if (not state.closing and entry.request == 0 and event.request > state.serial
                and event.target > 0 and event.destination > 0 and not event.target_busy):
            value = Entry(event.request, event.target, event.destination, 'freezing')
            return replace(state, serial=event.request, entry=value), Effects(True, 'freeze')
        return state, Effects()
    if (entry.request == 0 or event.request != entry.request or event.target != entry.target
            or event.destination != entry.destination):
        return state, Effects()
    if event.kind == 'cancel':
        return replace(state, entry=cancel_entry(entry)), Effects(True, 'cancel' if entry.physical else 'none')
    if event.kind == 'retired' and entry.physical and event.validated:
        return replace(state, entry=replace(entry, physical=False, lane=0)), Effects(True, 'retire', entry.lane)
    if event.kind == 'finish' and entry.phase in ('publishing', 'cancelled') and not entry.physical and event.validated:
        return replace(state, entry=Entry()), Effects(True, 'release')
    if state.closing:
        return state, Effects()
    if event.kind == 'frozen' and entry.phase == 'freezing' and event.validated:
        return replace(state, entry=replace(entry, phase='queued')), Effects(True, 'queue')
    if (event.kind == 'start' and entry.phase == 'queued' and event.validated
            and event.lane in (1, 2) and not event.lane_busy
            and not event.destination_waits):
        return replace(state, entry=replace(entry, phase='running', physical=True, lane=event.lane)), Effects(True, 'dispatch', event.lane)
    if event.kind == 'complete' and entry.phase == 'running' and entry.physical and event.validated:
        return replace(state, entry=replace(entry, phase='ready', physical=False, lane=0)), Effects(True, 'stage', entry.lane)
    if (event.kind == 'publish' and entry.phase == 'ready' and event.validated
            and not event.destination_waits):
        return replace(state, entry=replace(entry, phase='publishing')), Effects(True, 'publish')
    return state, Effects()

"""Trusted collection adapter for scalar bake admission decisions.

The public queue retains eight reservations and two worker lanes. Collection
selection, occupancy scans, and replacement are ordinary runtime bookkeeping;
the selected entry's lifecycle decisions come from bake_queue_policy.
"""
from dataclasses import dataclass, replace

from . import bake_queue_policy as policy

Entry, Event, Effects = policy.Entry, policy.Event, policy.Effects
earlier, cancel_entry = policy.earlier, policy.cancel_entry


@dataclass(frozen=True)
class State:
    generation: int = 1
    serial: int = 0
    closing: bool = False
    entries: tuple[Entry, ...] = (Entry(),) * 8


def new() -> State:
    return State()


def put(state: State, slot: int, value: Entry) -> State:
    if not 0 <= slot < len(state.entries):
        return state
    entries = list(state.entries)
    entries[slot] = value
    return replace(state, entries=tuple(entries))


def target_busy(state: State, target: int) -> bool:
    return target > 0 and any(entry.target == target for entry in state.entries)


def lane_busy(state: State, lane: int) -> bool:
    return lane > 0 and any(entry.lane == lane for entry in state.entries)


def destination_waits(state: State, request: int, destination: int) -> bool:
    return any(earlier(entry, request, destination) for entry in state.entries)


def step(state: State, event: Event) -> tuple[State, Effects]:
    entry = state.entries[event.slot] if 0 <= event.slot < 8 else Entry()
    observation = replace(event,
        target_busy=target_busy(state, event.target),
        lane_busy=lane_busy(state, event.lane),
        destination_waits=destination_waits(state, entry.request, entry.destination))
    selected = policy.State(state.generation, state.serial, state.closing, entry)
    updated, effects = policy.step(selected, observation)
    if not effects.accepted:
        return state, effects
    if effects.action == 'cancel_all':
        state = replace(state, entries=tuple(cancel_entry(item) for item in state.entries))
    else:
        state = put(state, event.slot, updated.entry)
    return replace(state, generation=updated.generation,
                   serial=updated.serial, closing=updated.closing), effects

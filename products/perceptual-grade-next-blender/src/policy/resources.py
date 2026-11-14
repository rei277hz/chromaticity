"""Adoption and synchronous retirement of generated host resources."""

# pg-book: technical-report/en#next-policy.resources

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class Adoption:
    owner_matches: bool
    node_matches: bool
    space_matches: bool
    complete: bool
    image_valid: bool
    image_agrees: bool


def may_adopt(observation: Adoption) -> bool:
    return (observation.owner_matches
            and observation.node_matches and observation.space_matches
            and observation.complete and observation.image_valid
            and observation.image_agrees)


@dataclass(frozen=True)
class State:
    phase: Literal["disposal", "retirement", "fence", "detach", "observe",
                   "evict", "recheck", "remove", "terminal"]


@dataclass(frozen=True)
class Event:
    """Receipt for the sole resource operation currently running synchronously."""

    failed: bool = False
    live: bool = False
    owned: bool = False
    users: int = 0
    protected: bool = False


@dataclass(frozen=True)
class Effects:
    action: Optional[str] = None


def new_disposal() -> State:
    return State("disposal")


def new_retirement() -> State:
    return State("retirement")


def eligible(event: Event) -> bool:
    return event.live and event.owned and event.users == 0 and not event.protected


def step(state: State, event: Event) -> tuple[State, Effects]:
    if state.phase == "disposal":
        return State("fence"), Effects("fence")
    if state.phase == "retirement":
        return State("observe"), Effects("observe")
    if state.phase == "fence":
        if event.failed:
            return State("terminal"), Effects()
        return State("detach"), Effects("detach")
    if state.phase == "detach":
        # A partially detached resource is still protected by fresh user counts.
        return State("observe"), Effects("observe")
    if state.phase == "observe":
        if event.failed:
            return State("terminal"), Effects()
        if not event.live or eligible(event):
            return State("evict"), Effects("evict")
        return State("terminal"), Effects()
    if state.phase == "evict":
        if event.failed:
            return State("terminal"), Effects()
        return State("recheck"), Effects("recheck")
    if state.phase == "recheck":
        if not event.failed and eligible(event):
            return State("remove"), Effects("remove")
        return State("terminal"), Effects()
    if state.phase == "remove":
        return State("terminal"), Effects()
    return state, Effects()

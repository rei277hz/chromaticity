"""Synchronous shared-image publication, durability, and restoration decisions."""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class State:
    phase: Literal["idle", "prepare", "snapshot", "upload", "pack", "commit",
                   "restore_upload", "restore_pack", "restore_metadata",
                   "deliver", "fail", "retire", "terminal"]


@dataclass(frozen=True)
class Event:
    """Receipt for the sole image operation currently running synchronously."""

    failed: bool = False
    matching: bool = False
    clean: bool = False


@dataclass(frozen=True)
class Effects:
    action: Optional[str] = None


def request_save_packing(generated: bool, dirty: bool) -> bool:
    return generated and dirty


def finish_save_packing(clean: bool, error: Optional[str]) -> Optional[str]:
    if error is not None:
        return error
    if not clean:
        return "Grade parameter image could not be packed"
    return None


def new() -> State:
    return State("idle")


def step(state: State, event: Event) -> tuple[State, Effects]:
    if state.phase == "idle":
        return State("prepare"), Effects("prepare")
    if state.phase == "prepare":
        if event.failed:
            return State("fail"), Effects("fail")
        return State("snapshot"), Effects("snapshot")
    if state.phase == "snapshot":
        if event.failed:
            return State("fail"), Effects("fail")
        if event.matching and event.clean:
            return State("commit"), Effects("commit")
        return State("upload"), Effects("upload")
    if state.phase == "upload":
        if not event.failed:
            return State("pack"), Effects("pack")
        return State("restore_upload"), Effects("restore_upload")
    if state.phase == "pack":
        if event.failed or not event.clean:
            return State("restore_upload"), Effects("restore_upload")
        return State("commit"), Effects("commit")
    if state.phase == "commit":
        if event.failed:
            return State("restore_upload"), Effects("restore_upload")
        return State("deliver"), Effects("deliver")
    if state.phase == "restore_upload":
        if event.failed:
            return State("fail"), Effects("fail")
        return State("restore_pack"), Effects("restore_pack")
    if state.phase == "restore_pack":
        if event.failed or not event.clean:
            return State("fail"), Effects("fail")
        return State("restore_metadata"), Effects("restore_metadata")
    if state.phase == "restore_metadata":
        return State("fail"), Effects("fail")
    if state.phase == "deliver":
        if event.failed:
            return State("fail"), Effects("fail")
        return State("retire"), Effects("retire")
    if state.phase == "fail":
        return State("retire"), Effects("retire")
    if state.phase == "retire":
        return State("terminal"), Effects()
    return state, Effects()

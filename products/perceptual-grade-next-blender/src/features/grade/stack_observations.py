"""Runtime-owned observations over enabled Grade Stack entries."""


Entry = tuple[int, str]


def stack_changed(previous: tuple[Entry, ...], current: tuple[Entry, ...]) -> bool:
    return previous != current


def grade_is_referenced(entries: tuple[Entry, ...], grade_id: int) -> bool:
    return any(pointer == grade_id for pointer, _direction in entries)

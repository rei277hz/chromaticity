"""Runtime-owned observations over ordered Grade Stack membership."""


def stack_changed(previous_ids: tuple[int, ...], current_ids: tuple[int, ...]) -> bool:
    return previous_ids != current_ids


def grade_is_referenced(grade_ids: tuple[int, ...], grade_id: int) -> bool:
    return grade_id in grade_ids

"""Execute an image transaction and retain its native restoration snapshot."""

from dataclasses import dataclass

import numpy as np

from ..policy import image_publication as policy


def pack_image_for_save(image, *, generated, pack):
    """Apply the separate save fallback without claiming a new publication."""
    if not policy.request_save_packing(generated, image.is_dirty):
        return
    failure = None
    try:
        pack(image)
        clean = image.packed_file is not None and not image.is_dirty
    except Exception as error:
        failure = error
        clean = False
    error = policy.finish_save_packing(clean, None if failure is None else str(failure))
    if error is not None:
        if failure is not None:
            raise failure
        raise RuntimeError(error)


def write_metadata(entries):
    for owner, key, value in entries:
        if value is None:
            if key in owner:
                del owner[key]
        else:
            owner[key] = value


@dataclass
class ImageSnapshot:
    pixels: object
    metadata: tuple

    @classmethod
    def capture(cls, image, metadata):
        pixels = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(pixels)
        previous = tuple((owner, key, owner.get(key)) for owner, key, _value in metadata)
        return cls(pixels, previous)


def run_image_publication(operations):
    state = policy.new()
    event = policy.Event()
    failures = []
    while True:
        state, effects = policy.step(state, event)
        action = effects.action
        if action is None:
            return tuple(failures)
        try:
            observation = operations[action](tuple(failures))
            event = policy.Event(**(observation or {}))
            # Silent packing failures are observations, not native exceptions.
            if action in ("pack", "restore_pack") and not event.clean:
                error = RuntimeError("Grade parameter image could not be packed")
                failures.append(error)
                event = policy.Event(failed=True)
        except Exception as error:
            failures.append(error)
            event = policy.Event(failed=True)

"""Pack generated images on save and retain native bake restoration snapshots."""

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..features.grade.policy import bank_publication as policy


def pack_image_for_save(image, *, generated, pack):
    """Apply the separate save fallback without claiming a new publication."""
    # pg-book: technical-report/en#next-policy.bank-publication
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
    # pg-book: technical-report/en#next-policy.bake
    pixels: object
    metadata: tuple
    colorspace: Optional[str] = None
    alpha_mode: Optional[str] = None
    half_precision: Optional[bool] = None

    @classmethod
    def capture(cls, image, metadata):
        pixels = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(pixels)
        previous = tuple((owner, key, owner.get(key)) for owner, key, _value in metadata)
        colorspace = getattr(getattr(image, "colorspace_settings", None), "name", None)
        alpha_mode = getattr(image, "alpha_mode", None)
        half_precision = getattr(image, "use_half_precision", None)
        return cls(pixels, previous, colorspace, alpha_mode, half_precision)

    def restore_properties(self, image):
        colorspace = getattr(getattr(image, "colorspace_settings", None), "name", None)
        if self.colorspace is not None and colorspace != self.colorspace:
            image.colorspace_settings.name = self.colorspace
        if self.alpha_mode is not None and getattr(image, "alpha_mode", None) != self.alpha_mode:
            image.alpha_mode = self.alpha_mode
        if (self.half_precision is not None
                and getattr(image, "use_half_precision", None) != self.half_precision):
            image.use_half_precision = self.half_precision

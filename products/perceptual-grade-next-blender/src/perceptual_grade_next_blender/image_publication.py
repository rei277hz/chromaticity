"""Checked native Image publication boundary for explicit Bakes.

The adapter keeps the host-specific Image/RNA operations at the edge.  A
backup store must persist the previous backing before the native write begins;
runtime-only bytes are deliberately not accepted as a publication receipt.
"""

from dataclasses import dataclass
import hashlib
import uuid


@dataclass(frozen=True)
class ImageBackup:
    image_id: object
    payload: object
    token: object


class ImagePublication:
    """Publish one complete Bake result with recoverable overwrite semantics.

    ``backup_store`` exposes ``snapshot(image)``, ``save(image, payload) -> token``,
    ``restore(image, token)``, ``mark_committed(token, candidate)`` and ``discard(token)``. ``write`` writes the
    native full precision result, and ``verify`` must inspect the actual Image
    datablock after the write.  This keeps Image publication independent from
    the analytical evaluator and makes the native commit boundary explicit.
    """

    def __init__(self, image, *, backup_store, write, verify, image_id=None,
                 operation=None):
        if image is None or not all(callable(getattr(backup_store, name, None))
                                    for name in ("save", "restore", "mark_committed", "discard")):
            raise TypeError("Image publication requires an image and persistent backup store")
        if not callable(write) or not callable(verify):
            raise TypeError("Image publication requires native write and verification callbacks")
        self.image = image
        self.backup_store = backup_store
        self.write = write
        self.verify = verify
        self.image_id = image_id if image_id is not None else id(image)
        self.operation = operation
        self.backup = None
        self.staged = None
        self.committed = False

    def stage(self, rgba):
        payload = self._copy_payload(rgba)
        if self.backup is not None or self.staged is not None:
            if (not self.committed and self.backup is not None
                    and self._payload_equal(payload, self.staged)):
                return self.backup
            raise RuntimeError("Image publication is already staged")
        previous = self._snapshot()
        try:
            token = self.backup_store.save(self.image, previous, self.operation)
        except TypeError:
            token = self.backup_store.save(self.image, previous)
        if not token:
            raise RuntimeError("Persistent Image backup was not committed")
        self.backup = ImageBackup(self.image_id, previous, token)
        self.staged = payload
        return self.backup

    def commit(self):
        if self.backup is None or self.staged is None:
            raise RuntimeError("Image publication has no staged result")
        try:
            self.write(self.image, self.staged)
            if not self.verify(self.image, self.staged):
                raise RuntimeError("Native Image write did not verify")
            self.backup_store.mark_committed(self.backup.token, self.staged)
        except BaseException:
            self.restore()
            raise
        self.committed = True
        self.staged = None
        return True

    def finalize(self):
        """Drop retained recovery backing after the exact workflow receipt."""
        if not self.committed or self.backup is None:
            raise RuntimeError("Image publication has no verified native commit")
        self.backup_store.discard(self.backup.token)
        self.backup = None
        return True

    def restore(self):
        if self.backup is None:
            return False
        if self.committed:
            return False
        rollback = getattr(self.backup_store, "rollback", None)
        if callable(rollback):
            rollback(self.backup.token)
        else:
            self.backup_store.restore(self.image, self.backup.token)
            self.backup_store.discard(self.backup.token)
        self.backup = None
        self.staged = None
        self.committed = False
        return True

    def recover(self):
        """Restore a persisted pre-write backing after reopen/crash inspection."""
        return self.restore()

    def _snapshot(self):
        callback = getattr(self.backup_store, "snapshot", None)
        if not callable(callback):
            raise TypeError("Persistent backup store must provide snapshot(image)")
        return callback(self.image)

    @staticmethod
    def _copy_payload(value):
        copy = getattr(value, "copy", None)
        if callable(copy):
            value = copy()
        return value

    @staticmethod
    def _payload_equal(left, right):
        try:
            import numpy as np
            return np.array_equal(np.asarray(left), np.asarray(right))
        except (TypeError, ValueError):
            return left == right


class BlenderImageBackupStore:
    """Persist publication backups as packed float32 Blender Image datablocks."""

    TARGET_KEY = "perceptual_grade_next_bake_backup_id"
    ACTIVE_KEY = "perceptual_grade_next_bake_active_backup"
    TOKEN_KEY = "perceptual_grade_next_bake_backup_token"
    STATE_KEY = "perceptual_grade_next_bake_backup_state"
    DIGEST_KEY = "perceptual_grade_next_bake_backup_candidate_digest"
    OPERATION_KEY = "perceptual_grade_next_bake_backup_operation"
    IMAGE_PREFIX = ".PG Next Bake Recovery "

    def __init__(self, bpy_module=None):
        if bpy_module is None:
            import bpy as bpy_module
        self.bpy = bpy_module

    @staticmethod
    def _pixels(image):
        import numpy as np
        values = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(values)
        return values

    @staticmethod
    def _digest(value):
        import numpy as np
        values = np.asarray(value, dtype=np.float32)
        return hashlib.sha256(values.tobytes(order="C")).hexdigest()

    def snapshot(self, image):
        return self._pixels(image)

    def save(self, image, payload, operation=None):
        import numpy as np

        values = np.asarray(payload, dtype=np.float32)
        if values.ndim != 1 or values.size != len(image.pixels):
            raise ValueError("Bake result does not match the target Image pixel domain")
        if image.get(self.ACTIVE_KEY):
            raise RuntimeError("This Image already has a pending Bake publication")
        stable_id = image.get(self.TARGET_KEY)
        target_id_is_new = not stable_id
        stable_id = stable_id or uuid.uuid4().hex
        token = uuid.uuid4().hex
        width, height = (int(image.size[0]), int(image.size[1]))
        backup = None
        try:
            backup = self.bpy.data.images.new(
                self.IMAGE_PREFIX + token, width=width, height=height,
                alpha=True, float_buffer=True,
            )
            backup.use_half_precision = False
            backup.pixels.foreach_set(values)
            backup.update()
            backup.pack()
            if not backup.packed_file:
                raise RuntimeError("Blender did not pack the Image recovery backing")
            backup[self.TARGET_KEY] = stable_id
            backup[self.TOKEN_KEY] = token
            backup[self.STATE_KEY] = "staged"
            backup[self.OPERATION_KEY] = operation if operation is not None else 0
            image[self.TARGET_KEY] = stable_id
            image[self.ACTIVE_KEY] = token
        except BaseException:
            try:
                image.pop(self.ACTIVE_KEY, None)
                if target_id_is_new:
                    image.pop(self.TARGET_KEY, None)
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
            if backup is not None:
                try:
                    self.bpy.data.images.remove(backup)
                except (ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
            raise
        return token

    def mark_committed(self, token, candidate=None):
        backup = self._backup(token)
        if candidate is None:
            raise ValueError("A verified candidate payload is required for recovery")
        backup[self.DIGEST_KEY] = self._digest(candidate)
        backup[self.STATE_KEY] = "committed"

    def restore(self, image, token):
        backup = self._backup(token)
        if image.get(self.TARGET_KEY) != backup.get(self.TARGET_KEY):
            raise RuntimeError("Recovery backing belongs to another Image")
        self._write(image, self._pixels(backup))

    def discard(self, token):
        backup = self._backup(token, required=False)
        if backup is None:
            return False
        target_id = backup.get(self.TARGET_KEY)
        image = next((item for item in self.bpy.data.images
                      if item.get(self.TARGET_KEY) == target_id
                      and item.get(self.ACTIVE_KEY) == token), None)
        if image is not None:
            image.pop(self.ACTIVE_KEY, None)
        self.bpy.data.images.remove(backup)
        return True

    def rollback(self, token):
        backup = self._backup(token, required=False)
        if backup is None:
            return False
        target_id = backup.get(self.TARGET_KEY)
        target = next((item for item in self.bpy.data.images
                       if item.get(self.TARGET_KEY) == target_id
                       and item.get(self.ACTIVE_KEY) == token), None)
        if target is not None:
            self._write(target, self._pixels(backup))
            target.pop(self.ACTIVE_KEY, None)
        self.bpy.data.images.remove(backup)
        return True

    def recover_pending(self):
        """Recover interrupted publications after load/undo reconstruction."""
        recovered = []
        for backup in tuple(self.bpy.data.images):
            token = backup.get(self.TOKEN_KEY)
            if not token:
                continue
            target_id = backup.get(self.TARGET_KEY)
            target = next((item for item in self.bpy.data.images
                           if item != backup and item.get(self.TARGET_KEY) == target_id
                           and item.get(self.ACTIVE_KEY) == token), None)
            if target is None:
                self.bpy.data.images.remove(backup)
                recovered.append((token, "orphan_removed"))
                continue
            candidate_digest = backup.get(self.DIGEST_KEY, "")
            committed = (backup.get(self.STATE_KEY) == "committed"
                         and candidate_digest
                         and self._digest(self._pixels(target)) == candidate_digest)
            if committed:
                target.pop(self.ACTIVE_KEY, None)
                outcome = "committed_preserved"
            else:
                self._write(target, self._pixels(backup))
                target.pop(self.ACTIVE_KEY, None)
                outcome = "previous_restored"
            self.bpy.data.images.remove(backup)
            recovered.append((token, outcome))
        return tuple(recovered)

    def _backup(self, token, required=True):
        backup = next((image for image in self.bpy.data.images
                       if image.get(self.TOKEN_KEY) == token), None)
        if backup is None and required:
            raise RuntimeError("Persistent Image recovery backing is missing")
        return backup

    @staticmethod
    def _write(image, payload):
        import numpy as np
        values = np.asarray(payload, dtype=np.float32)
        if values.ndim != 1 or values.size != len(image.pixels):
            raise RuntimeError("Recovery backing no longer matches the target Image")
        image.use_half_precision = False
        image.pixels.foreach_set(values)
        image.update()


def publish_blender_image(image, rgba, *, operation, bpy_module=None):
    """Stage a verified float32 Image overwrite with a packed prior backing.

    The returned publication remains recoverable until ``finalize`` is called
    after the matching project-workflow completion receipt.
    """
    import numpy as np

    values = np.asarray(rgba, dtype=np.float32)
    if values.ndim != 3 or values.shape[-1] != 4:
        raise ValueError("Bake Image result must have a height × width × RGBA shape")
    width, height = (int(image.size[0]), int(image.size[1]))
    if values.shape[:2] != (height, width):
        raise ValueError("Bake Image result dimensions do not match the destination")
    if not getattr(image, "is_float", False) or getattr(image, "use_half_precision", False):
        raise RuntimeError("Bake destination must be a full-precision float Image")
    values = np.array(values, dtype=np.float32, copy=True)
    flat = values.ravel()

    def write(target, payload):
        target.use_half_precision = False
        target.pixels.foreach_set(payload)
        target.update()
        target.pack()

    def verify(target, payload):
        readback = np.empty(len(target.pixels), dtype=np.float32)
        target.pixels.foreach_get(readback)
        return (target.packed_file is not None
                and np.array_equal(readback, payload))

    publication = ImagePublication(
        image, backup_store=BlenderImageBackupStore(bpy_module),
        write=write, verify=verify, image_id=image.as_pointer(), operation=operation,
    )
    publication.stage(flat)
    return publication


__all__ = (
    "BlenderImageBackupStore", "ImageBackup", "ImagePublication",
    "publish_blender_image",
)

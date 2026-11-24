"""Order lifecycle fences around Blender file and undo transitions."""

# pg-book: technical-report/en#next-policy.resources

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

from .publication import PublicationDeferred


@dataclass(frozen=True)
class _Recovery:
    node_pointers: Optional[frozenset[int]]


class LifecycleCoordinator:
    def __init__(self):
        self._phase = "ready"
        self._generation = 0
        self._recovery = None

    @property
    def changing(self):
        return self._phase == "changing"

    @property
    def reset_pending(self):
        return self._phase != "ready"

    def admits(self, recovery, pointer=None):
        if recovery is None:
            return not self.reset_pending
        return (self._phase == "pending" and self._recovery is recovery
                and (pointer is None or recovery.node_pointers is None
                     or pointer in recovery.node_pointers))

    def begin(self, operations):
        """Run every cleanup step and return failures after the safety fence."""
        self._generation += 1
        generation = self._generation
        self._phase = "changing"
        self._recovery = None
        failures = []
        for operation in operations:
            if self._generation != generation:
                break
            try:
                operation()
            except Exception as error:
                failures.append(error)
        return tuple(failures)

    def finish(self, invalidate_render_preflights):
        if not self.changing:
            return
        generation = self._generation
        invalidate_render_preflights()
        if self._generation == generation:
            self._phase = "pending"

    def reset(self):
        """Clear the fence after successful extension teardown."""
        self._generation += 1
        self._phase = "ready"
        self._recovery = None

    @contextmanager
    def _admit_recovery(self, node_pointers):
        if self._phase != "pending" or self._recovery is not None:
            raise PublicationDeferred("Grade lifecycle recovery is unavailable")
        recovery = _Recovery(node_pointers)
        self._recovery = recovery
        try:
            yield recovery
        finally:
            if self._recovery is recovery:
                self._recovery = None

    @contextmanager
    def render_recovery(self, node_pointers):
        """Admit the exact render's nodes without completing global recovery."""
        if not self.reset_pending:
            yield None
        else:
            with self._admit_recovery(frozenset(node_pointers)) as recovery:
                yield recovery

    def reconcile(self, release_resources, repair_outputs, fail_closed):
        """Return the next timer interval after applying the recovery effects."""
        if not self.reset_pending:
            return None
        try:
            with self._admit_recovery(None) as recovery:
                try:
                    release_resources()
                    if self.admits(recovery):
                        repair_outputs(recovery)
                except PublicationDeferred:
                    return 0.02
                except Exception as error:
                    if self.admits(recovery):
                        fail_closed(error, recovery)
                    return 0.2
                if not self.admits(recovery):
                    return 0.02
                self._phase = "ready"
        except PublicationDeferred:
            return 0.02
        return None

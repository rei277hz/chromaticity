"""Plain compositor binding and completion facts shared with native callbacks."""

from collections import deque
from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class MembershipEffects:
    previous: dict

    @property
    def reevaluate_scenes(self):
        return {scene for (scene, _node), old in self.previous.items() if old is None}


class CompositorReceipts:
    def __init__(self):
        self._lock = threading.Lock()
        self._bindings = {}
        self._completed = {}
        self._pending = deque()
        self._serial = 0

    def bind(self, nodes_by_scene, *, baked_nodes=()):
        """Bind live outputs under a fresh generation and withdraw baked outputs."""
        previous = {}
        with self._lock:
            if nodes_by_scene:
                self._serial += 1
            for scene, nodes in nodes_by_scene.items():
                bindings = self._bindings.setdefault(scene, {})
                for node in nodes:
                    previous[scene, node] = bindings.get(node)
                    bindings[node] = self._serial
            if baked_nodes:
                for scene, bindings in tuple(self._bindings.items()):
                    for node in baked_nodes:
                        if node in bindings:
                            previous[scene, node] = bindings.pop(node)
                    if not bindings:
                        del self._bindings[scene]
        return previous

    def reconcile(self, nodes_by_scene):
        """Match scene membership, preserving generations for unchanged pairs."""
        desired = {
            (scene, node)
            for scene, nodes in nodes_by_scene.items()
            for node in nodes
        }
        previous = {}
        with self._lock:
            current = {
                (scene, node)
                for scene, bindings in self._bindings.items()
                for node in bindings
            }
            removed = current - desired
            added = desired - current
            if added:
                self._serial += 1
            for scene, node in removed:
                bindings = self._bindings[scene]
                previous[scene, node] = bindings.pop(node)
                if not bindings:
                    del self._bindings[scene]
            for scene, node in added:
                previous[scene, node] = None
                self._bindings.setdefault(scene, {})[node] = self._serial
        return MembershipEffects(previous)

    def restore(self, previous):
        with self._lock:
            for (scene, node), generation in previous.items():
                bindings = self._bindings.setdefault(scene, {})
                if generation is None:
                    bindings.pop(node, None)
                else:
                    bindings[node] = generation
                if not bindings:
                    self._bindings.pop(scene, None)

    def snapshot(self, scene):
        with self._lock:
            return dict(self._bindings.get(scene, {}))

    def completed(self, receipt):
        """Queue only plain successful terminal receipts from any thread."""
        if receipt is None or not receipt.successful:
            return
        with self._lock:
            self._pending.append((receipt.identity, receipt.epoch, receipt.snapshot))

    def collect(self):
        """Accept later successful snapshots on the main-thread adapter tick."""
        with self._lock:
            while self._pending:
                scene, epoch, snapshot = self._pending.popleft()
                previous = self._completed.get(scene)
                if previous is None or epoch > previous[0]:
                    self._completed[scene] = epoch, dict(snapshot)

    def awaiting(self, node, scenes):
        """Current binding differs from the last completed visible snapshot."""
        with self._lock:
            for scene in scenes:
                generation = self._bindings.get(scene, {}).get(node)
                if generation is None:
                    return True
                completed = self._completed.get(scene)
                if completed is None or completed[1].get(node) != generation:
                    return True
        return False

    def node_identities(self):
        with self._lock:
            return frozenset(node for bindings in self._bindings.values() for node in bindings)

    def known(self, node):
        with self._lock:
            return any(node in bindings for bindings in self._bindings.values())

    def forget(self, node):
        with self._lock:
            for scene, bindings in tuple(self._bindings.items()):
                bindings.pop(node, None)
                if not bindings:
                    del self._bindings[scene]
            for _epoch, snapshot in self._completed.values():
                snapshot.pop(node, None)
            self._pending = deque(
                (scene, epoch, tuple((identity, generation)
                                     for identity, generation in snapshot if identity != node))
                for scene, epoch, snapshot in self._pending)

    def reset(self):
        with self._lock:
            self._bindings.clear()
            self._completed.clear()
            self._pending.clear()

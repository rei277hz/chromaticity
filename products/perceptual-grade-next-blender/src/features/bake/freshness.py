"""Small source revisions and durable, metadata-only bake receipts.

No operation here reads image pixels. Runtime ID keys deliberately never enter
persisted receipts; load/undo rebuild their baselines from restored provenance.
"""

# pg-book: technical-report/en#next-policy.bake

from dataclasses import dataclass
import json
from typing import Optional


RECEIPT_SCHEMA = 1


@dataclass(frozen=True)
class BakeReceipt:
    signature: str
    backend_signature: Optional[str] = None
    source_invalidated: bool = False

    def encode(self):
        record = {"schema": RECEIPT_SCHEMA, "signature": self.signature}
        if self.backend_signature is not None:
            record["backend_signature"] = self.backend_signature
        if self.source_invalidated:
            record["source_invalidated"] = True
        return json.dumps(record, separators=(",", ":"), sort_keys=True)

    @classmethod
    def decode(cls, value) -> Optional["BakeReceipt"]:
        try:
            record = json.loads(value)
            signature = record.get("signature")
            backend_signature = record.get("backend_signature")
            source_invalidated = record.get("source_invalidated", False)
            if (type(record.get("schema")) is int
                    and record["schema"] == RECEIPT_SCHEMA
                    and isinstance(signature, str) and signature
                    and (backend_signature is None
                         or isinstance(backend_signature, str) and backend_signature)
                    and type(source_invalidated) is bool):
                return cls(signature, backend_signature, source_invalidated)
        except (AttributeError, TypeError, ValueError):
            pass
        return None


def source_key(value):
    value = getattr(value, "original", value)
    uid = getattr(value, "session_uid", None)
    if uid is None:
        pointer = getattr(value, "as_pointer", None)
        uid = pointer() if pointer is not None else id(value)
    return type(value).__name__, int(uid)


class BakeSources:
    """Track only the IDs used by bound receipts or pending requests."""

    def __init__(self):
        self.generations = {}
        self.bindings = {}
        self.readers = {}

    def clear(self):
        self.generations.clear()
        self.bindings.clear()
        self.readers.clear()

    def forget(self, node_key):
        previous = self.bindings.pop(node_key, ())
        for key, _generation, _dirty in previous:
            readers = self.readers.get(key)
            if readers is not None:
                readers.discard(node_key)
                if not readers:
                    self.readers.pop(key, None)

    def snapshot(self, dependencies):
        facts = {}
        for value in dependencies:
            key = source_key(value)
            facts[key] = (key, self.generations.get(key, 0),
                          bool(getattr(value, "is_dirty", False)))
        return tuple(sorted(facts.values()))

    def bind(self, node_key, dependencies):
        snapshot = self.snapshot(dependencies)
        # Do not retire/recreate shared generations while replacing a binding.
        previous = self.bindings.get(node_key, ())
        self.bindings[node_key] = snapshot
        current_keys = {key for key, _generation, _dirty in snapshot}
        for key in current_keys:
            self.readers.setdefault(key, set()).add(node_key)
        for key, _generation, _dirty in previous:
            if key not in current_keys:
                readers = self.readers[key]
                readers.discard(node_key)
                if not readers:
                    self.readers.pop(key)
        return snapshot

    def matches(self, snapshot):
        return all(self.generations.get(tuple(key), 0) == generation
                   for key, generation, _dirty in snapshot)

    def changed(self, node_key, dependencies):
        baseline = self.bindings.get(node_key)
        if baseline is None:
            return False
        current = self.snapshot(dependencies)
        if tuple((key, generation) for key, generation, _dirty in current) != tuple(
                (key, generation) for key, generation, _dirty in baseline):
            return True
        return any(dirty and not old_dirty
                   for (_, _, dirty), (_, _, old_dirty) in zip(current, baseline))

    def source_changed(self, node_key, dependencies):
        """Detect changes to retained source IDs without treating rerouting as edits."""
        baseline = self.bindings.get(node_key)
        if baseline is None:
            return False
        previous = {key: (generation, dirty)
                    for key, generation, dirty in baseline}
        current = self.snapshot(dependencies)
        return any(
            key in previous and (
                generation != previous[key][0]
                or (dirty and not previous[key][1])
            )
            for key, generation, dirty in current
        )

    def invalidate(self, dependencies):
        keys = set()
        for value in dependencies:
            try:
                keys.add(source_key(value))
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        affected = set()
        for key in keys:
            if key in self.readers:
                self.generations[key] = self.generations.get(key, 0) + 1
                affected.update(self.readers[key])
        return affected

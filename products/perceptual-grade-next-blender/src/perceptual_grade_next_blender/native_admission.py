"""Main-thread reader/writer admission for native datablock publication."""

from dataclasses import dataclass
import threading
import uuid


@dataclass(frozen=True)
class NativeLease:
    token: str
    mode: str
    identity: str


_LOCK = threading.RLock()
_READERS = {}
_WRITER = None


def _host_readers_idle():
    try:
        from .scope_runtime import _DEPSGRAPH_SETTLED, _native_readers_idle
        return bool(_DEPSGRAPH_SETTLED and _native_readers_idle())
    except (ImportError, AttributeError, ReferenceError, RuntimeError):
        return False


def can_acquire_reader(*, reader_probe=None):
    probe = _host_readers_idle if reader_probe is None else reader_probe
    with _LOCK:
        return _WRITER is None and bool(probe())


def acquire_reader(identity, *, reader_probe=None):
    """Acquire an exact native-read lease, or return None while fenced."""
    identity = str(identity)
    if not identity:
        raise ValueError("native reader lease requires an identity")
    probe = _host_readers_idle if reader_probe is None else reader_probe
    with _LOCK:
        if _WRITER is not None or not probe():
            return None
        token = uuid.uuid4().hex
        lease = NativeLease(token, "reader", identity)
        _READERS[token] = lease
        return lease


def acquire_writer(identity, *, reader_probe=None):
    """Acquire exclusive native publication admission, or return None."""
    global _WRITER
    identity = str(identity)
    if not identity:
        raise ValueError("native writer lease requires an identity")
    probe = _host_readers_idle if reader_probe is None else reader_probe
    with _LOCK:
        if _WRITER is not None or _READERS or not probe():
            return None
        _WRITER = NativeLease(uuid.uuid4().hex, "writer", identity)
        return _WRITER


def release(lease):
    """Release only the exact lease returned by this module."""
    global _WRITER
    if not isinstance(lease, NativeLease):
        return False
    with _LOCK:
        if lease.mode == "reader":
            if _READERS.get(lease.token) != lease:
                return False
            del _READERS[lease.token]
            return True
        if lease.mode == "writer" and _WRITER == lease:
            _WRITER = None
            return True
        return False


def reader_count():
    with _LOCK:
        return len(_READERS)


def writer_active():
    with _LOCK:
        return _WRITER is not None


__all__ = (
    "NativeLease", "acquire_reader", "acquire_writer", "can_acquire_reader",
    "reader_count", "release", "writer_active",
)

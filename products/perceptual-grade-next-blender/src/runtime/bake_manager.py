"""Foreground request coordinator for serialized native bake jobs."""

# pg-book: technical-report/en#next-policy.bake

from collections import deque
from concurrent.futures import CancelledError
from contextlib import nullcontext
import shutil

from ..policy import bake as bake_policy
from .publication import PublicationDeferred


class BakeManager:
    """Own accepted requests until their helper work and callbacks retire.

    ``current_signature(node, route)`` must return the current effective bake
    signature or ``None`` when it cannot be established. ``publish_callback``
    is called only after the policy authorizes publication and has the legacy
    shape ``(entry, result, error)``. It writes pixels and metadata, retaining
    its own rollback snapshot, but must leave Use Bake disabled. Activation is
    a separate ``activate_callback(entry, result)`` authorized only by the
    policy's ``activate`` effect. A rollback callback receives
    ``(entry, result, error)``; a failure callback receives ``(entry, error)``.
    ``publication_context()`` optionally supplies a host admission scope for
    publication, activation and rollback. A deferred scope preserves the ready
    result until a later poll; callbacks must not enter a second admission.
    """

    def __init__(self, *, freeze_snapshot, create_job):
        self.freeze_snapshot = freeze_snapshot
        self.create_job = create_job
        self.queue = deque()
        self.publication_queue = deque()
        self.active = None
        self.jobs = {}
        self.closed = False

    @staticmethod
    def _node_key(node):
        try:
            pointer = int(node.as_pointer())
            if pointer:
                return pointer
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        return id(node)

    @staticmethod
    def _notify_failure(entry, error):
        callback = entry.get("failure_callback")
        if callback is None:
            return
        try:
            callback(entry, error)
        except Exception as callback_error:
            entry.setdefault("callback_errors", []).append(callback_error)

    @staticmethod
    def _resolve_signature(entry):
        try:
            value = entry["current_signature"](entry["node"], entry["route"])
        except (ReferenceError, RuntimeError, TypeError, ValueError, AttributeError):
            return None
        return value if isinstance(value, str) and value else None

    def _event(self, entry, event):
        entry["state"], effects = bake_policy.step(entry["state"], event)
        return effects

    def request(self, node, route, publish_callback, current_signature,
                activate_callback=None, rollback_callback=None,
                failure_callback=None, publication_context=None):
        if self.closed:
            raise RuntimeError("Bake manager is closed")
        if not callable(publish_callback) or not callable(current_signature):
            raise TypeError("Bake publication and current-signature callbacks are required")
        if publication_context is not None and not callable(publication_context):
            raise TypeError("Bake publication context must be a context-manager factory")
        node_key = self._node_key(node)
        if not bake_policy.can_enqueue(len(self.jobs), node_key in self.jobs):
            raise RuntimeError("Bake queue is full or this node already has a request")
        route = dict(route)
        signature = route.get("request_signature")
        if not isinstance(signature, str) or not signature:
            raise ValueError("Bake request requires a nonempty signature")
        if current_signature(node, route) != signature:
            raise RuntimeError("Bake inputs changed before the request was accepted")

        root, snapshot, images = self.freeze_snapshot(route)
        try:
            inputs = {
                "snapshot_path": str(snapshot),
                "artifact_dir": str(root), "images": images,
                "route": route,
            }
            entry = {
                "node": node, "node_key": node_key,
                "route": route, "inputs": inputs,
                "root": root, "publish_callback": publish_callback,
                "activate_callback": activate_callback,
                "rollback_callback": rollback_callback,
                "failure_callback": failure_callback,
                "current_signature": current_signature,
                "publication_context": publication_context,
                "state": bake_policy.new(),
            }
            effects = self._event(entry, bake_policy.Event(
                "request", signature,
            ))
            if effects.action != "enqueue":
                raise RuntimeError("Bake policy rejected the request")
        except BaseException:
            self._remove_files(root)
            raise
        self.queue.append(entry)
        self.jobs[node_key] = entry

    def invalidate(self, node, signature):
        """Withdraw stale demand; active helper ownership lasts until terminal."""
        return self._withdraw(self.jobs.get(self._node_key(node)), "invalidate", signature)

    def withdraw(self, node_key):
        """Withdraw a disposed node by its accepted key, without touching RNA."""
        return self._withdraw(self.jobs.get(node_key), "invalidate")

    def _withdraw(self, entry, kind, signature=None):
        if entry is None:
            return False
        effects = self._event(entry, bake_policy.Event(
            kind,
            current_signature=signature,
        ))
        if effects.action == "cancel":
            if self.active is entry and entry.get("job") is not None:
                try:
                    entry["job"].cancel()
                except Exception as error:
                    entry.setdefault("callback_errors", []).append(error)
            return True
        if effects.action == "discard":
            self._retire(entry)
            return True
        return False

    def _remove_files(self, root):
        shutil.rmtree(root, ignore_errors=True)

    def _retire(self, entry):
        for queue in (self.queue, self.publication_queue):
            try:
                queue.remove(entry)
            except ValueError:
                pass
        if self.jobs.get(entry["node_key"]) is entry:
            self.jobs.pop(entry["node_key"], None)
        self._remove_files(entry["root"])

    def _failure(self, entry, error):
        self._notify_failure(entry, error)
        self._retire(entry)

    def _publish(self, entry, result):
        signature = self._resolve_signature(entry)
        if signature != entry["route"]["request_signature"]:
            self._withdraw(entry, "invalidate", signature)
            return False
        factory = entry.get("publication_context")
        try:
            scope = nullcontext() if factory is None else factory()
            with scope:
                self._publish_admitted(entry, result)
        except PublicationDeferred as error:
            if entry["state"].phase == "ready":
                return True
            self._failure(entry, error)
        except Exception as error:
            self._failure(entry, error)
        return False

    def _publish_admitted(self, entry, result):
        """Consume the complete publication transaction within host admission."""
        effects = self._event(entry, bake_policy.Event(
            "publish",
            current_signature=self._resolve_signature(entry),
        ))
        if effects.action == "discard":
            self._retire(entry)
            return
        if effects.action != "publish":
            raise RuntimeError("Bake policy did not authorize image publication")
        publication_error = None
        try:
            if entry["publish_callback"](entry, result, None) is False:
                raise RuntimeError("Bake image publication did not commit")
        except Exception as error:
            publication_error = error
        effects = self._event(entry, bake_policy.Event(
            "published",
            current_signature=self._resolve_signature(entry),
            successful=publication_error is None,
            error=None if publication_error is None else str(publication_error),
        ))
        if effects.action == "activate":
            try:
                callback = entry["activate_callback"]
                if callback is not None and callback(entry, result) is False:
                    raise RuntimeError("Bake activation did not commit")
            except Exception as error:
                publication_error = error
            effects = self._event(entry, bake_policy.Event(
                "activated",
                current_signature=self._resolve_signature(entry),
                successful=publication_error is None,
                error=None if publication_error is None else str(publication_error),
            ))
        if effects.action == "rollback":
            error = publication_error or RuntimeError(
                effects.error or "Bake inputs changed during publication")
            error = self._rollback(entry, result, error)
            self._notify_failure(entry, error)
        elif effects.action != "retire":
            self._notify_failure(entry, RuntimeError("Bake publication did not settle"))
        self._retire(entry)

    def _rollback(self, entry, result, error):
        callback = entry.get("rollback_callback")
        if callback is None:
            return error
        try:
            callback(entry, result, error)
        except Exception as rollback_error:
            error = ExceptionGroup("Bake rollback failed", [error, rollback_error])
        return error

    def _retry_publications(self):
        pending = tuple(self.publication_queue)
        self.publication_queue.clear()
        for entry in pending:
            if self.jobs.get(entry["node_key"]) is not entry:
                continue
            if self._publish(entry, entry["result"]):
                self.publication_queue.append(entry)

    def cancel_all(self):
        """Withdraw all accepted work while retaining active helper ownership."""
        self._withdraw_all("invalidate")

    def _withdraw_all(self, event_kind):
        for entry in tuple(self.jobs.values()):
            self._withdraw(entry, event_kind)

    def _start_next(self):
        while self.active is None and self.queue and not self.closed:
            entry = self.queue.popleft()
            signature = self._resolve_signature(entry)
            if (signature != entry["route"]["request_signature"]
                    and self._withdraw(entry, "invalidate", signature)):
                continue
            effects = self._event(entry, bake_policy.Event(
                "start",
            ))
            if effects.action != "start":
                self._retire(entry)
                continue
            self.active = entry
            try:
                entry["job"] = self.create_job(entry["inputs"])
            except Exception as error:
                self.active = None
                effects = self._event(entry, bake_policy.Event(
                    "completed",
                    current_signature=entry["route"]["request_signature"], successful=False,
                    error=str(error),
                ))
                if effects.action == "retire":
                    self._failure(entry, error)
                else:
                    self._retire(entry)

    def _finish_active(self, entry, result):
        self.active = None
        if isinstance(result, CancelledError):
            effects = self._event(entry, bake_policy.Event(
                "cancelled" if entry["state"].phase == "cancelling" else "completed",
                error=str(result),
            ))
            if effects.action == "retire":
                self._retire(entry)
            return
        if isinstance(result, BaseException):
            signature = self._resolve_signature(entry)
            effects = self._event(entry, bake_policy.Event(
                "completed",
                current_signature=signature, successful=False, error=str(result),
            ))
            if effects.action == "retire":
                self._failure(entry, result)
            else:
                self._retire(entry)
            return

        receipt_matches = (
            isinstance(result, dict)
            and result.get("request_signature") == entry["route"]["request_signature"]
        )
        signature = self._resolve_signature(entry)
        effects = self._event(entry, bake_policy.Event(
            "completed",
            current_signature=signature if receipt_matches else None,
            successful=receipt_matches,
            error=None if receipt_matches else "Bake helper returned a mismatched receipt",
        ))
        if effects.action == "discard":
            self._retire(entry)
            return
        if entry["state"].phase == "ready":
            entry["result"] = result
            self.publication_queue.append(entry)
            return
        if effects.action == "retire":
            self._failure(entry, RuntimeError(effects.error or "Bake helper failed"))
            return
        self._retire(entry)

    def poll(self):
        if self.closed:
            return bool(self.jobs)
        if self.active is None:
            self._start_next()
        entry = self.active
        if entry is not None:
            try:
                result = entry["job"].advance()
            except Exception as error:
                result = error
            if result is not None:
                self._finish_active(entry, result)
        if self.publication_queue:
            self._retry_publications()
        return self.active is not None or bool(self.queue) or bool(self.publication_queue)

    def begin_shutdown(self):
        """Stop accepting requests and withdraw work before the helper closes."""
        if not self.closed:
            self.closed = True
            self._withdraw_all("close")

    def finish_shutdown(self):
        """Release the remaining snapshot after the capture helper has retired."""
        if not self.closed:
            raise RuntimeError("Bake shutdown has not started")
        if self.active is not None and not self.active["job"].retired():
            raise RuntimeError("Bake capture job has not retired")
        for entry in tuple(self.jobs.values()):
            effects = self._event(entry, bake_policy.Event(
                "cancelled",
            ))
            if effects.action == "retire":
                self._retire(entry)
        self.queue.clear()
        self.publication_queue.clear()
        self.active = None


__all__ = ("BakeManager",)

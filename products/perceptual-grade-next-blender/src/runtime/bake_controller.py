"""Blender-facing Bake orchestration, receipts, and image publication."""

# pg-book: technical-report/en#next-policy.bake

import json
from pathlib import Path
import threading
from uuid import uuid4

import numpy as np

from ..policy import bake as bake_policy
from . import bake_graph, bake_routes
from .bake_freshness import BakeReceipt, BakeSources
from .bake_manager import BakeManager
from .image_publication import ImageSnapshot, write_metadata
from .publication import PublicationDeferred


BAKE_SCHEMA = 2
BAKE_IMAGE_SCHEMA = "_pg_next_bake_schema"
BAKE_SOURCE_VERIFICATION = "_pg_next_bake_source_verification"
BAKE_SOURCE_VERIFICATION_VERSION = 1
BAKE_DOMAIN = "_pg_next_bake_domain"
BAKE_SIGNATURE = "_pg_next_bake_signature"
BAKE_OPERATION = "_pg_next_bake_operation"
BAKE_WIDTH = "_pg_next_bake_width"
BAKE_HEIGHT = "_pg_next_bake_height"
BAKE_ERROR = "_pg_next_bake_error"
BAKE_CONTEXT = "_pg_next_bake_context"
BAKE_NODE_SIGNATURE = "_pg_next_bake_node_receipt"


class BakeController:
    def __init__(self, bpy, *, gate, nodes, prepare_kernels, wrapper,
                 ensure_wrapper, synchronize_output, live_error, fail_output,
                 block_nodes, timer_callback):
        self.bpy = bpy
        self.gate = gate
        self.nodes = nodes
        self.prepare_kernels = prepare_kernels
        self.wrapper = wrapper
        self.ensure_wrapper = ensure_wrapper
        self.synchronize_output = synchronize_output
        self.live_error = live_error
        self.fail_output = fail_output
        self.block_nodes = block_nodes
        self.timer_callback = timer_callback
        self.manager = None
        self.sources = BakeSources()
        self.mode_updates = set()
        self.image_updates = set()
        self.pending_invalidations = set()
        self.pending_reconciliations = set()

    def start(self, *, freeze_snapshot, create_job):
        if self.manager is None:
            self.manager = BakeManager(freeze_snapshot=freeze_snapshot, create_job=create_job)

    def begin_shutdown(self):
        if self.manager is not None:
            self.manager.begin_shutdown()

    def finish_shutdown(self):
        if self.manager is not None:
            self.manager.finish_shutdown()

    def stop_timer(self):
        timers = self.bpy.app.timers
        if timers.is_registered(self.timer_callback):
            timers.unregister(self.timer_callback)
        self.manager = None

    def busy(self, node):
        return self.manager is not None and node.as_pointer() in self.manager.jobs

    def cancel(self, node):
        if self.manager is not None:
            self.manager.withdraw(node.as_pointer())

    def withdraw_all(self):
        if self.manager is not None:
            self.manager.cancel_all()

    def forget(self, pointer):
        self.sources.forget(pointer)
        self.sources.forget(("request", pointer))
        self.pending_invalidations.discard(pointer)
        self.pending_reconciliations.discard(pointer)
        if self.manager is not None:
            self.manager.withdraw(pointer)

    def clear(self):
        self.sources.clear()
        self.pending_invalidations.clear()
        self.pending_reconciliations.clear()

    def image_poll(self, _node, image):
        if image is None:
            return True
        try:
            return (image.library is None and image.get(BAKE_IMAGE_SCHEMA) == BAKE_SCHEMA
                    and image.source in {"FILE", "GENERATED"} and image.is_float
                    and image.packed_file is not None and not image.is_dirty
                    and image.get(BAKE_DOMAIN) in {"EMPTY", "IMAGE", "UV", "COMPOSITOR"})
        except (AttributeError, ReferenceError, RuntimeError):
            return False

    def ensure_timer(self):
        """Keep the foreground bake queue alive after an idle timer retires."""
        if self.manager is None:
            return
        try:
            if not self.bpy.app.timers.is_registered(self.timer_callback):
                self.bpy.app.timers.register(self.timer_callback, first_interval=0.02,
                                             persistent=True)
        except (AttributeError, RuntimeError, TypeError):
            return

    def image_valid(self, node):
        return bake_graph.image_valid(node, getattr(node, "pg_bake_image", None))

    def set_mode(self, node, enabled, *, reconcile=True):
        policy = bake_policy.output_policy(
            bool(enabled), self.image_valid(node),
            self.live_error(node),
        )
        enabled = policy.mode == "baked"
        pointer = node.as_pointer()
        self.mode_updates.add(pointer)
        try:
            node.pg_use_bake = enabled
        finally:
            self.mode_updates.discard(pointer)
        if not reconcile:
            return enabled
        try:
            with self.gate().graph_commit():
                self.synchronize_output(node, use_bake=enabled)
        except PublicationDeferred:
            self.pending_reconciliations.add(pointer)
            self.ensure_timer()
        else:
            self.pending_reconciliations.discard(pointer)
        return enabled

    def receipt_signature(self, node):
        receipt = BakeReceipt.decode(node.get(BAKE_NODE_SIGNATURE))
        return None if receipt is None else receipt.signature

    def write_receipt(self, node, signature, backend_signature=None,
                      source_invalidated=False):
        write_metadata(((node, BAKE_NODE_SIGNATURE,
                         None if signature is None else BakeReceipt(
                             signature, backend_signature, source_invalidated,
                         ).encode()),))

    def _image_metadata(self, image, route, result):
        return (
            (image, BAKE_IMAGE_SCHEMA, BAKE_SCHEMA),
            (image, BAKE_SOURCE_VERIFICATION, BAKE_SOURCE_VERIFICATION_VERSION),
            (image, BAKE_DOMAIN, str(route.get("domain", "COMPOSITOR"))),
            (image, BAKE_SIGNATURE, route["receipt_signature"]),
            (image, BAKE_OPERATION, str(uuid4().hex)),
            (image, BAKE_WIDTH, int(result["width"])),
            (image, BAKE_HEIGHT, int(result["height"])),
            (image, "_pg_next_bake_uv_map", route.get("uv_map")),
            (image, "_pg_next_bake_interpolation", "Linear"),
            (image, "_pg_next_bake_extension", "REPEAT"),
        )

    def _set_image(self, node, image):
        """Set a transaction-owned binding without treating it as a user bind."""
        pointer = node.as_pointer()
        self.image_updates.add(pointer)
        try:
            node.pg_bake_image = image
        finally:
            self.image_updates.discard(pointer)

    def _publish(self, entry, result, error):
        """Consume the bake publish effect inside the manager's admitted scope."""
        node = entry["node"]
        publish_failed = False
        try:
            if error is not None:
                raise error
            route = entry["route"]
            path = Path(result["path"]).resolve()
            if not path.is_relative_to(entry["root"].resolve()):
                raise RuntimeError("Bake artifact is outside its request directory")
            if not path.is_file():
                raise RuntimeError("Bake artifact is unavailable")
            width, height = int(result["width"]), int(result["height"])
            if min(width, height) < 1 or width * height * 16 > bake_routes.MAX_PIXEL_BYTES:
                raise RuntimeError("Bake artifact dimensions exceed the pixel budget")
            source = self.bpy.data.images.load(str(path), check_existing=False)
            created = False
            image = None
            source.colorspace_settings.name = "Non-Color"
            source.alpha_mode = "CHANNEL_PACKED"
            if tuple(source.size) != (width, height) or source.channels != 4 or not source.is_float:
                raise RuntimeError("Bake artifact is not the expected float RGBA image")
            values = np.empty(width * height * 4, dtype=np.float32)
            source.pixels.foreach_get(values)
            if not np.isfinite(values).all():
                raise RuntimeError("Bake artifact contains nonfinite pixels")
            image = node.pg_bake_image
            created = image is None
            if not created and not bake_graph.image_allowed(node, image):
                raise RuntimeError("Bake destination is not a managed float Image")
            if created:
                image = self.bpy.data.images.new(
                    "Perceptual Grade Bake", width, height, alpha=True, float_buffer=True,
                )
            entry["bake_image"] = image
            entry["bake_created_image"] = created
            entry["bake_receipt_snapshot"] = tuple(
                (node, key, node.get(key)) for key in (BAKE_NODE_SIGNATURE, BAKE_CONTEXT)
            )
            if not created:
                readers = tuple(reader for reader in self.nodes()
                                if bake_routes.is_bake_target(reader)
                                and reader.pg_bake_image == image)
                entry["bake_reader_snapshots"] = tuple(
                    (reader, bool(reader.pg_use_bake), reader.get(BAKE_NODE_SIGNATURE))
                    for reader in readers
                )
                for reader, selected, _receipt in entry["bake_reader_snapshots"]:
                    if selected:
                        self.set_mode(reader, False)
            metadata = self._image_metadata(image, route, result)
            entry["bake_old_size"] = tuple(image.size)
            entry["bake_snapshot"] = None if created else ImageSnapshot.capture(image, metadata)
            # Changing interpretation can reload the packed buffer at its old size.
            if image.colorspace_settings.name != "Non-Color":
                image.colorspace_settings.name = "Non-Color"
            if image.alpha_mode != "CHANNEL_PACKED":
                image.alpha_mode = "CHANNEL_PACKED"
            if getattr(image, "use_half_precision", False):
                image.use_half_precision = False
            if tuple(image.size) != (width, height):
                image.scale(width, height)
            image.pixels.foreach_set(values)
            image.update()
            image.pack()
            if image.packed_file is None or image.is_dirty:
                raise RuntimeError("Bake Image could not be packed")
            write_metadata(metadata)
            image.update()
            if created:
                self._set_image(node, image)
        except Exception:
            publish_failed = True
            raise
        finally:
            if "source" in locals() and source is not None:
                try:
                    self.bpy.data.images.remove(source, do_unlink=True)
                except Exception:
                    if not publish_failed:
                        raise

    def _activate(self, entry, _result):
        node = entry["node"]
        route = entry["route"]
        image = getattr(node, "pg_bake_image", None)
        if image is None or image.get(BAKE_SIGNATURE) != route["receipt_signature"]:
            raise RuntimeError("Bake Image changed before activation")
        if self.wrapper(node) is None:
            self.ensure_wrapper(node)
        node[BAKE_CONTEXT] = json.dumps(self._context(route), separators=(",", ":"))
        self.write_receipt(node, route["receipt_signature"],
                            bake_routes.backend_signature(route))
        self._remember_observation(node)
        self.set_mode(node, True)
        if not node.pg_use_bake:
            raise RuntimeError("Bake output could not be activated")
        write_metadata(((node, BAKE_ERROR, None),))
        self._tag_readers(image, updated_node=node)
        for reader, selected, _receipt in entry.get("bake_reader_snapshots", ()):
            if reader != node and selected and self.toggle_available(reader):
                self.set_mode(reader, True)
        self.ensure_timer()

    def _tag_readers(self, image, *, updated_node=None):
        if updated_node is not None:
            self.mark_sources((image,))
        for reader in self.nodes():
            if bake_routes.is_bake_target(reader) and reader.pg_bake_image == image:
                if updated_node is not None and reader != updated_node:
                    self._persist_source_change(reader)
                self.synchronize_output(reader, use_bake=reader.pg_use_bake)
                reader.id_data.update_tag()
                if reader.node_tree is not None:
                    reader.node_tree.update_tag()

    def _rollback(self, entry, _result, error):
        image = entry.get("bake_image")
        snapshot = entry.get("bake_snapshot")
        node = entry.get("node")
        try:
            if image is None:
                return
            if entry.get("bake_created_image"):
                if node is not None:
                    if node.pg_bake_image == image:
                        self._set_image(node, None)
                    self.set_mode(node, False)
                    write_metadata(entry.get("bake_receipt_snapshot", ()))
                    self.sources.forget(node.as_pointer())
                if image.users == 0:
                    self.bpy.data.images.remove(image, do_unlink=True)
                return
            if snapshot is not None:
                old_size = entry.get("bake_old_size", tuple(image.size))
                snapshot.restore_properties(image)
                if tuple(image.size) != tuple(old_size):
                    image.scale(*old_size)
                image.pixels.foreach_set(snapshot.pixels)
                image.update()
                image.pack()
                if image.packed_file is None or image.is_dirty:
                    raise RuntimeError("Restored Bake Image could not be packed")
                write_metadata(snapshot.metadata)
                image.update()
            if node is not None:
                write_metadata(entry["bake_receipt_snapshot"])
                for reader, _selected, receipt in entry.get("bake_reader_snapshots", ()):
                    write_metadata(((reader, BAKE_NODE_SIGNATURE, receipt),))
                self.sources.forget(node.as_pointer())
            if snapshot is not None:
                self._tag_readers(image)
            if node is not None:
                node[BAKE_ERROR] = str(error)
                for reader, selected, _receipt in entry.get("bake_reader_snapshots", ()):
                    self.set_mode(reader, selected)
        except Exception as rollback_error:
            if image is not None:
                write_metadata(((image, BAKE_IMAGE_SCHEMA, None),))
                readers = tuple(candidate for candidate in self.nodes()
                                if bake_routes.is_bake_target(candidate)
                                and candidate.pg_bake_image == image)
                self.block_nodes(readers, rollback_error)
            raise ExceptionGroup("Bake Image rollback failed", [error, rollback_error])

    def tick(self):
        manager = self.manager
        if manager is None:
            return None
        keep_observing = False
        reconcile_failed = False
        try:
            pending = manager.poll()
        except Exception as error:
            print("Perceptual Grade Bake failed:", error)
            pending = bool(manager.jobs or manager.queue or manager.active
                           or manager.publication_queue)
        try:
            targets = {node.as_pointer(): node for node in self.nodes()
                       if bake_routes.is_bake_target(node)}
            self.pending_reconciliations.intersection_update(targets)
            receipt_keys = {pointer for pointer, node in targets.items()
                            if self.receipt_signature(node) is not None}
            keep_observing = bool(receipt_keys)
            tracked_nodes = tuple(
                node for pointer, node in targets.items()
                if (pointer in receipt_keys or pointer in manager.jobs
                    or pointer in self.pending_reconciliations)
            )
            if tracked_nodes or self.pending_invalidations:
                self.reconcile(tracked_nodes, inventory=targets)
        except Exception as error:
            print("Perceptual Grade Bake reconciliation failed:", error)
            reconcile_failed = True
        try:
            for key in tuple(self.sources.bindings):
                if isinstance(key, tuple) and key[1] not in manager.jobs:
                    self.sources.forget(key)
        except Exception as error:
            print("Perceptual Grade Bake source cleanup failed:", error)
            reconcile_failed = True
        if (pending or reconcile_failed
                or self.pending_reconciliations or self.pending_invalidations):
            return 0.02
        return 0.5 if keep_observing else None

    def _report_failure(self, entry, error):
        try:
            node = entry["node"]
            node[BAKE_ERROR] = str(error)
        except (AttributeError, ReferenceError, RuntimeError):
            return

    def current_signature(self, node, route):
        if not self.sources.matches(route["source_revisions"]):
            return None
        dependencies = []
        current = bake_routes.observe(node, route, dependencies=dependencies)["route"]
        if current is None or self.sources.changed(("request", node.as_pointer()), dependencies):
            return None
        return current["request_signature"]

    def _remember_observation(self, node):
        dependencies = []
        bake_routes.preview(node, self.stored_context(node), dependencies=dependencies)
        self.sources.bind(node.as_pointer(), dependencies)
        self.pending_invalidations.discard(node.as_pointer())

    def observed_signature(self, node, context, *, track_sources=False):
        dependencies = []
        observation = bake_routes.observe(node, context, dependencies=dependencies)
        route = observation["route"]
        if route is None:
            return None
        if track_sources:
            pointer = node.as_pointer()
            if self.sources.source_changed(pointer, dependencies):
                self._persist_source_change(node)
                self.sources.bind(pointer, dependencies)
            elif pointer not in self.sources.bindings:
                self.sources.bind(pointer, dependencies)
        return route["receipt_signature"]

    def _route(self, node, context, dependencies, upstream_grades):
        context = context or self.stored_context(node)
        route = bake_routes.describe(node, context, dependencies=dependencies,
                                     upstream_grades=upstream_grades)
        if route.get("width") is None or route.get("height") is None:
            route["width"] = int(node.pg_bake_width)
            route["height"] = int(node.pg_bake_height)
        route["source_revisions"] = self.sources.snapshot(dependencies)
        return route

    def _context(self, route):
        return {key: route[key] for key in (
            "scene", "owner_kind", "owner_name", "group_path", "object_name",
            "scene_key", "owner_key", "object_key", "root_key", "effect_name",
        ) if key in route}

    def stored_context(self, node):
        value = node.get(BAKE_CONTEXT)
        if not value:
            return None
        try:
            context = json.loads(value)
            if isinstance(context, dict):
                context["group_path"] = tuple(context.get("group_path") or ())
                return context
        except (TypeError, ValueError):
            return None
        return None

    def request(self, node, context):
        if self.manager is None:
            raise RuntimeError("Bake manager is unavailable")
        pointer = node.as_pointer()
        if pointer in self.manager.jobs:
            raise RuntimeError("This node already has a Bake request")
        dependencies = []
        upstream_grades = []
        with self.gate().commit():
            self.reconcile()
            route = self._route(node, context, dependencies, upstream_grades)
        self.prepare_kernels(node, upstream_grades)
        with self.gate().commit():
            if self.wrapper(node) is None:
                self.ensure_wrapper(node)
            write_metadata(((node, BAKE_ERROR, None),))
            request_key = ("request", pointer)
            self.sources.bind(request_key, dependencies)
            try:
                self.manager.request(
                    node, route, self._publish, self.current_signature,
                    activate_callback=self._activate,
                    rollback_callback=self._rollback,
                    failure_callback=self._report_failure,
                    publication_context=self.gate().commit,
                )
            except BaseException:
                self.sources.forget(request_key)
                raise
        self.ensure_timer()

    def image_changed(self, node, _context):
        pointer = node.as_pointer()
        if pointer in self.mode_updates or pointer in self.image_updates:
            return
        self.set_mode(node, False)
        self.sources.forget(pointer)
        self.pending_invalidations.discard(pointer)
        self.write_receipt(node, None)
        image = getattr(node, "pg_bake_image", None)
        if image is not None and self.image_valid(node):
            try:
                observation = bake_routes.observe(node, self.stored_context(node))
                route = observation.get("route")
                effects = bake_policy.binding_policy(
                    None if route is None else route.get("receipt_signature"),
                    self.image_valid(node),
                    route is not None and (route.get("domain") == "UV")
                    == (image.get(BAKE_DOMAIN) == "UV"),
                )
                if effects.receipt_signature is not None:
                    self.write_receipt(node, effects.receipt_signature,
                                        bake_routes.backend_signature(route))
                    node[BAKE_CONTEXT] = json.dumps(self._context(route), separators=(",", ":"))
                    self._remember_observation(node)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        if self.manager is not None:
            self.manager.invalidate(node, None)

    def toggle_available(self, node, _context=None):
        return bake_policy.bake_toggle_available(
            self.image_valid(node),
            self.live_error(node),
        )

    def warning(self, node, observation):
        if not self.image_valid(node):
            return None
        receipt = BakeReceipt.decode(node.get(BAKE_NODE_SIGNATURE))
        if receipt is None:
            return "status.bake_stale_unverified"
        if receipt.source_invalidated or node.as_pointer() in self.pending_invalidations:
            return "status.bake_stale_source"
        route = observation["route"]
        if route is None:
            return "status.bake_stale_route"
        image = node.pg_bake_image
        if (route.get("canvas_size") is not None
                and tuple(image.size) != tuple(route["canvas_size"])):
            return "status.bake_stale_canvas_size"
        if route["receipt_signature"] == receipt.signature:
            return None
        if (receipt.backend_signature is not None
                and receipt.backend_signature != bake_routes.backend_signature(route)):
            return "status.bake_stale_engine"
        return "status.bake_stale_inputs"

    def use_changed(self, node, _context):
        if node.as_pointer() in self.mode_updates:
            return
        try:
            if node.pg_use_bake:
                if not self.toggle_available(node):
                    raise RuntimeError("Bound Bake Image is unavailable or Grade output has failed")
                self.set_mode(node, True)
                self.ensure_timer()
            else:
                self.set_mode(node, False)
        except Exception as error:
            node[BAKE_ERROR] = str(error)
            self.set_mode(node, False)

    def dimension_changed(self, node, _context):
        if node.as_pointer() in self.mode_updates:
            return
        if self.manager is not None:
            try:
                self.manager.invalidate(node, None)
            except Exception:
                self.set_mode(node, False)
        if (getattr(node, "pg_use_bake", False)
                or self.receipt_signature(node) is not None):
            self.reconcile((node,))
        self.ensure_timer()

    def invalidate(self, node):
        if not bake_routes.is_bake_target(node):
            return
        if (not getattr(node, "pg_use_bake", False)
                and self.receipt_signature(node) is None
                and (self.manager is None
                     or node.as_pointer() not in self.manager.jobs)
                and node.as_pointer() not in self.pending_reconciliations):
            return
        self.reconcile((node,))

    def mark_sources(self, dependencies):
        affected = self.sources.invalidate(dependencies)
        self.pending_invalidations.update(key for key in affected if isinstance(key, int))
        if affected:
            self.ensure_timer()
        return {key[1] if isinstance(key, tuple) else key for key in affected}

    def _persist_source_change(self, node):
        receipt = BakeReceipt.decode(node.get(BAKE_NODE_SIGNATURE))
        if bake_policy.persist_source_invalidation(
                receipt is not None, receipt is not None and not receipt.source_invalidated):
            self.write_receipt(node, receipt.signature, receipt.backend_signature, True)

    def invalidate_source(self, image):
        """Notify the add-on after a script changes an Image's pixel buffer."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Bake source invalidation requires Blender's main thread")
        if not isinstance(image, self.bpy.types.Image):
            raise TypeError("Bake source invalidation requires a Blender Image")
        affected = self.mark_sources((image,))
        if affected:
            self.reconcile(
                tuple(node for node in self.nodes()
                      if node.as_pointer() in affected),
            )
        return len(affected)

    def reconcile(self, nodes=None, *, inventory=None):
        gate = self.gate()
        if gate is None:
            return
        candidates = tuple(self.nodes()) if nodes is None else tuple(nodes)
        try:
            with gate.graph_commit():
                self.reconcile_in_scope(candidates, inventory=inventory)
        except PublicationDeferred:
            self.pending_reconciliations.update(
                node.as_pointer() for node in candidates
                if bake_routes.is_bake_target(node)
            )
            self.ensure_timer()

    def reconcile_in_scope(self, nodes, *, inventory=None, scoped=False):
        selected = {node.as_pointer(): node for node in nodes
                    if bake_routes.is_bake_target(node)}
        if self.pending_invalidations:
            if scoped:
                inventory = selected
                pending = tuple(self.pending_invalidations & selected.keys())
            else:
                pending = tuple(self.pending_invalidations)
            if inventory is None:
                inventory = {node.as_pointer(): node for node in self.nodes()
                             if bake_routes.is_bake_target(node)}
            for pointer in pending:
                node = inventory.get(pointer)
                if node is not None:
                    self._persist_source_change(node)
                    self.sources.forget(pointer)
                    selected[pointer] = node
                self.pending_invalidations.discard(pointer)

        for pointer, node in selected.items():
            using_bake = bool(node.pg_use_bake)
            job = None if self.manager is None else self.manager.jobs.get(pointer)
            has_receipt = self.receipt_signature(node) is not None
            if has_receipt:
                self.observed_signature(node, self.stored_context(node), track_sources=True)
            if job is not None:
                self.manager.invalidate(node, self.manager._resolve_signature(job))
            try:
                if not (using_bake or job is not None or has_receipt):
                    self.synchronize_output(node, use_bake=False)
                else:
                    output = bake_policy.output_policy(
                        using_bake, self.image_valid(node), self.live_error(node),
                    )
                    enabled = output.mode == "baked"
                    if enabled != using_bake:
                        self.set_mode(node, enabled, reconcile=False)
                    if output.mode == "error":
                        node[BAKE_ERROR] = output.error
                        self.fail_output(node, output.error)
                    else:
                        self.synchronize_output(node, use_bake=enabled)
            except PublicationDeferred:
                self.pending_reconciliations.add(pointer)
                raise
            except Exception as error:
                self.fail_output(node, str(error))
            self.pending_reconciliations.discard(pointer)

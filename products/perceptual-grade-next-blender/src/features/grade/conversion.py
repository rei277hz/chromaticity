"""Stage animation ownership changes while a Grade node is replaced."""

from dataclasses import dataclass
import re
from typing import Optional


_BACKUP_TAG = "_perceptual_grade_conversion_backup"
_BACKUP_SAFE_TAG = _BACKUP_TAG + "_safe_to_cleanup"
_NODE_SELECTOR = re.compile(r'''(?:^|\.)(nodes\[(?:-?\d+|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\])(?=[.\[])''')


def _action_bindings(animation):
    if animation is None:
        return
    yield animation

    def visit(strips):
        for strip in strips:
            if getattr(strip, "action", None) is not None:
                yield strip
            children = getattr(strip, "strips", ())
            if children:
                yield from visit(children)

    for track in animation.nla_tracks:
        yield from visit(track.strips)


def _slot_curves(action, slot):
    if slot is None:
        return
    for layer in action.layers:
        for strip in layer.strips:
            channelbag = strip.channelbag(slot)
            if channelbag is not None:
                for curve in tuple(channelbag.fcurves):
                    yield channelbag.fcurves, curve


def _matching_slot(action, slot):
    if slot is None:
        return None
    for candidate in action.slots:
        if candidate.identifier == slot.identifier:
            return candidate
    raise RuntimeError("Copied animation Action lost its bound slot")


def _node_suffix(path, prefix):
    if path.startswith(prefix + ".") or path.startswith(prefix + "["):
        return path[len(prefix):]
    return None


def _remove_conversion_driver(animation, curve):
    animation.drivers.remove(curve)


def _animation_owners(tree):
    import bpy

    # Blender's user map lists main IDs and attributes references made by an
    # embedded node tree to its containing ID. Both can own driver curves.
    owners = {tree}
    for owner in bpy.data.user_map():
        owners.add(owner)
        embedded = getattr(owner, "node_tree", None)
        if embedded is not None and embedded.is_embedded_data:
            owners.add(embedded)
    return owners


def _single_property_targets(driver):
    for index, variable in enumerate(driver.variables):
        if variable.type == "SINGLE_PROP":
            yield index, variable.targets[0]


def _resolve(owner, path):
    try:
        return owner.path_resolve(path)
    except (AttributeError, ValueError):
        return None


@dataclass(frozen=True)
class _Binding:
    owner: object
    action: object
    slot: object

    def assign(self, action):
        slot = _matching_slot(action, self.slot)
        self.owner.action = action
        # Action assignment can auto-select a slot, so restore explicit None.
        self.owner.action_slot = slot
        if self.owner.action != action or self.owner.action_slot != slot:
            raise RuntimeError("Could not preserve the node tree's animation binding")


@dataclass(frozen=True)
class _GradeDriver:
    curve: object
    suffix: str
    remove: bool
    array_index: int
    targets: tuple


@dataclass(frozen=True)
class _TargetState:
    id_type: str
    owner: object
    path: str

    def assign(self, target):
        # Changing id_type can clear the ID, and Blender may decline a new ID.
        if target.id_type != self.id_type:
            target.id_type = self.id_type
        if target.id != self.owner:
            target.id = self.owner
        if target.data_path != self.path:
            target.data_path = self.path
        if (target.id_type, target.id, target.data_path) != (self.id_type, self.owner, self.path):
            raise RuntimeError("Could not preserve a Grade driver target")


@dataclass(frozen=True)
class _DriverTarget:
    target: object
    original: _TargetState
    destination: _TargetState
    node_path: Optional[tuple[str, str]] = None

    def apply(self, node_prefix):
        state = self.destination
        if self.node_path is not None:
            root, suffix = self.node_path
            state = _TargetState(state.id_type, state.owner, root + node_prefix + suffix)
        state.assign(self.target)


class NodeAnimationConversion:
    """Prepare reversible animation remapping before deleting the source node.

    Active and NLA-bound Actions are copied before editing. Only bindings on
    this tree are rebound; their original Actions remain intact for rollback
    and for any other owners. Converted node drivers are copied to a temporary
    node group before removal so Blender can restore their complete FCurves.
    """

    def __init__(self, tree, source, replacement, *, removed_properties=(),
                 property_target_mapping=None):
        self.tree = tree
        self.source = source
        self.replacement = replacement
        self.source_prefix = source.path_from_id()
        self.replacement_prefix = replacement.path_from_id()
        self.removed_paths = frozenset(
            source.path_from_id(name) for name in removed_properties
        )
        self.property_target_mapping = dict(property_target_mapping or {})
        animation = tree.animation_data
        self._bindings = tuple(
            _Binding(owner, owner.action, owner.action_slot)
            for owner in _action_bindings(animation)
            if getattr(owner, "action", None) is not None
        )
        self._drivers = tuple(
            _GradeDriver(curve,
                         _node_suffix(curve.data_path, self.source_prefix),
                         curve.data_path in self.removed_paths,
                         curve.array_index,
                         tuple((index, plan)
                               for index, target in _single_property_targets(curve.driver)
                               if (plan := self._driver_target(target)) is not None))
            for curve in (() if animation is None else tuple(animation.drivers))
            if _node_suffix(curve.data_path, self.source_prefix) is not None
        )
        self._copies = {}
        self._survivors = []
        self._reader_targets = []
        self._driver_backup = None
        self._driver_backups = ()
        self._drivers_removed = False

    def _driver_target(self, target):
        owner, path = target.id, target.data_path
        if owner is None:
            return None
        reference = self._node_reference(owner, path)
        if reference is None or _resolve(owner, path) is None:
            return None
        root, suffix = reference
        original = _TargetState(target.id_type, owner, path)
        source_path = self.source_prefix + suffix
        mapping = self._target_mapping(source_path)
        if mapping is not None:
            destination, destination_path = mapping
            if destination != self.tree:
                return _DriverTarget(target, original,
                                     _TargetState("NODETREE", destination, destination_path))
            suffix = _node_suffix(destination_path, self.replacement_prefix)
            if suffix is None:
                raise RuntimeError("Could not resolve the replacement Grade driver field")
        elif source_path in self.removed_paths:
            raise RuntimeError("A Grade driver targets a property that conversion removes")
        return _DriverTarget(target, original, original, (root, suffix))

    def _node_reference(self, owner, path):
        # RNA paths can reach a node through its tree or through an ID that
        # references the tree. Resolve the node to check its actual identity.
        for match in _NODE_SELECTOR.finditer(path):
            if _resolve(owner, path[:match.end()]) == self.source:
                return path[:match.start(1)], path[match.end():]
        return None

    def _target_mapping(self, path):
        mapping = self.property_target_mapping.get(path)
        if mapping is not None:
            return mapping
        suffix = _node_suffix(path, self.source_prefix)
        if suffix is not None and suffix.startswith("."):
            return self.property_target_mapping.get(suffix[1:])
        return None

    def _capture_reader_targets(self):
        for owner in _animation_owners(self.tree):
            animation = getattr(owner, "animation_data", None)
            if animation is None:
                continue
            for curve in tuple(animation.drivers):
                # Source-node drivers have their own removal and rollback lifecycle.
                if (owner == self.tree
                        and _node_suffix(curve.data_path, self.source_prefix) is not None):
                    continue
                driver = curve.driver
                if driver is None:
                    continue
                for _index, target in _single_property_targets(driver):
                    plan = self._driver_target(target)
                    if plan is not None:
                        self._reader_targets.append(plan)

    def _targets(self):
        yield from self._reader_targets
        for driver in self._drivers:
            for _index, target in driver.targets:
                yield target

    def prepare(self):
        """Copy bound Actions and move source-node paths to the candidate."""
        if self.replacement_prefix == self.source_prefix:
            raise RuntimeError("Grade replacement must have a temporary unique name")
        self._capture_reader_targets()

        affected = {
            binding.action.as_pointer(): binding.action
            for binding in self._bindings
            if any(_node_suffix(curve.data_path, self.source_prefix) is not None
                   for _collection, curve in _slot_curves(binding.action, binding.slot))
        }
        for identity, original in affected.items():
            self._copies[identity] = (original, original.copy())

        visited = set()
        for binding in self._bindings:
            record = self._copies.get(binding.action.as_pointer())
            if record is None or binding.slot is None:
                continue
            _original, copied = record
            slot = _matching_slot(copied, binding.slot)
            identity = (copied.as_pointer(), slot.handle)
            if identity in visited:
                continue
            visited.add(identity)
            for collection, curve in _slot_curves(copied, slot):
                suffix = _node_suffix(curve.data_path, self.source_prefix)
                if suffix is None:
                    continue
                if curve.data_path in self.removed_paths:
                    collection.remove(curve)
                else:
                    curve.data_path = self.replacement_prefix + suffix
                    self._survivors.append((curve, suffix))

        for binding in self._bindings:
            record = self._copies.get(binding.action.as_pointer())
            if record is not None:
                binding.assign(record[1])

        for driver in self._drivers:
            driver.curve.data_path = self.replacement_prefix + driver.suffix
        for target in self._targets():
            target.apply(self.replacement_prefix)

    def finish(self):
        """Set candidate animation paths after its final node name is assigned."""
        prefix = self.replacement.path_from_id()
        for curve, suffix in self._survivors:
            curve.data_path = prefix + suffix
        for driver in self._drivers:
            driver.curve.data_path = prefix + driver.suffix
        for target in self._targets():
            target.apply(prefix)

    def remove_grade_drivers(self):
        """Backup then remove node-owned drivers on converted Grade fields."""
        # Only the prepared kernel has the replacement's final sockets. Verify
        # every remapped reader here while the source node can still be restored.
        for plan in self._targets():
            target = plan.target
            if _resolve(target.id, target.data_path) is None:
                raise RuntimeError(f"Could not resolve converted Grade driver path {target.data_path!r}")
        removable = tuple(driver for driver in self._drivers if driver.remove)
        if self._drivers_removed or not removable:
            return
        import bpy

        backup = bpy.data.node_groups.new(
            "Perceptual Grade conversion driver backup", self.tree.bl_idname,
        )
        self._driver_backup = backup
        backup[_BACKUP_TAG] = True
        backup[_BACKUP_SAFE_TAG] = False
        drivers = backup.animation_data_create().drivers
        copied = []
        for driver in removable:
            backup_curve = drivers.from_existing(src_driver=driver.curve)
            # The source may already have a temporary name. Store the backup
            # under its original path so it restores after the source is renamed.
            backup_curve.data_path = self.source_prefix + driver.suffix
            for index, target in driver.targets:
                target.original.assign(backup_curve.driver.variables[index].targets[0])
            copied.append(backup_curve)
        self._driver_backups = tuple(copied)
        animation = self.tree.animation_data
        self._drivers_removed = True
        for driver in removable:
            _remove_conversion_driver(animation, driver.curve)

    def rollback(self):
        """Restore original Action bindings, drivers, and external target IDs."""
        failures = []
        for binding in self._bindings:
            try:
                if (binding.action.as_pointer() in self._copies
                        and (binding.owner.action != binding.action
                             or binding.owner.action_slot != binding.slot)):
                    binding.assign(binding.action)
            except Exception as error:
                failures.append(error)

        for target in self._reader_targets:
            try:
                target.original.assign(target.target)
            except Exception as error:
                failures.append(error)

        animation = self.tree.animation_data
        replacement_prefix = self.replacement.path_from_id()
        for driver in self._drivers:
            try:
                original_path = self.source_prefix + driver.suffix
                curve = animation.drivers.find(
                    replacement_prefix + driver.suffix, index=driver.array_index,
                )
                if curve is not None:
                    curve.data_path = original_path
                else:
                    curve = animation.drivers.find(original_path, index=driver.array_index)
                if curve is not None:
                    for index, target in driver.targets:
                        target.original.assign(curve.driver.variables[index].targets[0])
            except Exception as error:
                failures.append(error)

        if self._drivers_removed and self._driver_backup is not None:
            try:
                source_drivers = self._driver_backup.animation_data.drivers
                destination = animation.drivers
                for backup in self._driver_backups:
                    if destination.find(backup.data_path, index=backup.array_index) is None:
                        destination.from_existing(src_driver=backup)
                for backup in tuple(source_drivers):
                    source_drivers.remove(backup)
            except Exception as error:
                failures.append(error)

        self._remove_action_copies(failures)
        if not failures:
            if self._driver_backup is not None:
                self._driver_backup[_BACKUP_SAFE_TAG] = True
            self._remove_backup(failures)
            self._clear()
        if failures:
            raise ExceptionGroup("Could not restore Grade node animation", failures)

    def commit(self):
        """Release transaction state and discard the temporary driver backup."""
        failures = []
        if self._driver_backup is not None:
            try:
                self._driver_backup[_BACKUP_SAFE_TAG] = True
            except Exception as error:
                failures.append(error)
        self._remove_backup(failures)
        self._clear()
        return tuple(failures)

    def _remove_action_copies(self, failures):
        for _original, copied in self._copies.values():
            try:
                copied.use_fake_user = False
                if copied.users == 0:
                    import bpy
                    bpy.data.actions.remove(copied)
            except Exception as error:
                failures.append(error)

    def _remove_backup(self, failures):
        try:
            group = self._driver_backup
            if group is not None and group.as_pointer() and group.users == 0:
                group[_BACKUP_SAFE_TAG] = True
                import bpy
                bpy.data.node_groups.remove(group, do_unlink=False)
        except Exception as error:
            failures.append(error)

    def _clear(self):
        self._bindings = ()
        self._drivers = ()
        self._copies.clear()
        self._survivors.clear()
        self._reader_targets.clear()
        self._driver_backups = ()
        self._driver_backup = None

"""Central ownership of Blender handler and timer registrations."""


class HostCallbackRouter:
    def __init__(self, bpy):
        self.bpy = bpy
        self._handlers = []
        self._timers = []

    def register_handlers(self, owner, bindings):
        if not owner:
            raise ValueError("Host callback registrations require an owner")
        for collection, callback in bindings:
            if callback not in collection:
                collection.append(callback)
            if not any(registered_owner == owner and registered_collection is collection
                       and registered_callback is callback
                       for registered_owner, registered_collection, registered_callback
                       in self._handlers):
                self._handlers.append((owner, collection, callback))

    def unregister_handlers(self, owner):
        errors = []
        owned = tuple(record for record in self._handlers if record[0] == owner)
        for _owner, collection, callback in reversed(owned):
            shared = any(
                other_owner != owner and other_collection is collection
                and other_callback is callback
                for other_owner, other_collection, other_callback in self._handlers
            )
            if shared:
                self._handlers.remove((_owner, collection, callback))
                continue
            try:
                while callback in collection:
                    collection.remove(callback)
            except ValueError:
                pass
            except Exception as error:
                errors.append(error)
                continue
            self._handlers[:] = [
                record for record in self._handlers
                if not (record[1] is collection and record[2] is callback)
            ]
        return tuple(errors)

    def timer_registered(self, callback):
        return self.bpy.app.timers.is_registered(callback)

    def ensure_timer(self, owner, callback, *, first_interval, persistent=False):
        if not owner:
            raise ValueError("Host timer registrations require an owner")
        if not self.timer_registered(callback):
            self.bpy.app.timers.register(
                callback, first_interval=first_interval, persistent=persistent,
            )
        if not any(item_owner == owner and item_callback is callback
                   for item_owner, item_callback in self._timers):
            self._timers.append((owner, callback))

    def unregister_timer(self, owner, callback):
        record = next((item for item in self._timers
                       if item[0] == owner and item[1] is callback), None)
        if record is None:
            return
        shared = any(item_owner != owner and item_callback is callback
                     for item_owner, item_callback in self._timers)
        if not shared and self.timer_registered(callback):
            self.bpy.app.timers.unregister(callback)
        self._timers.remove(record)

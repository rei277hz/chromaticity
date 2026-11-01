"""A picker enable lifecycle, retained by its exact registered native classes."""


class Session:
    def __init__(self, app):
        self.app = app
        self._controller = None
        self.ui = None
        self.closed = False

    def controller(self):
        self.app.require_open()
        if self._controller is None:
            from .controller import Controller
            self._controller = Controller(self.app)
        return self._controller

    def current_controller(self):
        return self._controller

    def reset(self):
        if self._controller is not None and not self.closed:
            protocol = self.app.lifecycle
            if protocol is not None:
                if protocol.state.phase == 'repair_needed':
                    protocol.require('repair', 'repair')
                elif protocol.state.phase == 'active':
                    protocol.require('inspect', 'inspect')
                receipt = dict(operation=protocol.state.operation, generation=protocol.state.generation)
            try:
                self._controller.reset()
                if protocol is not None:
                    if protocol.state.phase == 'repairing':
                        protocol.require('repaired', 'inspect', validated=True, debts=0, **receipt)
                    protocol.require('inspected', 'activate', validated=True,
                                     borrows=sum(len(arena._borrows) for arena in self.app.ownership.snapshots()),
                                     readers=0, debts=0, **receipt)
            except Exception:
                if protocol is not None:
                    protocol.event('failed', **receipt)
                raise

    def register(self):
        from .ui import create_ui
        self.ui = create_ui(self)
        for cls in self.ui.classes:
            cls._invariant_picker_session = self
        try:
            self.ui.register()
        except Exception:
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        errors = []
        if self.ui is not None:
            try:
                self.ui.stop()
            except Exception as error:
                errors.append(error)
        if self._controller is not None:
            try:
                self._controller.close()
            except Exception as error:
                errors.append(error)
        try:
            self.app.close()
        except Exception as error:
            errors.append(error)
        if errors:
            raise ExceptionGroup('Picker lifecycle cleanup failed', errors)
        self._controller = None
        self.closed = True

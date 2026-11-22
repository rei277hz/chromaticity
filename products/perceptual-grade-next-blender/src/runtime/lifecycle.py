"""Order lifecycle fences around Blender file and undo transitions."""

# pg-book: technical-report/en#next-policy.resources


class LifecycleCoordinator:
    def __init__(self):
        self.changing = False
        self.reset_pending = False

    def begin(self, operations):
        """Run every cleanup step and return failures after the safety fence."""
        self.changing = True
        failures = []
        for operation in operations:
            try:
                operation()
            except Exception as error:
                failures.append(error)
        return tuple(failures)

    def finish(self, invalidate_render_preflights):
        if not self.changing:
            return
        invalidate_render_preflights()
        self.changing = False

    def reconcile(self, release_resources, repair_outputs):
        if self.changing:
            return False
        release_resources()
        self.reset_pending = False
        repair_outputs()
        return True

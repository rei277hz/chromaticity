"""Composition root for the Blender extension."""

from .host.callbacks import HostCallbackRouter


class AddonRuntime:
    def __init__(self, bpy):
        self.callbacks = HostCallbackRouter(bpy)
        self.grade = None
        self.bake = None
        self.capture_helper = None
        self._shutdown_phase = None
        self._shutdown_retry = self._retry_unregister
        self._retrying_shutdown = False

    def register(self):
        from .runtime.capture_helper import CaptureHelperBackend
        from .features.grade import host as grade

        if (self.grade is not None
                and (self._shutdown_phase is not None
                     or self.grade.registration_cleanup_needed())):
            self.unregister()
        if self.capture_helper is None:
            self.capture_helper = CaptureHelperBackend()
        self.grade = grade
        try:
            grade.register(self.callbacks)
            self.bake = grade.register_bake(self.capture_helper.create_job)
            grade.register_scope(self.capture_helper.create_job)
        except Exception as startup_error:
            try:
                self.unregister()
            except Exception as cleanup_error:
                raise ExceptionGroup(
                    "Extension startup and rollback both failed",
                    [startup_error, cleanup_error],
                ) from startup_error
            raise

    def unregister(self):
        if self.grade is None:
            return
        if self._shutdown_phase is None:
            self._shutdown_phase = "grade_admission"
        try:
            from .features.vectorscope import ui as vectorscope

            if self._shutdown_phase == "grade_admission":
                self.grade.close_admission()
                self._shutdown_phase = "bake_begin"
            if self._shutdown_phase == "bake_begin":
                if self.bake is not None:
                    self.bake.begin_shutdown()
                self._shutdown_phase = "vectorscope_begin"
            if self._shutdown_phase == "vectorscope_begin":
                vectorscope.begin_shutdown()
                self._shutdown_phase = "capture_retirement"
            if self._shutdown_phase == "capture_retirement":
                if self.capture_helper is not None:
                    self.capture_helper.close()
                self._shutdown_phase = "bake_finish"
            if self._shutdown_phase == "bake_finish":
                if self.bake is not None:
                    self.bake.finish_shutdown()
                self._shutdown_phase = "vectorscope_finish"
            if self._shutdown_phase == "vectorscope_finish":
                vectorscope.finish_shutdown()
                self._shutdown_phase = "feature_teardown"
        except Exception as error:
            self._schedule_shutdown_retry(error)
            raise

        self.capture_helper = None
        errors = []
        try:
            vectorscope.unregister()
        except Exception as error:
            errors.append(error)
        if self.bake is not None:
            try:
                self.bake.stop_timer()
            except Exception as error:
                errors.append(error)
        try:
            self.grade.unregister()
        except Exception as error:
            errors.append(error)
        if not self._retrying_shutdown:
            try:
                self.callbacks.unregister_timer("application", self._shutdown_retry)
            except Exception as error:
                errors.append(error)
        if len(errors) == 1:
            failure = errors[0]
        elif errors:
            failure = ExceptionGroup("Extension teardown failed", errors)
        else:
            self.grade = None
            self.bake = None
            self._shutdown_phase = None
            return
        self._schedule_shutdown_retry(failure)
        raise failure

    def _schedule_shutdown_retry(self, failure):
        try:
            self.callbacks.ensure_timer(
                "application", self._shutdown_retry,
                first_interval=0.1, persistent=True,
            )
        except Exception as timer_error:
            raise ExceptionGroup(
                "Extension shutdown and retry scheduling both failed",
                [failure, timer_error],
            ) from failure

    def _retry_unregister(self):
        self._retrying_shutdown = True
        try:
            self.unregister()
        except Exception as error:
            print("Perceptual Grade extension shutdown failed:", error)
            return 0.1
        finally:
            self._retrying_shutdown = False
        return None


_runtime = None


def register():
    global _runtime
    if _runtime is None:
        import bpy

        _runtime = AddonRuntime(bpy)
    _runtime.register()


def unregister():
    if _runtime is not None:
        _runtime.unregister()


def invalidate_image(image):
    from .features.grade.host import invalidate_source

    return invalidate_source(image)

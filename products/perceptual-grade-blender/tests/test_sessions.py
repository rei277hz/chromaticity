"""Same imported product, distinct App lifecycles and exact native registration."""
from importlib import import_module
from types import SimpleNamespace
import unittest

from color_tools.blender_runtime import ClosedError, ForeignOwnerError
from color_tools.perceptual_grade_blender.machines import create_machines
from color_tools.perceptual_grade_blender.integration.components import Component, ComponentRef, component_get, component_items
from color_tools.perceptual_grade_blender.integration.registry import COMPONENTS
from color_tools.perceptual_grade_blender.session import Session


class ComponentTests(unittest.TestCase):
    def test_live_scalar_exports_and_explicit_writers(self):
        value = 1

        def assign(next_value):
            nonlocal value
            value = next_value

        component = Component(readers={'value': lambda: value}, writers={'value': assign})
        self.assertEqual(component.value, 1)
        value = 2
        self.assertEqual(dict(component_items(component))['value'], 2)
        component['value'] = 3
        self.assertEqual(value, 3)
        self.assertEqual(component_get(component, 'missing', 4), 4)
        with self.assertRaises(AttributeError):
            component.undeclared = 5

    def test_product_get_and_items_exports_do_not_collide_with_mapping_helpers(self):
        component = Component({'get': lambda a, b, c: (a, b, c), 'items': lambda: 'product items'})
        self.assertEqual(component.get(1, 2, 3), (1, 2, 3))
        self.assertEqual(component.items(), 'product items')
        self.assertIs(component_get(component, 'get'), component.get)
        self.assertIs(dict(component_items(component))['items'], component.items)

    def test_product_private_exports_remain_distinct_from_component_storage(self):
        values = {name: index for index, name in enumerate(('_state', '_session', '_name', '_exports', '_readers', '_writers'))}
        component = Component(readers={name: lambda name=name: values[name] for name in values},
                              writers={name: lambda value, name=name: values.__setitem__(name, value) for name in values})
        session = SimpleNamespace(_component=lambda name: component)
        reference = ComponentRef(session, 'fixture')
        for name in values:
            self.assertEqual(getattr(reference, name), values[name])
            setattr(reference, name, 42)
            self.assertEqual(getattr(component, name), 42)
        self.assertEqual(dict(component_items(component)), values)


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.machines = create_machines()

    def session(self):
        result = Session(self.machines)
        self.addCleanup(result.close)
        return result

    def test_all_foreground_factories_are_inert_and_isolated(self):
        first, second = self.session(), self.session()
        self.assertEqual(first.components, {})
        self.assertEqual(second.components, {})
        for name in sorted(COMPONENTS):
            with self.subTest(component=name):
                module = import_module('color_tools.perceptual_grade_blender.' + name)
                left, right = first._component(name), second._component(name)
                self.assertIs(first._component(name), left)
                self.assertIsNot(left, right)
                self.assertIs(import_module(module.__name__), module)
        self.assertIsNone(first.app.execution.current_runtime())
        self.assertIsNone(second.app.execution.current_runtime())
        self.assertEqual(first.classes, [])
        self.assertEqual(second.classes, [])
        self.assertEqual(first.handlers, [])
        self.assertEqual(second.handlers, [])
        for name, field in (('graph.scheduler', '_records'), ('graph.lut', '_states'),
                            ('scopes.jobs', '_states'), ('scopes.sampling', '_images'),
                            ('ui.warp', '_rail_drags'), ('ui.warp_samples', '_textures')):
            self.assertIsNot(getattr(first.component(name), field), getattr(second.component(name), field))
        self.assertIsNot(first.component('graph.grades').PGGradeData, second.component('graph.grades').PGGradeData)
        self.assertIsNot(first.component('ui.diagram').PG_OT_diagram_drag, second.component('ui.diagram').PG_OT_diagram_drag)
        self.assertIsNot(first.component('ui.warp').geometry, second.component('ui.warp').geometry)
        first.component('graph.nodes')._rendering = True
        self.assertTrue(first.component('graph.nodes')._rendering)
        self.assertFalse(second.component('graph.nodes')._rendering)

    def test_foreign_receipts_and_owned_fields_do_not_cross_sessions(self):
        first, second = self.session(), self.session()
        machine = self.machines['attempt']
        left = first.app.store(machine=machine, initial=dict(identity=1, generation=0, interests=1))
        right = second.app.store(machine=machine, initial=dict(identity=1, generation=0, interests=1))
        event = machine.module.Event(kind='start', identity=1, generation=0)
        receipt = left.event(event)
        before = right.state
        with self.assertRaises(ForeignOwnerError):
            right.dispatch(receipt)
        self.assertIs(right.state, before)
        left.dispatch(receipt)
        self.assertEqual(left.state.phase, 1)

        left_field = first.component('ownership').OwnedField('session.test')
        right_field = second.component('ownership').OwnedField('session.test')
        class LeftHolder:
            value = left_field
        class RightHolder:
            value = right_field
        first_holder, second_holder = LeftHolder(), RightHolder()
        first_value, second_value = object(), object()
        first_holder.value, second_holder.value = first_value, second_value
        self.assertIs(first_holder.value, first_value)
        self.assertIs(second_holder.value, second_value)
        with self.assertRaises(ForeignOwnerError):
            right_field.__set__(first_holder, object())
        self.assertIs(first_holder.value, first_value)
        self.assertIs(second_holder.value, second_value)

        first.close()
        self.assertTrue(first.app.closed)
        with self.assertRaises(ClosedError):
            left.dispatch(event)
        self.assertIs(second_holder.value, second_value)
        self.assertTrue(right.dispatch(event).accepted)
        replacement = self.session()
        self.assertNotIn(replacement.app.identity, (first.app.identity, second.app.identity))
        self.assertEqual(replacement.component('graph.scheduler')._records, {})

    def test_deferred_borrow_fences_admission_and_preserves_exact_native_classes(self):
        import bpy
        application = self.session()
        application.register()
        scheduler = application.component('graph.scheduler')
        guard = application.component('graph.output_guard')
        retained = application.app.ownership.retain(bpy.context.scene, 'deferred.close')
        exact_classes = tuple(application.classes)
        with application.app.ownership.borrow(retained):
            self.assertFalse(application.close())
            self.assertTrue(application.waiting_for_readers)
            self.assertFalse(application.closed)
            self.assertFalse(scheduler.lifecycle_admits('discover'))
            self.assertFalse(scheduler.lifecycle_admits('timer'))
            with self.assertRaises(guard.PublicationDeferred):
                with guard.publication():
                    self.fail('Deferred cleanup admitted output installation')
            self.assertTrue(all(cls.is_registered for cls in exact_classes))
        self.assertTrue(application.close())
        self.assertTrue(application.app.closed)
        self.assertFalse(application.waiting_for_readers)
        self.assertTrue(all(not cls.is_registered for cls in exact_classes))

    def test_teardown_guard_rechecks_readers_after_admission_fence(self):
        from types import SimpleNamespace
        first = self.session()
        guard = first.component('graph.output_guard')
        guard.observation()  # Registration constructs its actor before fencing.
        first.app.fence()
        self.assertFalse(guard.available())
        self.assertTrue(guard.available(cleanup=True))
        original = guard.bpy
        try:
            guard.bpy = SimpleNamespace(app=SimpleNamespace(is_job_running=lambda kind: kind == 'RENDER'),
                                        data=SimpleNamespace(window_managers=[]))
            self.assertFalse(guard.available(cleanup=True))
            self.assertIn('RENDER', guard.reason(cleanup=True))
        finally:
            guard.bpy = original

    def test_output_cleanup_retains_failed_menu_and_finishes_independent_menu(self):
        from types import SimpleNamespace
        first = self.session()
        output = first.component('graph.output')
        callbacks = (lambda: None, lambda: None)
        removed = []

        class Menu:
            def __init__(self, callback, fail=False):
                self.draw = SimpleNamespace(_draw_funcs=[callback])
                self.fail = fail

            def remove(self, callback):
                if self.fail:
                    self.fail = False
                    raise RuntimeError('native menu cleanup failed')
                self.draw._draw_funcs.remove(callback)
                removed.append(callback)

        left, right = Menu(callbacks[0], True), Menu(callbacks[1])
        output._menus.extend(((left, callbacks[0]), (right, callbacks[1])))
        with self.assertRaises(ExceptionGroup):
            output.unregister()
        self.assertEqual(removed, [callbacks[1]])
        self.assertEqual(output._menus, [(left, callbacks[0])])
        self.assertTrue(output.unregister())
        self.assertEqual(removed, [callbacks[1], callbacks[0]])
        self.assertEqual(output._menus, [])

    def test_zero_argument_unregister_recovers_exact_registered_session(self):
        from color_tools import perceptual_grade_blender as addon
        from color_tools.perceptual_grade_blender.integration import lifecycle
        import bpy

        first = self.session()
        first.register()
        old_tick = first.component('scopes.jobs').tick
        old_admits = first.component('graph.scheduler').lifecycle_admits
        self.assertIs(lifecycle.registered_session(), first)
        classes, handlers = tuple(first.classes), tuple(first.handlers)
        self.assertTrue(classes)
        addon.unregister()
        self.assertTrue(first.closed)
        self.assertIsNone(old_tick())
        self.assertFalse(old_admits('discover'))
        self.assertIsNone(lifecycle.registered_session())
        self.assertTrue(all(not getattr(cls, 'is_registered', False) for cls in classes))
        self.assertTrue(all(callback not in getattr(bpy.app.handlers, name) for name, callback in handlers))
        second = self.session()
        second.register()
        self.assertIs(lifecycle.registered_session(), second)
        self.assertNotEqual(first.app.identity, second.app.identity)
        self.assertIsNone(old_tick())
        first.close()
        self.assertIs(lifecycle.registered_session(), second)
        self.assertTrue(any(getattr(cls, 'is_registered', False) for cls in second.classes))
        addon.unregister()
        self.assertTrue(second.closed)


if __name__ == '__main__':
    unittest.main()

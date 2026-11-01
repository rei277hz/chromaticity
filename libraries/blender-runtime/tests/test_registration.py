"""Registration cleanup owns only its callbacks and survives partial failures."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from color_tools.blender_runtime import App
from color_tools.blender_runtime.blender.registration import Registration


class RegistrationTests(unittest.TestCase):
    def test_partial_failure_unwinds_in_reverse_order_and_finishes_cleanup(self):
        registrations = Registration(App(package='fixture', storage_name='fixture'))
        calls = []
        registrations.defer(lambda: calls.append('oldest'))
        def broken():
            calls.append('broken')
            if calls.count('broken') == 1:
                raise RuntimeError('native cleanup failed')
        registrations.defer(broken)
        registrations.defer(lambda: calls.append('newest'))
        with self.assertRaises(ExceptionGroup) as caught:
            registrations.close()
        self.assertEqual(calls, ['newest', 'broken', 'oldest'])
        self.assertEqual(len(caught.exception.exceptions), 1)
        self.assertTrue(registrations)
        registrations.close()
        self.assertFalse(registrations)
        self.assertEqual(calls, ['newest', 'broken', 'oldest', 'broken'])

    def test_closing_one_registration_preserves_peer_handlers_and_timer(self):
        timers = set()
        host = SimpleNamespace(app=SimpleNamespace(timers=SimpleNamespace(
            is_registered=lambda callback: callback in timers,
            register=lambda callback, **settings: timers.add(callback),
            unregister=timers.remove)))
        handlers = []
        first, second = Registration(App(package='fixture', storage_name='fixture')), Registration(App(package='fixture', storage_name='fixture'))
        a, b = lambda: None, lambda: None
        with patch.dict(sys.modules, {'bpy': host}):
            first.handler(handlers, a)
            second.handler(handlers, b)
            first.timer(a, first_interval=.1)
            second.timer(b, first_interval=.1)
            first.close()
            self.assertEqual(handlers, [b])
            self.assertEqual(timers, {b})
            second.close()
        self.assertEqual(handlers, [])
        self.assertEqual(timers, set())

    def test_existing_registration_is_not_owned_or_removed(self):
        callback = lambda: None
        handlers = [callback]
        registration = Registration(App(package='fixture', storage_name='fixture'))
        registration.handler(handlers, callback)
        registration.close()
        self.assertEqual(handlers, [callback])
        owner = SimpleNamespace(existing='peer')
        with self.assertRaises(RuntimeError):
            registration.property(owner, 'existing', 'replacement')
        self.assertEqual(owner.existing, 'peer')


if __name__ == '__main__':
    unittest.main()

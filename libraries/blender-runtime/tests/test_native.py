"""Concrete binding-order premises for timer and keymap retirement."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from color_tools.blender_runtime.blender import BlenderConfig
from color_tools.blender_runtime.ownership import OwnershipConfig
from .test_app import MachineFixture


class NativeRemovalTests(MachineFixture, unittest.TestCase):
    def setUp(self):
        self.application = self.app(ownership=OwnershipConfig(self.machine('ownership'),
            keys=lambda value: (id(value), None, None)), blender=BlenderConfig(native=True))

    def test_both_binding_paths_retire_all_matching_cells_before_native_removal(self):
        arena = self.application.ownership
        remove_timer = self.application.blender.native.remove_timer
        remove_keymap_item = self.application.blender.native.remove_keymap_item
        for remove in (remove_timer,remove_keymap_item):
            for fail_after_effect in (False,True):
                with self.subTest(remove=remove.__name__,fail_after_effect=fail_after_effect):
                    value=object()
                    first=arena.retain(value,'first.holder')
                    second=arena.retain(value,'second.holder')
                    other=object()
                    unrelated=arena.retain(other,'other.holder')
                    observed=[]
                    def native(argument):
                        self.assertIs(argument,value)
                        self.assertIsNone(arena.resolve(first))
                        self.assertIsNone(arena.resolve(second))
                        self.assertIs(arena.resolve(unrelated),other)
                        observed.append(True)
                        if fail_after_effect:raise RuntimeError('removed before binding failed')
                    owner=(SimpleNamespace(event_timer_remove=native) if remove is remove_timer
                           else SimpleNamespace(keymap_items=SimpleNamespace(remove=native)))
                    if fail_after_effect:
                        with self.assertRaisesRegex(RuntimeError,'binding failed'):remove(owner,value)
                    else:remove(owner,value)
                    self.assertEqual(observed,[True])
                    self.assertIsNone(arena.resolve(first))
                    self.assertIsNone(arena.resolve(second))
                    arena.release(unrelated)

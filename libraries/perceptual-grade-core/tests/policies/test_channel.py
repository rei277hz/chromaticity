"""Channel query, domain, and Store regressions."""
import unittest
from tests.blender_runtime.policy_fixture import bind_policy as Machine
from color_tools.blender_runtime import App, DomainError
from color_tools.perceptual_grade_core.graph import scheduler_policy as policy
from color_tools.perceptual_grade_core.graph.policies import channel


class ChannelPolicyTests(unittest.TestCase):
    def test_store_uses_policy_domains_and_noncommitting_preview(self):
        machine = Machine(channel, initializers=('initial',))
        app = App(package='scheduler-test', storage_name='scheduler_test')
        self.addCleanup(app.close)
        store = app.store(machine=machine, initial=dict(owner=1, key=0, session=1, scope=False, linear=False))
        before = store.state
        event = policy.Event('request', owner=1, session=1, key=5)
        prospective = store.preview(event)
        self.assertIs(store.state, before)
        self.assertEqual(prospective.state.requested, 5)
        store.dispatch(event)
        self.assertEqual(store.state, prospective.state)
        before = store.state
        with self.assertRaises(DomainError):
            store.dispatch(policy.Event('request', owner=1, session=1, key=-1))
        self.assertIs(store.state, before)

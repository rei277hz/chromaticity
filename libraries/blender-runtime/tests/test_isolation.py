"""Two private extension packages share source without sharing live state."""
from importlib import import_module, reload
import gc
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
import weakref
from unittest.mock import patch

import numpy as np
from color_tools import blender_runtime as invariant, invariant as actor_runtime, color_core
from .test_app import MachineFixture
from color_tools.color_core import linear as color
from color_tools.blender_runtime.execution.contracts import RuntimeProfile
from color_tools.blender_runtime.execution.values import seal


class SharedCoreTests(MachineFixture, unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runtimes = []
        self.apps = []
        self.packages = []
        self.addCleanup(self.close)

    def close(self):
        for runtime in self.runtimes:
            self.assertTrue(runtime.shutdown().clean)
        for app in self.apps:
            app.close()
        for name in self.packages:
            for module in tuple(sys.modules):
                if module == name or module.startswith(name + '.'):
                    del sys.modules[module]

    def package(self, name):
        extension = self.root / name
        target = extension
        target.mkdir(parents=True)
        (extension / '__init__.py').write_text(
            'raise RuntimeError("Extension entrypoint must not run in helpers")\n')
        for component in (invariant, actor_runtime, color_core):
            shutil.copytree(Path(component.__file__).parent, target / component.__name__.rsplit('.', 1)[-1],
                            ignore=shutil.ignore_patterns('__pycache__'))
        module = ModuleType(name)
        module.__path__ = [str(extension)]
        sys.modules[name] = module
        self.packages.append(name)
        self.assertFalse((target / '_vendor').exists())
        return target

    def application(self, name, *, ownership=False, execution=None, require_clean=lambda: None):
        framework = import_module(name + '.blender_runtime')
        settings = {}
        if ownership:
            ownership_module = import_module(name + '.blender_runtime.ownership')
            machine = self.private_machine(framework, 'ownership')
            settings['ownership'] = ownership_module.OwnershipConfig(machine, require_clean=require_clean)
        if execution is not None:
            settings['execution'] = framework.ExecutionConfig(execution)
        app = framework.App(package=self.root / name, storage_name=name, **settings)
        self.apps.append(app)
        return app

    def context(self, name):
        return self.application(name, ownership=True).ownership

    def execution_machines(self, name):
        framework = import_module(name + '.blender_runtime')
        machines = import_module(name + '.blender_runtime.execution.machines')
        return machines.ExecutionMachines(*(self.private_machine(framework, kind)
            for kind in ('attempt', 'gpu', 'retry', 'startup')))

    def private_machine(self, framework, kind):
        original = self.machine(kind)
        factories = import_module(framework.__name__ + '.machines')
        return factories.policy_machine(kind, initializers=(original.default_initializer,),
                                        queries=tuple(original.queries))

    def test_cross_package_tokens_cannot_resolve_or_release_equal_cell_ids(self):
        for name in ('private_first', 'private_second'):
            self.package(name)
        first = self.context('private_first')
        second = self.context('private_second')
        first_value, second_value = object(), object()
        first_ref = first.retain(first_value, 'first')
        second_ref = second.retain(second_value, 'second')
        self.assertEqual((first_ref.arena, first_ref.cell), (second_ref.arena, second_ref.cell))
        self.assertNotEqual(first_ref.domain, second_ref.domain)
        for context, ref in ((first, second_ref), (second, first_ref)):
            for operation in (context.resolve, context.release, context.default.resolve):
                with self.assertRaises(Exception) as caught:
                    operation(ref)
                self.assertEqual(type(caught.exception).__name__, 'ForeignOwnerError')
        self.assertIs(first.resolve(first_ref), first_value)
        self.assertIs(second.resolve(second_ref), second_value)
        with self.assertRaises(Exception) as caught:
            first.borrow(second_ref)
        self.assertEqual(type(caught.exception).__name__, 'ForeignOwnerError')
        first.close()
        self.assertIsNone(first.resolve(first_ref))
        self.assertIs(second.resolve(second_ref), second_value)

    def test_arena_close_retires_only_owned_cells_and_is_terminal(self):
        self.package('private_lifetime')
        module = self.context('private_lifetime')
        owner, peer = module.arena(), module.arena()
        ref = owner.retain(object(), 'closed')
        peer_value = object()
        peer_ref = peer.retain(peer_value, 'peer')
        owner.close()
        owner.close()
        self.assertNotIn(owner, module.snapshots())
        self.assertIn(peer, module.snapshots())
        self.assertEqual(owner.physical_counts(), (0, 0))
        self.assertIsNone(module.resolve(ref))
        self.assertIsNone(owner.resolve(ref))
        self.assertIs(peer.resolve(peer_ref), peer_value)
        with self.assertRaises(ReferenceError):
            with module.borrow(ref):
                self.fail('A closed arena provided a new borrow')
        for action in (lambda: owner.retain(object(), 'late'), owner.begin,
                       owner.native_replaced, lambda: owner.recovered(owner.state.token)):
            with self.subTest(action=action), self.assertRaises(RuntimeError):
                action()

    def test_close_preserves_scoped_borrow_until_its_original_finally(self):
        self.package('private_borrow')
        module = self.context('private_borrow')
        owner = module.arena()
        value = SimpleNamespace(name='native')
        ref = owner.retain(value, 'borrowed')
        with owner.borrow(ref) as borrowed:
            owner.close()
            self.assertIs(borrowed, value)
            self.assertEqual(owner.physical_counts(), (0, 1))
            self.assertEqual(owner.state.borrows, 1)
            self.assertNotIn(owner, module.snapshots())
            self.assertIsNone(owner.resolve(ref))
        self.assertEqual(owner.physical_counts(), (0, 0))
        self.assertEqual(owner.state.borrows, 0)
        self.assertEqual(owner.state.phase, import_module('private_borrow.blender_runtime.ownership.arena').FAILED)

    def test_close_does_not_keep_controller_alive_through_token_finalizer(self):
        self.package('private_retirement')
        module = self.context('private_retirement')
        owner = module.arena()
        observed = weakref.ref(owner)
        ref = owner.retain(object(), 'fixture')
        owner.close()
        del owner
        gc.collect()
        self.assertIsNone(observed())
        self.assertIsNone(module.resolve(ref))

    def test_closed_controller_does_not_block_peers_already_in_boundary(self):
        self.package('private_boundary')
        module = self.context('private_boundary')
        before_replacement, before_recovery, peer = module.arena(), module.arena(), module.arena()
        module.begin_boundary()
        before_replacement.close()
        receipts = module.native_replaced()
        self.assertNotIn(before_replacement, [owner for owner, _ in receipts])
        before_recovery.close()
        module.recovered(receipts)
        self.assertEqual(peer.state.phase, 0)
        self.assertTrue(module.admits('discover'))
        peer.close()

    def test_module_reload_preserves_tokens_and_original_finalizer(self):
        self.package('private_reload')
        module = import_module('private_reload.blender_runtime.ownership.arena')
        context = self.context('private_reload')
        owner = context.arena()
        value = object()
        ref = owner.retain(value, 'before_reload')
        domain = ref.domain
        reloaded = reload(module)
        self.assertEqual(context.domain, domain)
        self.assertIn(owner, context.snapshots())
        self.assertIs(context.resolve(ref), value)
        self.assertFalse(hasattr(reloaded, '_arenas'))
        del ref
        gc.collect()
        self.assertEqual(owner.physical_counts(), (0, 0))
        owner.close()

    def test_finalizer_targets_original_controller_after_registry_replacement(self):
        self.package('private_replacement')
        module = self.context('private_replacement')
        owner, peer = module.arena(), module.arena()
        ref = owner.retain(object(), 'original')
        peer_value = object()
        peer_ref = peer.retain(peer_value, 'replacement')
        # A delayed finalizer must use its original controller even if a host
        # reload/recovery adapter has replaced the package's registry mapping.
        with patch.object(module, '_arenas', {owner.identity: peer}):
            del ref
            gc.collect()
        self.assertEqual(owner.physical_counts(), (0, 0))
        self.assertIs(peer.resolve(peer_ref), peer_value)
        owner.close()
        peer.close()

    def test_two_cpu_extensions_execute_and_shutdown_independently(self):
        handles = []
        for index, name in enumerate(('private_first', 'private_second')):
            target = self.package(name)
            (target / 'operations.py').write_text(
                'from .color_core.linear import convert_rgb\n'
                'def dispatch(operation, inputs, context):\n'
                '    context.checkpoint()\n'
                '    if operation != "convert": raise ValueError(operation)\n'
                '    return {"rgb": convert_rgb(inputs["rgb"], "ACEScg", "Linear Rec.709"),'
                f' "extension": {name!r}}}\n')
            runtime_module = import_module(name + '.blender_runtime.execution.runtime')
            contracts = import_module(name + '.blender_runtime.execution.contracts')
            lane = 'cpu_' + str(index)
            profile = contracts.RuntimeProfile(lanes=(lane,), gpu_probes=(), fallback_lane=lane)
            runtime = runtime_module.ExecutionRuntime(self.root / ('state_' + name), app=self.application(name),
                machines=self.execution_machines(name), package=target,
                profile=profile, limits=contracts.RuntimeLimits(startup_seconds=6., shutdown_seconds=.2),
                environment=dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path)))
            self.runtimes.append(runtime)
            handle = runtime.submit(contracts.JobSpec('convert', {'rgb': (2., .2, .1)}, lane=lane))
            handles.append(handle)
        for index, handle in enumerate(handles):
            result = handle.result(timeout=12)
            self.assertEqual(result['extension'], ('private_first', 'private_second')[index])
            np.testing.assert_allclose(result['rgb'], color.convert_rgb((2., .2, .1), 'ACEScg', 'Linear Rec.709'), rtol=1e-12)
        first, second = self.runtimes
        self.assertNotEqual(first.session.identity, second.session.identity)
        self.assertEqual(set(first.generations), {'cpu_0'})
        self.assertEqual(set(second.generations), {'cpu_1'})
        self.assertEqual(first.gpu_healths, {})
        first.shutdown()
        other_contracts = import_module('private_second.blender_runtime.execution.contracts')
        next_job = second.submit(other_contracts.JobSpec('convert', {'rgb': (.1, .2, .3)}, lane='cpu_1'))
        self.assertEqual(next_job.result(timeout=12)['extension'], 'private_second')
        self.assertTrue(second.session.path.is_dir())

    def test_worker_host_and_value_boundary_are_explicit_inputs(self):
        target = self.package('private_host')
        (target / 'test_host.py').write_text(
            'READY = False\n'
            'def initialize(settings):\n'
            '    global READY\n'
            '    READY = settings["ready"]\n'
            '    return {"backend": "fixture-host"}\n'
            'def diagnostic(gpu_role):\n'
            '    return {"device": "fixture"}\n')
        (target / 'operations.py').write_text(
            'import sys\n'
            'from . import test_host\n'
            'def dispatch(operation, inputs, context):\n'
            '    return {"ready": test_host.READY, "bpy": "bpy" in sys.modules, "value": inputs["value"]}\n')
        runtime_module = import_module('private_host.blender_runtime.execution.runtime')
        contracts = import_module('private_host.blender_runtime.execution.contracts')
        snapshots = []
        def seal_values(value):
            result = seal(value)
            snapshots.append(result)
            return result
        runtime = runtime_module.ExecutionRuntime(self.root / 'host_state', app=self.application('private_host'),
            machines=self.execution_machines('private_host'), package=target,
            profile=contracts.RuntimeProfile(lanes=('bulk',), gpu_probes=()), seal=seal_values,
            worker_host='test_host', host_settings={'ready': True},
            environment=dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path)))
        self.runtimes.append(runtime)
        result = runtime.submit(contracts.JobSpec('fixture', {'value': 7})).result(timeout=12)
        self.assertEqual(dict(result), {'ready': True, 'bpy': False, 'value': 7})
        self.assertEqual(runtime.helpers['bulk'].backend, 'fixture-host')
        self.assertEqual([None if item is None else dict(item) for item in snapshots],
                         [{'value': 7}, None, dict(result)])

    def test_private_blender_service_factories_are_independent(self):
        for name in ('private_service_first', 'private_service_second'):
            self.package(name)
        def factory(name):
            return lambda app: SimpleNamespace(closed=False, fenced=False, name=name,
                                               shutdown=lambda: SimpleNamespace(clean=True))
        first = self.application('private_service_first', execution=factory('first'))
        second = self.application('private_service_second', execution=factory('second'))
        self.assertEqual(first.execution.get_runtime().name, 'first')
        self.assertEqual(second.execution.get_runtime().name, 'second')
        first.close()
        replacement = self.application('private_service_first', execution=factory('replacement'))
        self.assertEqual(replacement.execution.get_runtime().name, 'replacement')
        self.assertEqual(second.execution.get_runtime().name, 'second')

    def test_services_in_one_development_namespace_are_independent(self):
        from color_tools.blender_runtime import App, ExecutionConfig
        def app(name):
            return App(package='fixture', storage_name='fixture', execution=ExecutionConfig(
                lambda app: SimpleNamespace(closed=False, fenced=False, name=name,
                                            shutdown=lambda: SimpleNamespace(clean=True))))
        first, second = app('first'), app('second')
        self.apps.extend((first, second))
        original = first.execution.get_runtime()
        self.assertIs(first.execution.get_runtime(), original)
        self.assertEqual(second.execution.get_runtime().name, 'second')
        first.close()
        replacement = app('reloaded')
        self.apps.append(replacement)
        self.assertEqual(replacement.execution.get_runtime().name, 'reloaded')
        self.assertEqual(second.execution.get_runtime().name, 'second')

    def test_discovery_prerequisites_are_injected_per_package(self):
        for name in ('private_gate_first', 'private_gate_second'):
            self.package(name)
        blocked = [True]
        def require_clean():
            if blocked[0]:
                raise RuntimeError('Product repair required')
        first = self.application('private_gate_first', ownership=True, require_clean=require_clean).ownership
        second = self.context('private_gate_second')
        with self.assertRaisesRegex(RuntimeError, 'Product repair required'):
            first.require_ready()
        second.require_ready()
        blocked[0] = False
        first.require_ready()

    def test_profiles_reject_mutable_and_invalid_configuration(self):
        for kwargs in (
            {'lanes': ['bulk']}, {'lanes': ('bulk', 'bulk')}, {'lanes': ('../bulk',)},
            {'gpu_probes': [('probe', 'gpu')]}, {'gpu_probes': (['probe', 'gpu'],)},
            {'gpu_probes': (('probe', 'missing'),)}, {'fallback_lane': 'gpu'},
            {'uncached_operations': ['scope_register']}, {'uncached_operations': ('same', 'same')},
            {'dispatcher': '../operations'}, {'dispatcher': ''},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                RuntimeProfile(**kwargs)

    def test_value_boundary_copies_arrays_and_rejects_native_graphs(self):
        original = np.arange(12, dtype='f4').reshape(3, 4)
        snapshot = seal({'values': original, 'nested': [1, 2]})
        original[:] = -1
        np.testing.assert_array_equal(snapshot['values'], np.arange(12).reshape(3, 4))
        self.assertEqual(snapshot['nested'], (1, 2))
        with self.assertRaises(ValueError):
            snapshot['values'][0, 0] = 7
        with self.assertRaises(TypeError):
            seal({'brush': object()})
        cycle = []
        cycle.append(cycle)
        with self.assertRaises(ValueError):
            seal(cycle)

    def test_linear_conversion_preserves_hdr_and_roundtrips(self):
        for source in color.SPACES:
            for destination in color.SPACES:
                value = (-.1, 2., 16.)
                converted = color.convert_rgb(value, source, destination)
                np.testing.assert_allclose(color.convert_rgb(converted, destination, source), value, rtol=1e-11, atol=1e-11)
        np.testing.assert_allclose(color.convert_rgb((1., 1., 1.), 'ACEScg', 'Linear Rec.709'), (1., 1., 1.), atol=1e-12)


if __name__ == '__main__':
    unittest.main()

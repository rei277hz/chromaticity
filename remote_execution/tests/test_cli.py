"""Protect portable NativeLink endpoint selection without Docker or network access."""
import contextlib
from importlib.resources import files
import importlib.util
import io
import json
import sys
import unittest
from unittest.mock import call, patch


spec = importlib.util.spec_from_file_location('remote_execution_cli', files(__package__) / 'cli.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class ClientConfigurationTests(unittest.TestCase):
    def config(self, **overrides):
        return dict(image_id='sha256:worker', workspace_container=None) | overrides

    def test_attached_workspace_uses_service_name_without_explicit_flag(self):
        config = self.config()
        with patch.object(cli, 'require_ready') as ready:
            selected = cli.client_config(config)
        self.assertEqual(selected['endpoint'], cli.SERVICE_ENDPOINT)
        self.assertEqual(selected['health_url'], cli.SERVICE_HEALTH)
        ready.assert_called_once_with(selected)
        self.assertNotIn('endpoint', config)

    def test_host_falls_back_to_localhost_when_service_name_is_unreachable(self):
        with patch.object(cli, 'require_ready', side_effect=[RuntimeError('unreachable'), None]) as ready:
            selected = cli.client_config(self.config())
        self.assertEqual(selected['endpoint'], cli.HOST_ENDPOINT)
        self.assertEqual(selected['health_url'], cli.HOST_HEALTH)
        self.assertEqual([row.args[0]['endpoint'] for row in ready.call_args_list],
                         [cli.SERVICE_ENDPOINT, cli.HOST_ENDPOINT])

    def test_saved_workspace_flag_does_not_force_an_endpoint_for_this_process(self):
        config = self.config()
        config['workspace_container'] = 'development'
        with patch.object(cli, 'require_ready', side_effect=[RuntimeError('unreachable'), None]) as ready:
            selected = cli.client_config(config)
        self.assertEqual(selected['endpoint'], cli.HOST_ENDPOINT)
        self.assertEqual([row.args[0]['endpoint'] for row in ready.call_args_list],
                         [cli.SERVICE_ENDPOINT, cli.HOST_ENDPOINT])

    def test_unreachable_named_endpoints_fail_instead_of_reusing_saved_ip(self):
        config = self.config(endpoint='172.19.0.2:50051', health_url='http://172.19.0.2:50052')
        with patch.object(cli, 'require_ready', side_effect=RuntimeError('unreachable')) as ready:
            with self.assertRaisesRegex(RuntimeError, 'No named NativeLink endpoint is ready'):
                cli.client_config(config)
        self.assertEqual([row.args[0]['endpoint'] for row in ready.call_args_list],
                         [cli.SERVICE_ENDPOINT, cli.HOST_ENDPOINT])

    def test_numeric_addresses_cannot_enter_tracked_buckconfig(self):
        for endpoint in ('172.19.0.2:50051', '127.0.0.1:50051', '[::1]:50051'):
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(RuntimeError, 'must use a hostname'):
                    cli.configured_buckconfig('[cells]\n  root = .\n', self.config(endpoint=endpoint))

    def test_named_addresses_keep_other_buckconfig_sections_unchanged(self):
        original = '[cells]\n  root = .\n\n[project]\n  ignore = buck-out\n'
        for endpoint in (cli.SERVICE_ENDPOINT, cli.HOST_ENDPOINT):
            with self.subTest(endpoint=endpoint):
                configured = cli.configured_buckconfig(original, self.config(endpoint=endpoint))
                self.assertTrue(configured.startswith(original))
                for field in ('engine_address', 'action_cache_address', 'cas_address'):
                    self.assertIn(f'  {field} = {endpoint}\n', configured)
                self.assertEqual(cli.configured_buckconfig(configured, self.config(endpoint=endpoint)), configured)

    def test_readiness_requires_a_worker_with_the_expected_image(self):
        config = self.config(endpoint=cli.SERVICE_ENDPOINT, health_url=cli.SERVICE_HEALTH)
        workers = [{
            'is_paused': False,
            'is_draining': False,
            'platform_properties': {'worker-image': 'sha256:other', 'OSFamily': 'linux', 'ISA': 'x86-64'},
        }]
        with patch.object(cli, 'health', side_effect=['ready', json.dumps(workers)]) as health:
            with self.assertRaisesRegex(RuntimeError, 'No registered worker matches'):
                cli.require_ready(config)
        self.assertEqual(health.call_args_list, [
            call(config=config), call('/admin/scheduler/scheduler/workers', config=config),
        ])

    def test_remote_migrates_old_numeric_deployment_before_writing_buckconfig(self):
        config = self.config(endpoint='172.19.0.2:50051', health_url='http://172.19.0.2:50052')
        with patch.object(sys, 'argv', ['re', 'remote']), \
                patch.object(cli, 'settings', return_value=config), \
                patch.object(cli, 'compose', return_value='worker'), \
                patch.object(cli, 'run', return_value=config['image_id']), \
                patch.object(cli, 'require_ready'), \
                patch.object(cli, 'atomic_write') as write, \
                patch.object(cli, 'configure_buck') as configure, \
                contextlib.redirect_stdout(io.StringIO()):
            cli.main()
        migrated = json.loads(write.call_args.args[1])
        self.assertEqual(migrated['endpoint'], cli.SERVICE_ENDPOINT)
        self.assertEqual(migrated['health_url'], cli.SERVICE_HEALTH)
        configure.assert_called_once_with(cli.ROOT, migrated)


if __name__ == '__main__':
    unittest.main()

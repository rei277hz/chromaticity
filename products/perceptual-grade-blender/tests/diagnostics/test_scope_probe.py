"""Diagnostic summaries preserve uncertainty and independent cold runs."""
import importlib.util
from importlib.resources import files
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


def module(name, filename):
    path = str(files('tests.diagnostics') / filename)
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


summary = module('_scope_probe_report_test', 'scope_probe_report.py')
launcher = module('_scope_probe_launcher_test', 'project_probe.py')


class ScopeProbeTests(unittest.TestCase):
    def test_inclusive_phases_are_not_misrepresented_as_additive(self):
        result = summary.summarize([
            dict(event='request_created', capture='a'),
            dict(event='request_created', capture='b'),
            dict(event='phase', capture='a', phase='snapshot', seconds=2.),
            dict(event='phase', capture='a', phase='serialize', seconds=1.5),
            dict(event='phase', capture='b', phase='snapshot', seconds=3.),
            dict(event='wait', capture='b', reason='debounce', count=4, seconds=.3),
            dict(event='wait', capture='b', reason='debounce'),
            dict(event='phase', phase='invalid', seconds=float('nan')),
            dict(event='phase', phase='invalid', seconds=-1),
            dict(event='capture_adopted', helper_timings=dict(render_seconds=.75, worker_entered_at=123.)),
        ])
        self.assertFalse(result['durations_are_additive'])
        self.assertEqual(result['capture_identities'], 2)
        self.assertEqual(result['inclusive_phases']['snapshot'],
                         dict(count=2, seconds=5., max_seconds=3.))
        self.assertEqual(result['reasons'], {'debounce': 5})
        self.assertEqual(result['wait_seconds'], {'debounce': .3})
        self.assertEqual(result['helper_phases']['render_seconds']['seconds'], .75)
        self.assertNotIn('worker_entered_at', result['helper_phases'])
        self.assertNotIn('invalid', result['inclusive_phases'])
        json.dumps(result, allow_nan=False)

    def test_cold_runs_have_independent_outputs_and_retain_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blend = root / 'source.blend'
            blend.write_bytes(b'project')
            output = root / 'report'
            seen = []
            def launch(args, resources, destination):
                seen.append(destination)
                code = 1 if len(seen) == 2 else 0
                launcher.write_json(destination / 'launch.json', dict(passed=code == 0, source='same'))
                launcher.write_json(destination / 'report.json', dict(passed=code == 0))
                return code
            arguments = ['project_probe', '--blend', str(blend), '--output-dir', str(output),
                         '--mode', 'scopes', '--cold-runs', '3', '--scope-diagnostics',
                         '--scope-owner', 'material', '--material', 'Paint', '--workspace', 'Shading']
            with patch.object(sys, 'argv', arguments), patch.object(launcher, 'launch', launch), \
                    patch.object(launcher, 'files', return_value=object()):
                self.assertEqual(launcher.main(), 1)
            self.assertEqual([item.name for item in seen], ['cold-1', 'cold-2', 'cold-3'])
            result = json.loads((output / 'summary.json').read_text())
            self.assertFalse(result['passed'])
            self.assertEqual(len(result['runs']), 3)
            self.assertEqual(blend.read_bytes(), b'project')

    def test_scopes_only_options_are_rejected_for_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blend = root / 'source.blend'
            blend.touch()
            arguments = ['project_probe', '--blend', str(blend), '--output-dir', str(root / 'out'),
                         '--mode', 'inspect', '--gui']
            with patch.object(sys, 'argv', arguments), self.assertRaises(SystemExit):
                launcher.main()


if __name__ == '__main__':
    unittest.main()

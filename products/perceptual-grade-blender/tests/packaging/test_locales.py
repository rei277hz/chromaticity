"""Catalog/compiler contracts without documentation CSV tooling."""
import ast
import gettext
from importlib.resources import files
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import contextmanager
from color_tools.perceptual_grade_blender.localization import i18n as i18n_factory
from color_tools.blender_runtime.execution.diagnostics import Failure
from color_tools.perceptual_grade_core.model import linear
from tools.compile_locales import compile_catalogs, fields


BAKE_BLOCKERS = (
    'checking', 'waiting', 'playback', 'busy', 'queue', 'resources',
    'destination', 'dirty', 'window', 'destination_domain', 'cycles', 'world_uv',
    'shader_to_rgb', 'unavailable', 'dimensions', 'source_empty', 'input_links', 'world_scene',
    'occurrence', 'owner', 'source_unbound', 'source_sequence', 'source_udim', 'source_type',
    'source_multiview', 'source_multilayer', 'cycle', 'group_tree', 'group_output', 'baked_unbound',
    'uv_degenerate', 'uv_empty', 'uv_complex', 'uv_overlap', 'uv_tile', 'mesh',
    'uv_missing', 'uv_incomplete', 'mesh_cache', 'material_slot', 'mesh_scene', 'mesh_hidden',
    'upstream', 'failed', 'target',
)

class LocaleTests(unittest.TestCase):
    def setUp(self):
        self.i18n = i18n_factory.create(None)

    @contextmanager
    def language(self, locale):
        previous = self.i18n.language
        self.i18n.language = lambda: locale
        try:
            yield
        finally:
            self.i18n.language = previous

    def test_core_diagnostics_are_translated_at_presentation_time(self):
        cases = (
            ('error.singular_basis', lambda: linear.inverse(((0., 0., 0.),) * 3)),
            ('error.invalid_xy', lambda: linear.xyz((0., 0.))),
            ('error.nonfinite_parameter', lambda: linear.safe_source_white((float('nan'), 0.))),
        )
        for message_id, action in cases:
            with self.subTest(message_id=message_id), self.assertRaises(ValueError) as caught:
                action()
            error = caught.exception
            diagnostic = str(error)
            receipt = Failure.capture(error)
            self.assertEqual(diagnostic, self.i18n.CATALOGS['en'][message_id])
            for locale in ('zh_HANS', 'en'):
                with self.language(locale):
                    self.assertEqual(self.i18n.error_text(error), self.i18n.CATALOGS[locale][message_id])
                    self.assertEqual(self.i18n.error_text(diagnostic), self.i18n.CATALOGS[locale][message_id])
                    self.assertEqual(self.i18n.error_text(receipt.exception('Preparation failed')),
                                     self.i18n.CATALOGS[locale][message_id])
            self.assertEqual(str(error), diagnostic)
        self.assertEqual(self.i18n.error_text(ValueError('Other failure'), locale='zh_HANS'),
                         self.i18n.CATALOGS['zh_HANS']['outcome.failed'])

    def test_tone_white_distribution_and_stack_terminology(self):
        en, zh = self.i18n.CATALOGS['en'], self.i18n.CATALOGS['zh_HANS']
        white_stems = ('adaptance_a', 'adaptance_b', 'j_low', 'j_high', 'j_a', 'j_b',
                       'c_low', 'c_high', 'c_a', 'c_b', 'hue', 'concentration_a', 'concentration_b')
        white_keys = {'tone.white', 'marker.tone.W', 'control.input_white.label', 'tooltip.tone.white'}
        white_keys.update(f'control.{stem}_2.label' for stem in white_stems)
        white_keys.update(f'tooltip.color.{stem}.white' for stem in white_stems)
        self.assertEqual(len(white_keys), 30)
        self.assertEqual({key for key, value in zh.items() if '白调' in value}, white_keys)
        for key, expected in {'marker.white.D': '白', 'white.source.label': '源白点',
                              'white.destination.label': '目标白点', 'white.e': '等能白 E',
                              'family.warp.label': '塑形', 'grade.white.label': '工作白点'}.items():
            self.assertEqual(zh[key], expected)
        for key in ('diagram.adaptance.statistics', 'tooltip.gizmo.selected_dot',
                    'tooltip.gizmo.neutral_statistics'):
            self.assertIn('95% distribution region', en[key].lower())
            self.assertIn('95% 分布范围', zh[key])
        self.assertEqual(zh['direction.inverse'], '逆向')
        self.assertEqual(zh['stack.name'], '感知调色栈')
        self.assertEqual(zh['node.stack.title'], '调色栈')
        self.assertFalse(any('堆栈' in value or '反向' in value for value in zh.values()))
        self.assertNotIn('installed', en['tooltip.scope.stack.output'])
        self.assertNotIn('LUT', zh['tooltip.scope.stack.output'])
        self.assertEqual({key for key in en if key.startswith('bake.')}, {
            'bake.error', 'bake.failed_render', 'bake.label', 'bake.tooltip',
            'bake.add.label', 'bake.add.tooltip', 'bake.node.label', 'bake.node.tooltip',
            'bake.status', 'bake.empty', 'bake.output.label',
            'bake.destination.label', 'bake.destination.tooltip',
            'bake.queued', 'bake.publish_wait', 'bake.interrupted', 'bake.inputs_changed',
            'bake.route.image', 'bake.route.uv', 'bake.route.linked_coordinates',
            'bake.route.surface_dependency', 'bake.route.multiple_images',
            'bake.route.existing_uv_binding', 'bake.route.image_source',
            'bake.route.constant', 'bake.vector.tooltip', 'bake.new', 'bake.new.tooltip',
            'bake.unlink', 'bake.unlink.tooltip', 'bake.check'} |
            {f'bake.blocked.{code}' for code in BAKE_BLOCKERS})
        self.assertIn('scope.stack.waiting', en)

    def test_catalog_keys_have_runtime_or_dctl_consumers(self):
        # String literals also cover labels passed through tuples and helpers.
        # Finite computed families are listed explicitly: a prefix wildcard
        # would silently retain an obsolete key added to that family.
        runtime = files('color_tools.perceptual_grade_blender')
        core = files('color_tools.perceptual_grade_core')
        catalog = set(self.i18n.CATALOGS['en'])
        used, required = set(), set()
        for path in (*runtime.rglob('*.py'), *core.rglob('*.py')):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    used.add(node.value)
                if isinstance(node, ast.Call) and node.args:
                    name = getattr(node.func, 'id', getattr(node.func, 'attr', ''))
                    if name in {'M', 'tr', 'native', 'tip'} and isinstance(node.args[0], ast.Constant):
                        if isinstance(node.args[0].value, str):
                            required.add(node.args[0].value)
        bindings = json.loads((core / 'localization/bindings.json').read_text())
        labels = json.loads((core / 'localization/control-labels.json').read_text())
        required.update(bindings.values())
        required.update(labels['labels'].values())
        required.update(labels['readouts'].values())
        controls = json.loads((files('tests.packaging') / 'dctl_sources/ui-spec.json').read_text())
        for control in controls:
            required.update((control['label_id'], control['tooltip_id']))
            if control['options']:
                required.update(control['options'][1])
        for kind, values in (('tone', 'BSMWH'), ('scope', 'RYGCBM'), ('white', 'SD')):
            required.update(f'marker.{kind}.{value}' for value in values)
        required.update(f'bake.blocked.{code}' for code in BAKE_BLOCKERS)
        required.update(f'tone.{name}' for name in ('black', 'shadows', 'midtones', 'white', 'highlights'))
        required.update(f'tooltip.stack.{action}' for action in ('add', 'remove', 'up', 'down'))
        required.update(f'tooltip.scope.stack.{side}' for side in ('input', 'output'))
        required.update(f'diagram.{family}.{kind}' for family in ('j', 'c') for kind in ('ab_units', 'ab_label'))
        self.assertFalse(required - catalog, sorted(required - catalog))
        self.assertFalse(catalog - (used | required), sorted(catalog - (used | required)))

    def test_runtime_catalogs_native_bridge_and_placeholders(self):
        english = self.i18n.CATALOGS['en']
        for locale, messages in self.i18n.CATALOGS.items():
            self.assertEqual(messages.keys(), english.keys())
            bridge = self.i18n.host_messages(locale)
            resource = files('color_tools.perceptual_grade_core') / 'locales' / locale / 'LC_MESSAGES' / 'perceptual_grade.mo'
            with resource.open('rb') as stream:
                compiled = gettext.GNUTranslations(stream)
            for key, value in messages.items():
                self.assertEqual(compiled.gettext(key), value)
                self.assertEqual(self.i18n.tr(key, locale=locale), value)
                self.assertEqual(fields(value), fields(english[key]))
                if key.startswith('tooltip.') or key == 'bake.vector.tooltip':
                    self.assertEqual(bridge['*', english[key]], value)
        with self.assertRaises(KeyError):
            self.i18n.tr('unknown.message')

    def test_third_locale_discovery_and_invalid_catalogs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalogs = root / 'catalogs'
            catalogs.mkdir()
            for source in (files('tests.packaging') / 'catalogs').glob('*.json'):
                (catalogs / source.name).write_bytes(source.read_bytes())
            messages = json.loads((catalogs / 'en.json').read_text())
            french = dict(messages, **{'product.name': 'Synthetic third locale'})
            path = catalogs / 'fr_FR.json'
            path.write_text(json.dumps(french))
            compile_catalogs(catalogs, root / 'compiled')
            with (root / 'compiled/fr_FR/LC_MESSAGES/perceptual_grade.mo').open('rb') as stream:
                self.assertEqual(gettext.GNUTranslations(stream).gettext('product.name'), 'Synthetic third locale')
            broken = dict(french)
            broken.pop('product.name')
            for value in (broken, {**french, 'error.grade_bypassed': 'Missing format field'}, {**french, 'product.name': ''}):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    compile_catalogs(catalogs, root / 'invalid')

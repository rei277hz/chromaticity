"""Check the two-book source projections and their combined Buck-built site."""
import ast
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import tomllib
import unittest
from urllib.parse import urlsplit
from xml.etree import ElementTree
import zipfile

from pg_book_build import assemble, languages, parts, site, zip_utils


NUMERICAL_CHARTS = {
    'linear-basis', 'tone-curves', 'tone-saturation', 'color-tone-weights',
    'color-drivers', 'color-hue-concentration', 'guard-boundary', 'guard-energy',
    'lut-input-grid', 'lut-interpolation', 'render-benchmark',
}
HISTORICAL_CHARTS = {
    'lut-shaper-errors', 'lut-shaper-placement',
    'lut-domain128-errors', 'lut-domain128-placement',
}
CHART_PATHS = {
    name: f'assets/{directory}/{name}.svg'
    for directory, names in (('figures', NUMERICAL_CHARTS), ('illustrations', HISTORICAL_CHARTS))
    for name in names
}
EDITIONS = {
    'user-manual': {'en': 'manual/en', 'zh-Hans': 'manual/zh-Hans'},
    'technical-report': {'en': 'technical/en'},
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(root):
    return {path.relative_to(root).as_posix(): sha(path)
            for path in sorted(root.rglob('*')) if path.is_file()}


def markdown_files(root):
    return {path.relative_to(root).as_posix() for path in root.rglob('*.md')
            if path.name != 'SUMMARY.md'
            and path.relative_to(root).parts[0] not in ('assets', 'downloads')}


def selected_chapters(root, directories):
    return {'README.md'} | {
        path.relative_to(root).as_posix()
        for directory in directories for path in (root / directory).rglob('*.md')
    }


def assignment(path, name):
    for statement in ast.parse(path.read_text()).body:
        if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name
                for target in statement.targets):
            return ast.literal_eval(statement.value)
    raise AssertionError(f'Missing {name} in {path}')


class BookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = Path(__file__).parent
        cls.docs = cls.resources / 'docs'
        cls.historical = cls.resources / 'historical'
        cls.inputs = cls.resources / 'book-inputs'
        cls.assets = [cls.resources / name for name in
                      ('generated-assets', 'diagram-assets', 'cdn-assets', 'data-downloads')]
        cls.output = (cls.resources / 'site').resolve()
        cls.book = cls.docs / 'book'
        cls.manifest_path = cls.resources / 'historical-manifest.json'
        cls.manifest = json.loads(cls.manifest_path.read_text())
        cls.publication = json.loads((cls.output / 'site-manifest.json').read_text())
        cls.manual = cls.inputs / 'user-manual'
        cls.report = cls.inputs / 'technical-report'
        manual_chapters, manual_localized = site.check_language_chapters(cls.manual)
        report_chapters = site.check_chapters(cls.report)
        cls.chapters = {'user-manual': manual_chapters, 'technical-report': report_chapters}
        cls.localized = {'user-manual': manual_localized,
                         'technical-report': {'en': report_chapters}}

    def test_authored_and_generated_inputs_are_assembled(self):
        self.assertEqual(self.manifest['schema'], 1)
        self.assertEqual(inventory(self.historical), self.manifest['files'])
        sources = inventory(self.book)
        for root in [*self.assets, self.historical]:
            incoming = inventory(root)
            self.assertFalse(sources.keys() & incoming.keys())
            sources.update(incoming)
        self.assertEqual({path.name for path in self.inputs.iterdir()}, set(EDITIONS))
        for book_name in EDITIONS:
            assembled = self.inputs / book_name
            self.assertFalse((assembled / 'src/vendor').exists())
            config = tomllib.loads((assembled / 'book.toml').read_text())
            title = 'User Manual' if book_name == 'user-manual' else 'Technical Report'
            self.assertEqual(config['book']['title'], 'Perceptual Grade ' + title)
            for name, digest in inventory(assembled).items():
                with self.subTest(book=book_name, path=name):
                    if name == 'book.toml' or name.endswith('/SUMMARY.md'):
                        continue
                    original = ('src/report/README.md'
                                if book_name == 'technical-report' and name == 'src/README.md'
                                else name)
                    self.assertIn(original, sources)
                    self.assertEqual(digest, sources[original])
            for name, digest in sources.items():
                if name.startswith(('src/assets/', 'src/downloads/', 'theme/', 'diagrams/')):
                    if name.startswith('src/downloads/') and name.endswith('.md'):
                        continue
                    with self.subTest(book=book_name, shared=name):
                        self.assertEqual(sha(assembled / name), digest)

    def test_books_cover_the_authored_content_with_the_requested_languages(self):
        manual_chapters = selected_chapters(self.book / 'src', ('guide', 'reference'))
        report_chapters = selected_chapters(self.book / 'src', ('theory', 'development', 'reference'))
        report_downloads = {
            path.relative_to(self.book / 'src').as_posix()
            for path in (self.book / 'src/downloads').rglob('*.md')
        }
        for language, directory in (('en', 'src'), ('zh-Hans', 'zh-Hans')):
            with self.subTest(language=language):
                self.assertEqual(markdown_files(self.manual / directory), manual_chapters)
                self.assertEqual(set(self.localized['user-manual'][language]), manual_chapters)
                self.assertEqual(selected_chapters(self.book / directory, ('guide', 'reference')),
                                 manual_chapters)
                for excluded in ('theory', 'development', 'report'):
                    self.assertFalse((self.manual / directory / excluded).exists())
        self.assertEqual(markdown_files(self.report / 'src'), report_chapters)
        self.assertEqual({path.relative_to(self.report / 'src').as_posix()
                          for path in (self.report / 'src/downloads').rglob('*.md')},
                         report_downloads)
        self.assertEqual(set(self.localized['technical-report']['en']), report_chapters)
        self.assertFalse((self.report / 'zh-Hans').exists())
        self.assertFalse((self.report / 'src/guide').exists())
        self.assertFalse((self.output / 'technical/zh-Hans').exists())
        source_chapters = markdown_files(self.book / 'src') - {'report/README.md'}
        self.assertEqual(manual_chapters | report_chapters, source_chapters)

    def test_each_edition_preserves_its_authored_summary(self):
        for assembled, authored in (
                ('user-manual/src/SUMMARY.md', 'src/SUMMARY.md'),
                ('user-manual/zh-Hans/SUMMARY.md', 'zh-Hans/SUMMARY.md'),
                ('technical-report/src/SUMMARY.md', 'src/report/SUMMARY.md')):
            with self.subTest(edition=assembled):
                self.assertEqual((self.inputs / assembled).read_bytes(),
                                 (self.book / authored).read_bytes())

    def test_every_manual_chapter_has_substantive_chinese_content(self):
        for chapter in self.localized['user-manual']['en']:
            with self.subTest(chapter=chapter):
                english = (self.manual / 'src' / chapter).read_text()
                chinese = (self.manual / 'zh-Hans' / chapter).read_text()
                body = '\n'.join(line for line in chinese.splitlines()
                                 if not line.startswith(('#', '>')))
                self.assertGreater(len(re.findall(r'[\u3400-\u9fff]', body)), 100)
                self.assertEqual(re.findall(r'^(#{2,6}) ', chinese, re.M),
                                 re.findall(r'^(#{2,6}) ', english, re.M))

    def test_core_chinese_workflow_chapters_are_complete_translations(self):
        controls = {
            'workflow': ('Linear', 'Tone', 'Color', 'SDR', 'HDR', 'sRGB', 'Dummy recording'),
            'linear': ('Source White', 'Global Exposure', 'Balance', 'Spread', 'Heading',
                       'Color Reference', 'Render Layers', 'ACEScg'),
            'tone': ('Input Black Nits', 'Input Highlights Nits', 'Reference Nits',
                     'Peak Anchor Nits', 'Remap Fit', '203', '4000'),
            'color': ('Lightness Fit', 'Chroma Fit', 'Global C Gain', 'Adaptance Strength',
                      'Adaptance Fit', 'Hue Fit', 'Global Cₗ → Hue', 'Global Cₕ → Hue'),
        }
        for name, required in controls.items():
            with self.subTest(chapter=name):
                english = (self.manual / 'src/guide' / (name + '.md')).read_text()
                chinese = (self.manual / 'zh-Hans/guide' / (name + '.md')).read_text()
                # A title and scope notice cannot satisfy a translated chapter.
                body = '\n'.join(line for line in chinese.splitlines()
                                 if not line.startswith(('#', '>')))
                self.assertGreater(len(re.findall(r'[\u3400-\u9fff]', body)), 300)
                self.assertEqual(len(re.findall(r'^## ', chinese, re.M)),
                                 len(re.findall(r'^## ', english, re.M)))
                self.assertEqual(re.findall(r'(?:src|data-still)="([^"]+)"', chinese),
                                 re.findall(r'(?:src|data-still)="([^"]+)"', english))
                self.assertEqual(re.findall(r'\]\(([^)]+)\)', chinese),
                                 re.findall(r'\]\(([^)]+)\)', english))
                self.assertEqual(re.findall(r'\\\((.*?)\\\)', chinese),
                                 re.findall(r'\\\((.*?)\\\)', english))
                self.assertIn('1.23.2', chinese)
                for marker in required:
                    self.assertIn(marker, chinese)

    def test_both_license_pages_explain_source_and_release_terms(self):
        repository = 'https://github.com/rei277hz/chromaticity/blob/main/'
        for book_name, language, directory in (
                ('user-manual', 'en', 'src'), ('user-manual', 'zh-Hans', 'zh-Hans'),
                ('technical-report', 'en', 'src')):
            source = (self.book / directory / 'reference/license.md').read_text()
            rendered = html.unescape(
                (self.output / EDITIONS[book_name][language] / 'reference/license.html').read_text())
            for stage, text in (('source', source), ('rendered', rendered)):
                with self.subTest(book=book_name, language=language, stage=stage):
                    for marker in ('MIT OR Apache-2.0', 'GPL-3.0-or-later',
                                   'Corresponding Source', 'DCTL', 'CC0 1.0',
                                   'git archive', '1.23.2'):
                        self.assertIn(marker, text)
                    for license_name in ('LICENSE-MIT', 'LICENSE-APACHE'):
                        self.assertIn(repository + license_name, text)
        credits = (self.book / 'src/reference/credits.md').read_text()
        self.assertIn('DetMCD.pdf', credits)
        self.assertIn('asymptotic Gaussian', credits)

    def test_generated_provenance_uses_stable_input_names(self):
        for name in ('numerical-figures', 'photographic-figures', 'host-screenshots',
                     'next-policy-diagrams'):
            document = self.output / 'downloads/provenance' / (name + '.json')
            provenance = json.loads(document.read_text())
            self.assertEqual(provenance['invocation'], 'buck2')
            self.assertTrue(provenance['inputs'])
            self.assertTrue(provenance['outputs'])
            for filename, digest in provenance['inputs'].items():
                with self.subTest(producer=name, input=filename):
                    path = PurePosixPath(filename)
                    self.assertFalse(path.is_absolute())
                    self.assertNotIn('..', path.parts)
                    self.assertNotIn('buck-out', path.parts)
                    self.assertRegex(digest, r'^[0-9a-f]{64}$')

    def test_rendered_links_and_manifest(self):
        checks = site.validate_site(self.output)
        self.assertEqual(checks['cdn_font_files'], 2)
        self.assertEqual(checks['cdn_katex_files'], 2)
        self.assertGreater(checks['html_pages'], sum(
            len(chapters) for editions in self.localized.values() for chapters in editions.values()))
        self.assertEqual(self.publication['validation'], checks)
        self.assertEqual(self.publication['invocation'], 'buck2')
        self.assertEqual(self.publication['build_target'],
                         'root//products/perceptual-grade-book:site')
        self.assertEqual(self.publication['tools'],
                         site.tool_pins(self.resources / 'tool-pins.bzl',
                                        self.resources / 'rust-versions.json'))
        self.assertEqual(self.publication['rust_dependencies'],
                         json.loads((self.resources / 'rust-versions.json').read_text()))
        self.assertEqual(self.publication['rust_dependencies_sha256'],
                         sha(self.resources / 'rust-versions.json'))
        self.assertNotIn('archives', self.publication['tools']['mdbook'])
        self.assertEqual(self.publication['tool_definitions_sha256'],
                         sha(self.resources / 'tool-pins.bzl'))
        self.assertEqual(self.publication['builder_sha256'], sha(site.__file__))
        self.assertEqual(self.publication['part_numbering_sha256'], sha(parts.__file__))
        self.assertEqual(self.publication['language_builder_sha256'], sha(languages.__file__))
        self.assertEqual((self.resources / 'site-manifest.json').read_bytes(),
                         (self.output / 'site-manifest.json').read_bytes())
        actual = inventory(self.output)
        actual.pop('site-manifest.json')
        self.assertEqual(actual, self.publication['site_files'])
        self.assertEqual(self.publication['input_files'], inventory(self.inputs))

    def test_book_editions_and_navigation(self):
        self.assertEqual(self.publication['languages'], self.localized)
        self.assertEqual(self.publication['chapters'], self.chapters)
        for book_name, editions in EDITIONS.items():
            for language, route in editions.items():
                edition = self.output / route
                for chapter in self.localized[book_name][language]:
                    with self.subTest(book=book_name, language=language, chapter=chapter):
                        page = 'index.html' if chapter == 'README.md' else chapter.removesuffix('.md') + '.html'
                        text = (edition / page).read_text()
                        self.assertIn(f'<html lang="{language}"', text)
                        self.assertNotIn('class="nav-wrapper"', text)
                        if book_name == 'user-manual':
                            self.assertIn('class="language-picker"', text)
                            self.assertIn('data-book-language="en"', text)
                            self.assertIn('data-book-language="zh-Hans"', text)
                            self.assertNotIn('class="language-unavailable"', text)
                        else:
                            self.assertNotIn('class="language-picker"', text)
                            self.assertNotIn('hreflang="zh-Hans"', text)
                search = next(edition.glob('searchindex-*.js')).read_text()
                section = 'guide' if book_name == 'user-manual' else 'theory'
                for page in (section + '/linear.html', 'reference/credits.html'):
                    self.assertIn(page, search)
                excluded = ('theory/', 'development/') if book_name == 'user-manual' else ('guide/',)
                toc = (edition / 'toc.html').read_text()
                for prefix in excluded:
                    self.assertNotIn('href="' + prefix, toc)
                    self.assertNotIn(prefix + 'linear.html', search)
                numbers = dict(re.findall(
                    r'<a href="([^"]+)"[^>]*><strong aria-hidden="true">([^<]+)</strong>', toc))
                if book_name == 'user-manual':
                    self.assertEqual(numbers['guide/install.html'], '1.')
                    self.assertEqual(numbers['guide/linear.html'], '2.1.')
                else:
                    self.assertEqual(numbers['theory/linear.html'], '1.')
                    self.assertEqual(numbers['development/architecture.html'], '1.')
                self.assertNotRegex(toc, r'href="[^"]*#')
        chinese_search = next((self.output / 'manual/zh-Hans').glob('searcher-*.js')).read_text()
        self.assertIn('window.PGChineseSearch.create', chinese_search)
        self.assertTrue((self.output / 'manual/chinese-search.js').is_file())
        self.assertIn('data-language-entry="true"', (self.output / 'manual/index.html').read_text())
        landing = self.output / 'index.html'
        targets = {site.local_target(self.output, landing, ref, False)
                   for ref, runtime in site.Page(landing.read_text()).refs if not runtime}
        self.assertIn(self.output / 'manual/index.html', targets)
        self.assertIn(self.output / 'technical/en/index.html', targets)
        self.assertFalse((self.output / 'en').exists())
        self.assertFalse((self.output / 'zh-Hans').exists())

    def test_cross_book_links_reach_the_correct_edition(self):
        destinations = (
            ('manual/en/index.html', 'technical/en/index.html'),
            ('manual/zh-Hans/index.html', 'technical/en/index.html'),
            ('technical/en/index.html', 'manual/en/index.html'),
            ('manual/en/guide/install.html', 'technical/en/theory/structure.html'),
            ('manual/zh-Hans/guide/install.html', 'technical/en/theory/structure.html'),
            ('technical/en/theory/structure.html', 'manual/en/guide/working-white.html'),
        )
        for origin, destination in destinations:
            page = self.output / origin
            with self.subTest(origin=origin, destination=destination):
                targets = {site.local_target(self.output, page, ref, False)
                           for ref, runtime in site.Page(page.read_text()).refs if not runtime}
                self.assertIn(self.output / destination, targets)

    def test_current_reference_scope_and_stage_three_contract(self):
        source = self.report / 'src'
        intro = (source / 'README.md').read_text()
        color = (source / 'theory/color.md').read_text()
        guard = (source / 'theory/hk-guard.md').read_text()
        tone = (source / 'theory/tone.md').read_text()
        self.assertIn('libraries/perceptual-grade-reference', intro)
        self.assertIn('WarpRepairedScale.lean', color)
        self.assertIn('hk_guard=True', color)
        self.assertIn('hk_guard=False', color)
        self.assertIn('HKCubeLuminance.lean', guard)
        self.assertIn('hk_cube_guard_positive_luminance', guard)
        self.assertIn('E_g=E_{\\mathrm{req}}', guard)
        self.assertIn('H>0', guard)
        self.assertIn('E_0>0', guard)
        self.assertIn('W>0', guard)
        self.assertIn('0.015507796089266005', tone)
        self.assertIn('0.037153526983', tone)
        order = ('3. Selective cone Adaptance',
                 '4. With the default guard enabled, [H–K repair]',
                 "5. The web's final positive scale")
        positions = [color.index(step) for step in order]
        self.assertEqual(positions, sorted(positions))
        rendered = html.unescape((self.output / 'technical/en/theory/color.html').read_text())
        self.assertIn('WarpRepairedScale.lean', rendered)
        self.assertIn('HKCubeLuminance.lean', html.unescape(
            (self.output / 'technical/en/theory/hk-guard.html').read_text()))

    def test_next_policy_chapter_is_only_in_the_english_edition(self):
        relative = 'development/next-policies.html'
        for route in ('manual/en', 'manual/zh-Hans', 'technical/en'):
            edition = self.output / route
            is_report = route == 'technical/en'
            with self.subTest(route=route):
                self.assertEqual((edition / relative).is_file(), is_report)
                for text in ((edition / 'toc.html').read_text(),
                             next(edition.glob('searchindex-*.js')).read_text()):
                    self.assertEqual(relative in text, is_report)
                printable = (edition / 'print.html').read_text()
                self.assertEqual('illustrations/next-policy/' in printable, is_report)

    def test_next_policy_figures_are_accessible_declared_svg_outputs(self):
        provenance = json.loads((self.output / 'downloads/provenance/next-policy-diagrams.json').read_text())
        self.assertEqual(provenance['renderer']['name'], 'D2')
        self.assertEqual(provenance['renderer']['version'], '0.9.0')
        expected_names = {
            '00-policy-layer', '01-preparation', '01b-preparation-join',
            '02-node', '03-helper', '04-bank-publication',
            '05-parameter-publication', '05b-image-publication',
            '05c-compositor-publication', '06-resources', '07-gesture',
            '07b-gesture-participants', '08-render-preflight',
        }
        self.assertEqual(set(provenance['outputs']), {
            f'assets/illustrations/next-policy/{name}.svg' for name in expected_names
        })
        chapter = self.output / 'technical/en/development/next-policies.html'
        referenced = {site.local_target(self.output, chapter, ref, False)
                      for ref, _ in site.Page(chapter.read_text()).refs
                      if 'illustrations/next-policy/' in ref}
        self.assertEqual(referenced, {self.output / name for name in provenance['outputs']})
        svg_namespace = '{http://www.w3.org/2000/svg}'
        for name, expected_hash in provenance['outputs'].items():
            with self.subTest(figure=name):
                path = self.output / name
                self.assertEqual(sha(path), expected_hash)
                root = ElementTree.parse(path).getroot()
                self.assertEqual(root.tag, svg_namespace + 'svg')
                self.assertEqual(root.get('role'), 'img')
                self.assertTrue(root.get('viewBox'))
                for dimension in ('width', 'height'):
                    self.assertGreater(int(root.get(dimension)), 0)
                labels = root.get('aria-labelledby', '').split()
                self.assertEqual(len(labels), 2)
                for element_name, label in zip(('title', 'desc'), labels):
                    element = root.find(svg_namespace + element_name + f'[@id="{label}"]')
                    self.assertIsNotNone(element)
                    self.assertTrue(element.text)

    def test_numerical_charts_are_accessible_static_vectors(self):
        svg_namespace = '{http://www.w3.org/2000/svg}'
        self.assertEqual(len(CHART_PATHS), 15)
        provenance = json.loads((self.output / 'downloads/provenance/numerical-figures.json').read_text())
        self.assertEqual(provenance['renderer']['name'], 'PGFPlots')
        self.assertEqual({name for name in provenance['outputs'] if name.startswith('images/')},
                         {f'images/{name}.svg' for name in CHART_PATHS})
        for name, relative in CHART_PATHS.items():
            with self.subTest(chart=name):
                path = self.output / relative
                self.assertTrue(path.is_file())
                self.assertFalse(path.with_suffix('.png').exists())
                self.assertEqual(sha(path), provenance['outputs'][f'images/{name}.svg'])
                self.assertEqual(path.read_bytes(), (self.report / 'src' / relative).read_bytes())
                root = ElementTree.parse(path).getroot()
                self.assertEqual(root.tag, svg_namespace + 'svg')
                self.assertEqual(root.get('role'), 'img')
                self.assertTrue(root.get('viewBox'))
                for dimension in ('width', 'height'):
                    self.assertGreater(int(root.get(dimension)), 0)
                # At 96 dpi, 605 by 661 CSS pixels fit the 160 by 175 mm
                # print bounds without shrinking chart labels.
                self.assertLessEqual(int(root.get('width')), 605)
                self.assertLessEqual(int(root.get('height')), 661)
                labels = root.get('aria-labelledby', '').split()
                self.assertEqual(len(labels), 2)
                for tag, identifier in zip(('title', 'desc'), labels):
                    element = root.find(svg_namespace + tag + f'[@id="{identifier}"]')
                    self.assertIsNotNone(element)
                    self.assertTrue(element.text and element.text.strip())
                ids = {element.get('id') for element in root.iter() if element.get('id')}
                for element in root.iter():
                    tag = element.tag.rsplit('}', 1)[-1]
                    self.assertNotIn(tag, {'image', 'script', 'foreignObject', 'text', 'animate',
                                           'animateMotion', 'animateTransform', 'set'})
                    for key, value in element.attrib.items():
                        attribute = key.rsplit('}', 1)[-1]
                        self.assertFalse(attribute.lower().startswith('on'))
                        if attribute in ('href', 'src'):
                            self.assertTrue(value.startswith('#'), value)
                            self.assertIn(value[1:], ids)
                css = '\n'.join(element.text or '' for element in root.iter()
                                if element.tag == svg_namespace + 'style')
                css += '\n' + '\n'.join(value for element in root.iter()
                                         for value in element.attrib.values())
                self.assertNotIn('@import', css.lower())
                for resource in re.findall(r'url\(\s*[\'"]?([^\)\'"\s]+)', css):
                    self.assertTrue(resource.startswith('#'), resource)
                    self.assertIn(resource[1:], ids)

        for route in ('manual/en', 'manual/zh-Hans', 'technical/en'):
            page = self.output / route / 'print.html'
            parsed = site.Page(page.read_text())
            references = {}
            linked = {site.local_target(self.output, page, ref, False)
                      for ref, runtime in parsed.refs if not runtime
                      and Path(urlsplit(ref).path).stem in CHART_PATHS}
            for tag, attrs in parsed.runtime_tags:
                if tag != 'img' or Path(urlsplit(attrs.get('src', '')).path).stem not in CHART_PATHS:
                    continue
                name = Path(urlsplit(attrs['src']).path).stem
                with self.subTest(route=route, chart=name):
                    expected = self.output / CHART_PATHS[name]
                    self.assertEqual(site.local_target(self.output, page, attrs['src'], True), expected)
                    self.assertIn(expected, linked)
                    self.assertTrue(attrs.get('alt', '').strip())
                    self.assertGreater(int(attrs['width']), 0)
                    self.assertGreater(int(attrs['height']), 0)
                    references[name] = expected
            expected_names = set(CHART_PATHS) if route == 'technical/en' else set()
            self.assertEqual(set(references), expected_names)

    def test_chart_source_archive_contains_portable_sources_and_data(self):
        provenance = json.loads((self.output / 'downloads/provenance/numerical-figures.json').read_text())
        path = self.output / 'downloads/chart-sources.zip'
        self.assertEqual(sha(path), provenance['outputs']['chart-sources.zip'])
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(set(names)))
            self.assertEqual({name for name in names if name.startswith('plots/')},
                             {f'plots/{name}.tex' for name in CHART_PATHS})
            self.assertTrue(any(name.startswith('tables/') and name.endswith('.dat') for name in names))
            for required in ('figures.json', 'manifest.json', 'numerical-data.json',
                             'plot-style.tex', 'font-paths.tex',
                             'fonts/Tinos-Regular.ttf', 'fonts/Tinos-Bold.ttf',
                             'fonts/Tinos-Italic.ttf', 'fonts/Tinos-BoldItalic.ttf',
                             'fonts/Tinos-OFL.txt', 'fonts/texgyretermes-math.otf',
                             'fonts/TeX-Gyre-Math-LICENSE.txt',
                             'fragments/lut-shaper-key.md', 'fragments/lut-domain128-key.md'):
                self.assertIn(required, names)
                self.assertTrue(archive.read(required))
            figures = json.loads(archive.read('figures.json'))['figures']
            self.assertEqual({figure['id'] for figure in figures}, set(CHART_PATHS))
            scopes = {figure['id']: figure['scope'] for figure in figures}
            self.assertEqual({name for name, scope in scopes.items() if scope == 'current-reference'},
                             {'linear-basis', 'tone-curves', 'tone-saturation', 'color-tone-weights',
                              'color-drivers', 'guard-boundary', 'guard-energy'})
            self.assertEqual(scopes['color-hue-concentration'], 'historical')
            self.assertEqual(scopes['lut-input-grid'], 'historical')
            source_manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(source_manifest, provenance['data_provenance'])
            self.assertTrue(source_manifest['inputs'])
            for name, expected in source_manifest['outputs'].items():
                self.assertIn(name, names)
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected)
            for item in archive.infolist():
                with self.subTest(source=item.filename):
                    member = PurePosixPath(item.filename)
                    self.assertFalse(member.is_absolute())
                    self.assertNotIn('..', member.parts)
                    self.assertEqual(item.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual(item.external_attr >> 16, 0o100644)
                    self.assertNotIn(member.suffix, {'.aux', '.log', '.fls', '.xdv', '.dvi', '.fmt', '.pdf', '.svg'})
                    self.assertFalse({'cache', 'config', 'formats', '__pycache__'} & set(member.parts))
                    if member.suffix in {'.json', '.tex', '.dat', '.md', '.txt', '.csv'}:
                        text = archive.read(item.filename).decode('utf-8')
                        for transient in ('buck-out/', '/home/', '/tmp/', '/nix/store/', 'pg-book-latex-'):
                            self.assertNotIn(transient, text)
                        if member.suffix == '.tex':
                            for table in re.findall(r'\{(tables/[^}]+)\}', text):
                                self.assertIn(table, names)

    def test_math_and_shared_runtime_assets(self):
        structure = (self.output / 'technical/en/theory/structure.html').read_text()
        self.assertIn('data-tex="j=H/100=M/100"', structure)
        self.assertIn('data-tex="J_{\\mathrm{HK}}"', html.unescape(structure))
        self.assertNotIn('![Published relationship', structure)
        self.assertIn('data-tex=', (self.output / 'technical/en/theory/hk-guard.html').read_text())
        self.assertFalse((self.output / 'vendor').exists())
        self.assertFalse(any(self.output.rglob('*.woff*')))
        katex = json.loads((self.output / 'downloads/provenance/katex.json').read_text())
        self.assertEqual(katex['katex'], assignment(self.resources / 'tool-pins.bzl', 'DOC_TOOLS')['katex'])
        for kind in ('stylesheet', 'script'):
            self.assertIn(katex['katex'][kind]['url'], structure)
            self.assertIn(katex['integrity'][kind], structure)
        for route in ('manual/en', 'manual/zh-Hans', 'technical/en'):
            for shared in ('assets', 'downloads', 'vendor'):
                self.assertFalse((self.output / route / shared).exists())
        fonts = json.loads((self.output / 'downloads/provenance/fonts.json').read_text())
        self.assertEqual(fonts['fonts'], assignment(self.resources / 'tool-pins.bzl', 'DOC_FONTS'))
        for font in fonts['fonts'].values():
            self.assertEqual(sha(self.output / 'downloads/licenses' / font['license']['out']),
                             font['license']['sha256'])
        icons = json.loads((self.output / 'downloads/provenance/favicon.json').read_text())
        for name, expected in icons['outputs'].items():
            self.assertEqual(sha(self.output / name), expected, name)
        for name, source in icons['sources'].items():
            self.assertEqual(sha(self.book / 'src/assets/icons' / name), source['sha256'])
        webmanifest = json.loads((self.output / 'site.webmanifest').read_text())
        self.assertTrue(any(icon['purpose'] == 'maskable' for icon in webmanifest['icons']))

    def test_published_downloads_and_media(self):
        downloads = self.output / 'downloads'
        extension = 'perceptual_grade-v1.23.2-20261101.zip'
        self.assertFalse((downloads / 'perceptual_grade.zip').exists())
        with zipfile.ZipFile(downloads / extension) as archive:
            metadata = tomllib.loads(archive.read('blender_manifest.toml').decode())
            self.assertEqual(metadata['version'], '1.23.2')
        for name in (extension, 'Perceptual-Grade.dctl',
                     'Perceptual-Grade-zh-HANS.dctl'):
            self.assertEqual(sha(downloads / name),
                             self.manifest['files']['src/downloads/' + name])
        tutorial = assignment(self.resources / 'tool-pins.bzl', 'TUTORIAL_ASSETS')['colorchecker2014']
        self.assertEqual(sha(downloads / 'ACEScg_ColorChecker2014.exr'), tutorial['sha256'])
        demos = json.loads((self.output / 'assets/demos/manifest.json').read_text())
        spec = json.loads((self.docs / 'data/demos.json').read_text())
        self.assertEqual([demo['name'] for demo in demos['demos']],
                         [demo['name'] for demo in spec['demos']])
        self.assertEqual(demos['color']['input_power_exponent'], 1.961)
        for name, expected in demos['outputs'].items():
            self.assertEqual(sha(self.output / 'assets/demos' / name.removeprefix('images/')), expected)
        intro = json.loads((downloads / 'provenance/intro-video.json').read_text())
        self.assertEqual(intro['source']['sha256'], sha(self.docs / 'media/intro/match-three-images.mp4'))
        for name, expected in intro['outputs'].items():
            self.assertEqual(sha(self.output / 'assets/intro' / name), expected)
        introduction = (self.output / 'manual/en/index.html').read_text()
        self.assertEqual([ref for ref in site.Page(introduction).iframes
                          if urlsplit(ref).netloc], [])
        self.assertIn(('../../assets/intro/match-three-images.webp', True),
                      site.Page(introduction).refs)
        self.assertLess(introduction.index('assets/intro/match-three-images.webp'),
                        introduction.index('class="download-grid"'))

    def test_markdown_reports_retain_original_bytes_and_download_links(self):
        for name in ('gpu-solver-exploration.md', 'gpu-baking-validation.md'):
            report = self.output / 'downloads' / name
            self.assertEqual(report.read_bytes(),
                             (self.book / 'src/downloads' / name).read_bytes())
            self.assertFalse(report.with_suffix('.html').exists())
            for relative in ('development/testing.html', 'print.html'):
                page = self.output / 'technical/en' / relative
                with self.subTest(report=name, page=page.relative_to(self.output)):
                    references = [ref for ref, _ in site.Page(page.read_text()).refs]
                    links = [ref for ref in references
                             if Path(urlsplit(ref).path).name == name]
                    self.assertTrue(links, 'Missing Markdown report download link')
                    for reference in links:
                        self.assertEqual(site.local_target(self.output, page, reference, False), report)
                    self.assertFalse(any(Path(urlsplit(ref).path).name == report.with_suffix('.html').name
                                         for ref in references))

    def test_archive_bytes_and_fixed_metadata(self):
        expected = inventory(self.output)
        archive_path = self.resources / 'site.zip'
        with zipfile.ZipFile(archive_path) as archive:
            self.assertEqual(archive.namelist(), sorted(expected))
            for required in ('index.html', 'manual/index.html', 'manual/en/index.html',
                             'manual/zh-Hans/index.html', 'technical/en/index.html'):
                self.assertIn(required, archive.namelist())
            self.assertFalse(any(name.startswith('technical/zh-Hans/')
                                 for name in archive.namelist()))
            self.assertIsNone(archive.testzip())
            for item in archive.infolist():
                with self.subTest(path=item.filename):
                    self.assertEqual(item.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual(item.external_attr >> 16, 0o100644)
                    self.assertEqual(hashlib.sha256(archive.read(item.filename)).hexdigest(),
                                     expected[item.filename])
        checksums = json.loads((self.resources / 'SHA256.json').read_text())
        self.assertEqual(checksums['perceptual-grade-site.zip'],
                         {'sha256': sha(archive_path), 'bytes': archive_path.stat().st_size})
        with tempfile.TemporaryDirectory() as temporary:
            rebuilt = Path(temporary) / 'site.zip'
            zip_utils.write_zip(rebuilt, zip_utils.files(self.output))
            self.assertEqual(sha(rebuilt), sha(archive_path))


class LanguageEditionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.book = Path(temporary.name)
        self.english = ['README.md', 'guide/common.md', 'reference/license.md']
        self.chinese = list(self.english)
        for directory, chapters in (('src', self.english), ('zh-Hans', self.chinese)):
            for name in chapters:
                path = self.book / directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('# Fixture chapter\n')
            self.write_summary(directory, chapters)

    def write_summary(self, directory, chapters):
        (self.book / directory / 'SUMMARY.md').write_text(
            '# Summary\n\n' + ''.join(f'- [Chapter]({name})\n' for name in chapters)
        )

    def test_every_manual_chapter_has_a_matching_translation(self):
        english, localized = site.check_language_chapters(self.book)
        self.assertEqual(english, self.english)
        self.assertEqual(localized, {'en': self.english, 'zh-Hans': self.chinese})

    def test_missing_translation_fails(self):
        (self.book / 'zh-Hans/guide/common.md').unlink()
        self.write_summary('zh-Hans', ['README.md', 'reference/license.md'])
        with self.assertRaisesRegex(ValueError, 'Simplified Chinese manual chapter paths must match'):
            site.check_language_chapters(self.book)

    def test_reordered_translation_fails(self):
        self.write_summary('zh-Hans', ['README.md', 'reference/license.md', 'guide/common.md'])
        with self.assertRaisesRegex(ValueError, 'Simplified Chinese manual chapter paths must match'):
            site.check_language_chapters(self.book)

    def test_unlisted_chinese_copy_is_rejected(self):
        copy = self.book / 'zh-Hans/development/next-policies.md'
        copy.parent.mkdir(parents=True)
        copy.write_text('# Accidental English fallback\n')
        with self.assertRaisesRegex(ValueError, 'unlisted chapters'):
            site.check_language_chapters(self.book)

    def test_manual_language_menu_links_to_each_matching_chapter(self):
        labels = {
            language: {'name': name, 'choose': 'Choose language', 'ui': {}}
            for language, name in (('en', 'English'), ('zh-Hans', '简体中文'))
        }
        markup = '<html><head></head><body><div class="right-buttons"></div></body></html>'
        for page in (Path('guide/common.html'), Path('reference/license.html')):
            with self.subTest(page=page):
                rendered = languages.language_chrome(markup, page, 'en', labels)
                self.assertIn('data-book-language="en"', rendered)
                self.assertNotIn('aria-disabled="true"', rendered)
                self.assertIn('data-book-language="zh-Hans"', rendered)
                self.assertIn('hreflang="zh-Hans"', rendered)
                self.assertIn('../../zh-Hans/' + page.as_posix(), rendered)


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.docs = self.root / 'docs'
        self.assets = self.root / 'assets'
        self.historical = self.root / 'historical'
        source = self.docs / 'book/src'
        source.mkdir(parents=True)
        (self.docs / 'book/book.toml').write_text(
            '[book]\ntitle = "Handbook"\nlanguage = "en"\nsrc = "src"\n')
        self.chapters = {
            'src': ['README.md', 'guide/install.md', 'reference/license.md'],
            'src/report': ['README.md', 'theory/model.md',
                           'development/architecture.md', 'reference/license.md'],
            'zh-Hans': ['README.md', 'guide/install.md', 'reference/license.md'],
        }
        texts = {
            'src/README.md': '# User Manual\n',
            'src/guide/install.md': '# Install\n',
            'src/reference/license.md': '# License\n',
            'src/report/README.md': '# Technical Report\n',
            'src/theory/model.md': '# Model\n',
            'src/development/architecture.md': '# Architecture\n',
            'zh-Hans/README.md': '# 用户手册\n',
            'zh-Hans/guide/install.md': '# 安装\n',
            'zh-Hans/reference/license.md': '# 许可\n',
        }
        for name, value in texts.items():
            path = self.docs / 'book' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        (source / 'downloads/measurement.md').parent.mkdir(parents=True)
        (source / 'downloads/measurement.md').write_text('# Downloadable measurement\n')
        for summary_root, chapters in self.chapters.items():
            target = self.docs / 'book' / summary_root / 'SUMMARY.md'
            target.parent.mkdir(parents=True, exist_ok=True)
            self.write_summary(target, chapters)
        self.asset = self.assets / 'src/assets/figure.png'
        self.asset.parent.mkdir(parents=True)
        self.asset.write_bytes(b'generated figure')
        self.download = self.historical / 'src/downloads/release.zip'
        self.download.parent.mkdir(parents=True)
        self.download.write_bytes(b'preserved release bytes')
        self.manifest = self.root / 'historical-manifest.json'
        self.spec = {'schema': 1, 'files': inventory(self.historical)}
        self.write_manifest()
        self.output = self.root / 'assembled'

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.spec))

    @staticmethod
    def write_summary(path, chapters):
        path.write_text('# Summary\n\n' + ''.join(f'- [Chapter]({name})\n' for name in chapters))

    def build(self, assets=None):
        return assemble.assemble(self.docs, [self.assets] if assets is None else assets,
                                 self.historical, self.manifest, self.output)

    def test_chapter_edits_and_new_generator_results_are_build_inputs(self):
        chapter = self.docs / 'book/src/README.md'
        chapter.write_text('# Edited chapter\n')
        self.asset.write_bytes(b'regenerated figure')
        assembled = self.build()
        manual, report = assembled / 'user-manual', assembled / 'technical-report'
        self.assertEqual((manual / 'src/README.md').read_bytes(), chapter.read_bytes())
        self.assertEqual((report / 'src/README.md').read_bytes(),
                         (self.docs / 'book/src/report/README.md').read_bytes())
        self.assertEqual((report / 'src/theory/model.md').read_bytes(),
                         (self.docs / 'book/src/theory/model.md').read_bytes())
        self.assertFalse((manual / 'src/theory').exists())
        self.assertFalse((report / 'src/guide').exists())
        for edition in (manual, report):
            self.assertEqual((edition / 'src/assets/figure.png').read_bytes(), self.asset.read_bytes())
            self.assertEqual((edition / 'src/downloads/release.zip').read_bytes(), self.download.read_bytes())
            self.assertEqual((edition / 'src/downloads/measurement.md').read_text(),
                             '# Downloadable measurement\n')
        self.assertFalse((report / 'zh-Hans').exists())

    def test_read_only_sources_produce_writable_private_assembly(self):
        before = {name: inventory(root) for name, root in
                  [('docs', self.docs), ('assets', self.assets), ('historical', self.historical)]}
        for root in (self.docs, self.assets, self.historical):
            for path in root.rglob('*'):
                if path.is_file():
                    path.chmod(0o444)
        directories = [path for path in self.docs.rglob('*') if path.is_dir()]
        for path in reversed(directories):
            self.addCleanup(path.chmod, 0o755)
            path.chmod(0o555)
        assembled = self.build()
        for path in (assembled / 'user-manual/book.toml',
                     assembled / 'user-manual/src/README.md',
                     assembled / 'user-manual/zh-Hans/README.md',
                     assembled / 'technical-report/src/README.md',
                     assembled / 'technical-report/src/assets/figure.png',
                     assembled / 'technical-report/src/downloads/release.zip'):
            self.assertTrue(path.stat().st_mode & 0o200, str(path))
            path.write_bytes(path.read_bytes() + b'\nprivate staging edit')
        for name, root in [('docs', self.docs), ('assets', self.assets), ('historical', self.historical)]:
            self.assertEqual(inventory(root), before[name])

    def test_missing_historical_download_fails_before_assembly(self):
        self.download.unlink()
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_tampered_historical_download_fails_before_assembly(self):
        self.download.write_bytes(b'changed bytes')
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_unlisted_historical_download_fails(self):
        (self.download.parent / 'unlisted.zip').write_bytes(b'unregistered')
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_generated_file_cannot_replace_authored_chapter(self):
        (self.assets / 'src/README.md').write_text('# Replacement chapter\n')
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_generated_file_cannot_introduce_an_unlisted_chapter(self):
        path = self.assets / 'src/guide/generated.md'
        path.parent.mkdir(parents=True)
        path.write_text('# Generated chapter\n')
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_historical_file_cannot_replace_generated_file(self):
        conflict = self.historical / 'src/assets/figure.png'
        conflict.parent.mkdir(parents=True)
        conflict.write_bytes(self.asset.read_bytes())
        self.spec['files'] = inventory(self.historical)
        self.write_manifest()
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_two_generators_cannot_own_the_same_path(self):
        with self.assertRaises(ValueError):
            self.build([self.assets, self.assets])
        self.assertFalse(self.output.exists())

    def test_file_cannot_shadow_an_authored_directory(self):
        (self.assets / 'src').rename(self.assets / 'old-src')
        (self.assets / 'src').write_bytes(b'conflict')
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_invalid_historical_path_fails(self):
        self.spec['files']['../outside'] = '0' * 64
        self.write_manifest()
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_chinese_technical_chapter_is_rejected(self):
        unexpected = self.docs / 'book/zh-Hans/theory/model.md'
        unexpected.parent.mkdir(parents=True)
        unexpected.write_text('# 不应出现的技术章节\n')
        with self.assertRaisesRegex(ValueError, 'Simplified Chinese SUMMARY must cover exactly'):
            self.build()
        self.assertFalse(self.output.exists())


class RenderingFailureTests(unittest.TestCase):
    def test_cross_book_routing_preserves_fragments_and_queries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            report = root / 'technical/en/theory/model.html'
            report.parent.mkdir(parents=True)
            report.write_text('<a href="../guide/common.html#manual-detail">Manual</a>')
            for language in ('en', 'zh-Hans'):
                chapter = root / 'manual' / language / 'guide/common.html'
                chapter.parent.mkdir(parents=True)
                chapter.write_text(
                    '<a href="../theory/model.html?x=1&amp;y=2#technical-detail">Report</a>'
                    '<a href="common.html#manual-detail">Same book</a>'
                    '<a href="https://example.org/theory/model.html">External</a>')
            self.assertEqual(site.repair_cross_book_links(root), 3)
            for language in ('en', 'zh-Hans'):
                chapter = root / 'manual' / language / 'guide/common.html'
                self.assertIn(
                    'href="../../../technical/en/theory/model.html?x=1&amp;y=2#technical-detail"',
                    chapter.read_text())
                self.assertIn('href="common.html#manual-detail"', chapter.read_text())
                self.assertIn('href="https://example.org/theory/model.html"', chapter.read_text())
            self.assertIn('href="../../../manual/en/guide/common.html#manual-detail"', report.read_text())
            self.assertEqual(site.repair_cross_book_links(root), 0)

    def test_unresolved_cross_book_destination_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            chapter = root / 'manual/en/guide/common.html'
            chapter.parent.mkdir(parents=True)
            chapter.write_text('<a href="../theory/absent.html">Missing report chapter</a>')
            with self.assertRaisesRegex(ValueError, 'Unresolved cross-book link'):
                site.repair_cross_book_links(root)

    def test_markdown_download_repair_preserves_other_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            book, output = root / 'book', root / 'site'
            source = book / 'src/downloads/nested/report.md'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'# Original downloadable report\n')
            chapter = output / 'technical/en/development/testing.html'
            chapter.parent.mkdir(parents=True)
            chapter.write_text(
                '<a href="../../../downloads/nested/report.html?x=1&amp;y=2#section">Report</a>'
                '<a href="https://example.org/downloads/nested/report.html">External</a>'
                '<a href="../../../downloads/existing.html">Existing HTML</a>'
                '<a href="missing.html">Unrelated missing HTML</a>')
            (chapter.parent / 'missing.md').write_text('# Not a download\n')
            printable = output / 'technical/en/print.html'
            printable.write_text('<a href="../../downloads/nested/report.html">Report</a>')
            site.copy_markdown_downloads(book, output)
            self.assertEqual((output / 'downloads/nested/report.md').read_bytes(), source.read_bytes())
            for suffix in ('.html', '.md'):
                (output / ('downloads/existing' + suffix)).write_text('Existing download')
            self.assertEqual(site.restore_markdown_download_links(output), 2)
            self.assertIn('href="../../../downloads/nested/report.md?x=1&amp;y=2#section"', chapter.read_text())
            self.assertIn('href="../../downloads/nested/report.md"', printable.read_text())
            for unchanged in ('https://example.org/downloads/nested/report.html',
                              '../../../downloads/existing.html', 'missing.html'):
                self.assertIn('href="' + unchanged + '"', chapter.read_text())
            self.assertEqual(site.restore_markdown_download_links(output), 0)

    def test_math_preserves_code_literals_and_paragraph_separation(self):
        sample = '$$\nH^2=J_A^2+66C\n$$\n\n![Chart](chart.png)\n\n## Next\n'
        converted = site.prepare_math(sample)
        self.assertIn('</div>\n\n', converted)
        self.assertIn('![Chart](chart.png)', converted)
        literal = '`\\(H\\)` and ``\\(C\\)``\n\n```text\n\\(a\\)\n```\n'
        self.assertEqual(site.prepare_math(literal), literal)

    def test_publication_rejects_broken_fragment_and_external_script(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / 'downloads/provenance').mkdir(parents=True)
            (root / 'downloads/provenance/fonts.json').write_text('{"fonts": {}}')
            (root / 'downloads/provenance/katex.json').write_text(json.dumps({
                'katex': {'version': '0.19.0',
                          'stylesheet': {'url': 'https://cdn.jsdelivr.net/npm/katex@0.19.0/dist/katex.min.css'},
                          'script': {'url': 'https://cdn.jsdelivr.net/npm/katex@0.19.0/dist/katex.min.js'}},
                'integrity': {'stylesheet': 'sha384-fixture', 'script': 'sha384-fixture'},
            }))
            (root / '.nojekyll').write_bytes(b'')
            page = root / 'index.html'
            for markup, message in (
                ('<a href="#absent">Broken fragment</a>', 'Broken fragment'),
                ('<script src="https://example.com/math.js"></script>', 'External runtime resource'),
                ('<img src="missing.png">', 'Broken local link'),
                ('<script defer src="https://cdn.jsdelivr.net/npm/katex@0.19.0/dist/katex.min.js" '
                 'crossorigin="anonymous"></script>', 'Invalid CDN KaTeX integration'),
                ('<script defer src="https://cdn.jsdelivr.net/npm/katex@0.19.0/dist/katex.min.js" '
                 'crossorigin="anonymous" integrity="sha384-wrong"></script>', 'Invalid CDN KaTeX integration'),
                ('<script defer src="https://cdn.jsdelivr.net/npm/katex@latest/dist/katex.min.js" '
                 'crossorigin="anonymous" integrity="sha384-fixture"></script>', 'External runtime resource'),
                ('<img src="https://cdn.jsdelivr.net/npm/katex@0.19.0/dist/katex.min.js" '
                 'crossorigin="anonymous" integrity="sha384-fixture">', 'Invalid CDN KaTeX integration'),
                ('<script async src="https://cdn.jsdelivr.net/npm/katex@0.19.0/dist/katex.min.js" '
                 'crossorigin="anonymous" integrity="sha384-fixture"></script>', 'Invalid CDN KaTeX integration'),
                ('<img srcset="https://cdn.jsdelivr.net/npm/katex@0.19.0/dist/katex.min.js 2x">',
                 'Invalid CDN KaTeX integration'),
                ('<span data-tex="x^2">x^2</span>', 'Missing CDN KaTeX'),
            ):
                with self.subTest(markup=markup):
                    page.write_text(markup)
                    with self.assertRaisesRegex(ValueError, message):
                        site.validate_site(root)


if __name__ == '__main__':
    unittest.main()

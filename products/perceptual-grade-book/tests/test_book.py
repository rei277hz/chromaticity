"""Check source-driven 1.23.2 assembly and the actual Buck-built publication."""
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
import zipfile

from pg_book_build import assemble, languages, parts, site


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(root):
    return {path.relative_to(root).as_posix(): sha(path)
            for path in sorted(root.rglob('*')) if path.is_file()}


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
        cls.assets = [cls.resources / name for name in ('generated-assets', 'cdn-assets', 'data-downloads')]
        cls.output = (cls.resources / 'site').resolve()
        cls.book = cls.docs / 'book'
        cls.manifest_path = cls.resources / 'historical-manifest.json'
        cls.manifest = json.loads(cls.manifest_path.read_text())
        cls.publication = json.loads((cls.output / 'site-manifest.json').read_text())
        cls.chapters = site.check_chapters(cls.book)

    def test_authored_and_generated_inputs_are_assembled(self):
        self.assertEqual(self.manifest['schema'], 1)
        self.assertEqual(inventory(self.historical), self.manifest['files'])
        expected = inventory(self.book)
        for root in [*self.assets, self.historical]:
            incoming = inventory(root)
            self.assertFalse(expected.keys() & incoming.keys())
            expected.update(incoming)
        self.assertEqual(inventory(self.inputs), expected)
        self.assertFalse((self.inputs / 'src/vendor').exists())

    def test_both_license_pages_explain_source_and_release_terms(self):
        repository = 'https://github.com/rei277hz/chromaticity/blob/main/'
        for language, directory in (('en', 'src'), ('zh-Hans', 'zh-Hans')):
            source = (self.book / directory / 'reference/license.md').read_text()
            rendered = html.unescape(
                (self.output / language / 'reference/license.html').read_text())
            for stage, text in (('source', source), ('rendered', rendered)):
                with self.subTest(language=language, stage=stage):
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
        for name in ('numerical-figures', 'photographic-figures', 'host-screenshots'):
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
        self.assertGreater(checks['html_pages'], len(self.chapters) * 2)
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

    def test_both_language_editions_and_navigation(self):
        self.assertEqual(site.check_chapters(self.book, 'zh-Hans'), self.chapters)
        self.assertEqual(self.publication['languages'],
                         {'en': self.chapters, 'zh-Hans': self.chapters})
        for language in ('en', 'zh-Hans'):
            edition = self.output / language
            for chapter in self.chapters:
                with self.subTest(language=language, chapter=chapter):
                    page = 'index.html' if chapter == 'README.md' else chapter.removesuffix('.md') + '.html'
                    text = (edition / page).read_text()
                    self.assertIn(f'<html lang="{language}"', text)
                    self.assertIn('class="language-picker"', text)
                    self.assertIn('data-book-language="en"', text)
                    self.assertIn('data-book-language="zh-Hans"', text)
                    self.assertNotIn('class="nav-wrapper"', text)
            search = next(edition.glob('searchindex-*.js')).read_text()
            for page in ('guide/linear.html', 'theory/linear.html', 'reference/credits.html'):
                self.assertIn(page, search)
            toc = (edition / 'toc.html').read_text()
            numbers = dict(re.findall(
                r'<a href="([^"]+)"[^>]*><strong aria-hidden="true">([^<]+)</strong>', toc))
            self.assertEqual(numbers['guide/install.html'], '1.')
            self.assertEqual(numbers['theory/linear.html'], '1.')
            self.assertEqual(numbers['guide/linear.html'], '2.1.')
            self.assertNotRegex(toc, r'href="[^"]*#')
        chinese_search = next((self.output / 'zh-Hans').glob('searcher-*.js')).read_text()
        self.assertIn('window.PGChineseSearch.create', chinese_search)
        self.assertTrue((self.output / 'chinese-search.js').is_file())
        self.assertIn('data-language-entry="true"', (self.output / 'index.html').read_text())

    def test_math_and_shared_runtime_assets(self):
        structure = (self.output / 'en/theory/structure.html').read_text()
        self.assertIn('data-tex="j=H/100"', structure)
        self.assertIn('data-tex="J_{\\mathrm{HK}}"', html.unescape(structure))
        self.assertNotIn('![Published relationship', structure)
        self.assertIn('data-tex=', (self.output / 'en/theory/hk-guard.html').read_text())
        self.assertFalse((self.output / 'vendor').exists())
        self.assertFalse(any(self.output.rglob('*.woff*')))
        katex = json.loads((self.output / 'downloads/provenance/katex.json').read_text())
        self.assertEqual(katex['katex'], assignment(self.resources / 'tool-pins.bzl', 'DOC_TOOLS')['katex'])
        for kind in ('stylesheet', 'script'):
            self.assertIn(katex['katex'][kind]['url'], structure)
            self.assertIn(katex['integrity'][kind], structure)
        for language in ('en', 'zh-Hans'):
            for shared in ('assets', 'downloads', 'vendor'):
                self.assertFalse((self.output / language / shared).exists())
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
        introduction = (self.output / 'en/index.html').read_text()
        self.assertEqual([ref for ref in site.Page(introduction).iframes
                          if urlsplit(ref).netloc], [])
        self.assertIn(('../assets/intro/match-three-images.webp', True),
                      site.Page(introduction).refs)
        self.assertLess(introduction.index('assets/intro/match-three-images.webp'),
                        introduction.index('class="download-grid"'))

    def test_markdown_reports_retain_original_bytes_and_download_links(self):
        for name in ('gpu-solver-exploration.md', 'gpu-baking-validation.md'):
            report = self.output / 'downloads' / name
            self.assertEqual(report.read_bytes(),
                             (self.book / 'src/downloads' / name).read_bytes())
            self.assertFalse(report.with_suffix('.html').exists())
            for language in ('en', 'zh-Hans'):
                for relative in ('development/testing.html', 'print.html'):
                    page = self.output / language / relative
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


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.docs = self.root / 'docs'
        self.assets = self.root / 'assets'
        self.historical = self.root / 'historical'
        (self.docs / 'book/src').mkdir(parents=True)
        (self.docs / 'book/book.toml').write_text('[book]\ntitle = "Handbook"\n')
        (self.docs / 'book/src/README.md').write_text('# Chapter\n')
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

    def build(self, assets=None):
        return assemble.assemble(self.docs, [self.assets] if assets is None else assets,
                                 self.historical, self.manifest, self.output)

    def test_chapter_edits_and_new_generator_results_are_build_inputs(self):
        chapter = self.docs / 'book/src/README.md'
        chapter.write_text('# Edited chapter\n')
        self.asset.write_bytes(b'regenerated figure')
        assembled = self.build()
        self.assertEqual((assembled / 'src/README.md').read_bytes(), chapter.read_bytes())
        self.assertEqual((assembled / 'src/assets/figure.png').read_bytes(), self.asset.read_bytes())
        self.assertEqual((assembled / 'src/downloads/release.zip').read_bytes(), self.download.read_bytes())

    def test_read_only_sources_produce_writable_private_assembly(self):
        before = {name: inventory(root) for name, root in
                  [('docs', self.docs), ('assets', self.assets), ('historical', self.historical)]}
        for root in (self.docs, self.assets, self.historical):
            for path in root.rglob('*'):
                if path.is_file():
                    path.chmod(0o444)
        directories = [self.docs / 'book', self.docs / 'book/src']
        for path in reversed(directories):
            self.addCleanup(path.chmod, 0o755)
            path.chmod(0o555)
        assembled = self.build()
        for path in (assembled / 'book.toml', assembled / 'src/README.md',
                     assembled / 'src/assets/figure.png', assembled / 'src/downloads/release.zip'):
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


class RenderingFailureTests(unittest.TestCase):
    def test_markdown_download_repair_preserves_other_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            book, output = root / 'book', root / 'site'
            source = book / 'src/downloads/nested/report.md'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'# Original downloadable report\n')
            chapter = output / 'en/guide/testing.html'
            chapter.parent.mkdir(parents=True)
            chapter.write_text(
                '<a href="../../downloads/nested/report.html?x=1&amp;y=2#section">Report</a>'
                '<a href="https://example.org/downloads/nested/report.html">External</a>'
                '<a href="../../downloads/existing.html">Existing HTML</a>'
                '<a href="missing.html">Unrelated missing HTML</a>')
            (chapter.parent / 'missing.md').write_text('# Not a download\n')
            printable = output / 'en/print.html'
            printable.write_text('<a href="../downloads/nested/report.html">Report</a>')
            site.copy_markdown_downloads(book, output)
            self.assertEqual((output / 'downloads/nested/report.md').read_bytes(), source.read_bytes())
            for suffix in ('.html', '.md'):
                (output / ('downloads/existing' + suffix)).write_text('Existing download')
            self.assertEqual(site.restore_markdown_download_links(output), 2)
            self.assertIn('href="../../downloads/nested/report.md?x=1&amp;y=2#section"', chapter.read_text())
            self.assertIn('href="../downloads/nested/report.md"', printable.read_text())
            for unchanged in ('https://example.org/downloads/nested/report.html',
                              '../../downloads/existing.html', 'missing.html'):
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

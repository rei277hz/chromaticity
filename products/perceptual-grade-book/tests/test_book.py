"""Check the preserved 1.23.2 inputs and the actual Buck-built publication."""
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
        cls.snapshot = cls.resources / 'snapshot'
        cls.output = (cls.resources / 'site').resolve()
        cls.book = cls.docs / 'book'
        cls.manifest_path = cls.resources / 'import-manifest.json'
        cls.manifest = json.loads(cls.manifest_path.read_text())
        cls.publication = json.loads((cls.output / 'site-manifest.json').read_text())
        cls.chapters = site.check_chapters(cls.book)

    def test_original_sources_and_snapshot_match_import(self):
        self.assertEqual(self.manifest['schema'], 1)
        self.assertEqual(self.manifest['version'], '1.23.2')
        self.assertEqual(len(self.manifest['docs']), 208)
        self.assertTrue(self.manifest['snapshot'])
        self.assertTrue(self.manifest['provenance'])
        self.assertEqual(inventory(self.docs), self.manifest['docs'])
        self.assertEqual(inventory(self.snapshot), self.manifest['snapshot'])
        self.assertEqual(assemble.verify_inputs(
            self.docs, self.snapshot, self.manifest_path), self.manifest)

    def test_document_updates_preserve_original_document_provenance(self):
        originals = {
            'book/book.toml':
                '08b48aa782e00ae0ede01ca39064050e17f598dd1215aa2d3b25a01333c6b464',
            'book/src/README.md':
                '38d64086e8ee3209d95ce28952bda5b3c9e888077333a5ff3450d141821e760f',
            'book/zh-Hans/README.md':
                '680007f7c808a498c19f36dc5b0082dadcc18e24496df8dcb59b8a9a57958b97',
            'book/src/development/contributing.md':
                '4d1cdd2740b9dfb6f5f32691b01fc65097a063827737f9a4733e920be9ea213e',
            'book/zh-Hans/development/contributing.md':
                '37a5766311208973a33426c8b61d7a0519b6e6f54a084681ac640fd2fcb93096',
            'book/src/guide/install.md':
                '57035faff23c8200e775990ff16aafaec8441fd10a0d38e9824f68b5dc0b2437',
            'book/zh-Hans/guide/install.md':
                '7dbd9798cc6cd3fdd7779cb2d66d3b92195b95ae26cf934156f7a4c5a387de4f',
            'book/src/development/documentation.md':
                '770ee6a85b0011880734c26ffae8b8971f588fbb8e84ba037a0c7b58cdc7e8dd',
            'book/src/development/publishing.md':
                '0f626ccc705e7b3a31699ff4910f0e652041a70ffa01e842741ff2a5ac7939da',
            'book/src/reference/license.md':
                'dcb0d18e45b129d8f7bdb6597cc2c51ebfd1c1ca3de45984eda22f1ceffbaddb',
            'book/zh-Hans/reference/license.md':
                'cce2164b9991113f14bc9f326f0e814b3317bf07e07d87d64119b9edf515398a',
            'book/src/reference/credits.md':
                '659f5bbd7ee029d8ddf3936355367793c340fb6b617180c784f0383633b0a889',
        }
        adaptations = self.manifest['provenance']['docs_adaptations']
        self.assertEqual(set(adaptations), set(originals))
        for name, original in originals.items():
            with self.subTest(document=name):
                self.assertEqual(adaptations[name]['original_sha256'], original)
                self.assertTrue(adaptations[name]['change'])
                self.assertNotEqual(original, sha(self.docs / name))
                self.assertEqual(self.manifest['docs'][name], sha(self.docs / name))

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

    def test_supplemental_provenance_uses_verified_release_relative_inputs(self):
        provenance = self.manifest['provenance']
        expected = dict(provenance['legacy_inputs_sha256'])
        expected.update({'docs/' + name: digest
                         for name, digest in self.manifest['docs'].items()})
        metadata = [
            'src/downloads/provenance/' + name + '.json'
            for name in ('numerical-figures', 'photographic-figures', 'host-screenshots')
        ]
        self.assertEqual(set(provenance['metadata_adaptations']), set(metadata))
        for filename in metadata:
            document = self.snapshot / filename
            adaptation = provenance['metadata_adaptations'][filename]
            self.assertRegex(adaptation['original_sha256'], r'^[0-9a-f]{64}$')
            self.assertNotEqual(adaptation['original_sha256'], sha(document))
            inputs = json.loads(document.read_text())['inputs']
            self.assertTrue(inputs)
            for name, digest in inputs.items():
                with self.subTest(metadata=filename, input=name):
                    path = PurePosixPath(name)
                    self.assertFalse(path.is_absolute())
                    self.assertNotIn('..', path.parts)
                    self.assertNotIn('buck-out', path.parts)
                    self.assertEqual(path.as_posix(), name)
                    self.assertIn(name, expected)
                    self.assertEqual(digest, expected[name])

    def test_rendered_links_and_manifest(self):
        checks = site.validate_site(self.output)
        self.assertEqual(checks['cdn_font_files'], 2)
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
        expected_inputs = {
            name.removeprefix('book/'): digest
            for name, digest in self.manifest['docs'].items() if name.startswith('book/')
        }
        expected_inputs.update(self.manifest['snapshot'])
        self.assertEqual(self.publication['input_files'], expected_inputs)

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
        self.assertTrue((self.output / 'vendor/katex/katex.min.js').is_file())
        self.assertTrue((self.output / 'vendor/katex/fonts').is_dir())
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
                     'Perceptual-Grade-zh-HANS.dctl', 'ACEScg_ColorChecker2014.exr'):
            self.assertEqual(sha(downloads / name),
                             self.manifest['snapshot']['src/downloads/' + name])
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


class ImportFailureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.docs, self.snapshot = self.root / 'docs', self.root / 'snapshot'
        (self.docs / 'book/src').mkdir(parents=True)
        (self.docs / 'book/book.toml').write_text('[book]\ntitle = "Preserved"\n')
        (self.docs / 'book/src/README.md').write_text('# Original chapter\n')
        self.asset = self.snapshot / 'src/assets/figure.png'
        self.asset.parent.mkdir(parents=True)
        self.asset.write_bytes(b'preserved supplemental bytes')
        self.manifest = self.root / 'import-manifest.json'
        self.spec = {'schema': 1, 'version': '1.23.2',
                     'docs': inventory(self.docs), 'snapshot': inventory(self.snapshot)}
        self.write_manifest()
        self.output = self.root / 'assembled'

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.spec))

    def test_read_only_sources_produce_writable_private_assembly(self):
        directories = [self.docs / 'book', self.docs / 'book/src']
        for path in reversed(directories):
            self.addCleanup(path.chmod, 0o755)
        for path in self.docs.rglob('*'):
            if path.is_file():
                path.chmod(0o444)
        self.asset.chmod(0o444)
        for path in directories:
            path.chmod(0o555)
        assembled = assemble.assemble(self.docs, self.snapshot, self.manifest, self.output)
        for path in (assembled / 'book.toml', assembled / 'src/README.md',
                     assembled / 'src/assets/figure.png'):
            self.assertTrue(path.stat().st_mode & 0o200, str(path))
            path.write_bytes(path.read_bytes() + b'\nprivate staging edit')
        self.assertEqual(inventory(self.docs), self.spec['docs'])
        self.assertEqual(inventory(self.snapshot), self.spec['snapshot'])

    def test_missing_supplement_fails_before_assembly(self):
        self.asset.unlink()
        with self.assertRaisesRegex(ValueError, 'snapshot inventory mismatch.*missing='):
            assemble.assemble(self.docs, self.snapshot, self.manifest, self.output)
        self.assertFalse(self.output.exists())

    def test_tampered_supplement_fails_before_assembly(self):
        self.asset.write_bytes(b'changed bytes')
        with self.assertRaisesRegex(ValueError, 'snapshot inventory mismatch.*changed='):
            assemble.assemble(self.docs, self.snapshot, self.manifest, self.output)
        self.assertFalse(self.output.exists())

    def test_unlisted_supplement_fails(self):
        (self.asset.parent / 'unlisted.png').write_bytes(b'unregistered')
        with self.assertRaisesRegex(ValueError, 'snapshot inventory mismatch.*extra='):
            assemble.assemble(self.docs, self.snapshot, self.manifest, self.output)
        self.assertFalse(self.output.exists())

    def test_supplement_cannot_replace_original_even_with_matching_hash(self):
        conflict = self.snapshot / 'src/README.md'
        conflict.write_text('# Replacement chapter\n')
        self.spec['snapshot'] = inventory(self.snapshot)
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'Snapshot conflicts with original'):
            assemble.assemble(self.docs, self.snapshot, self.manifest, self.output)
        self.assertFalse(self.output.exists())

    def test_changed_original_is_rejected(self):
        (self.docs / 'book/src/README.md').write_text('# Edited original chapter\n')
        with self.assertRaisesRegex(ValueError, 'docs inventory mismatch.*changed='):
            assemble.assemble(self.docs, self.snapshot, self.manifest, self.output)
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
            (root / '.nojekyll').write_bytes(b'')
            page = root / 'index.html'
            for markup, message in (
                ('<a href="#absent">Broken fragment</a>', 'Broken fragment'),
                ('<script src="https://example.com/math.js"></script>', 'External runtime resource'),
                ('<img src="missing.png">', 'Broken local link'),
            ):
                with self.subTest(markup=markup):
                    page.write_text(markup)
                    with self.assertRaisesRegex(ValueError, message):
                        site.validate_site(root)


if __name__ == '__main__':
    unittest.main()

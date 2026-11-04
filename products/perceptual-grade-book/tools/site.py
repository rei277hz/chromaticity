"""Build the handbook from declared inputs, with pinned CDN fonts and equations."""
import argparse
import ast
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit, urlunsplit
from xml.etree import ElementTree
from pg_book_build.languages import LANGUAGES, language_chrome, share_assets, landing, enable_chinese_search


INTRO_VIDEO_EMBED = ('https://player.bilibili.com/player.html?isOutside=true'
                    '&aid=116325414341794&bvid=BV17H9GBNEfJ&cid=37150327813&p=1')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    return {p.relative_to(root).as_posix(): digest(p)
            for p in sorted(root.rglob('*')) if p.is_file()}


def tool_pins(path, rust_versions):
    for item in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(item, ast.Assign) and any(isinstance(n, ast.Name) and n.id == 'DOC_TOOLS' for n in item.targets):
            pins = ast.literal_eval(item.value)
            # The central Rust lock owns the executable used by this build.
            versions = json.loads(rust_versions.read_text(encoding='utf-8'))
            pins['mdbook'] = dict(versions['crates']['mdbook'], source='crates.io',
                                 buck_target='root//third_party/rust:mdbook-mdbook')
            return pins
    raise ValueError('DOC_TOOLS is missing from the documentation lock')


def prepare_math(text):
    """Renderable TeX markup, preserving fenced code and literal examples."""
    parts = re.split(r'(^```[^\n]*\n.*?^```\s*$)', text, flags=re.M | re.S)
    for i in range(0, len(parts), 2):
        value = re.sub(r'^\$\$[ \t]*\n(.*?)\n\$\$[ \t]*$',
                       lambda m: '\n<div class="grade-equation" data-tex="' + html.escape(m[1].strip(), quote=True) + '"></div>\n',
                       parts[i], flags=re.M | re.S)
        value = re.sub(r'(?P<ticks>`+).*?(?P=ticks)(?!`)|\\\((?P<tex>.*?)\\\)',
                       lambda m: m[0] if m['ticks'] else
                       '<span data-tex="' + html.escape(m['tex'], quote=True) + '"></span>', value)
        parts[i] = value
    return ''.join(parts)


def polish_pages(site, language="en", labels=None):
    """Adapt mdBook navigation to the ACES-inspired reading layout."""
    favicon = site / 'favicon.ico'
    if not favicon.is_file():
        raise ValueError('Missing required generated favicon.ico')
    icon_version = digest(favicon)[:12]
    touch_icon = site / 'apple-touch-icon.png'
    if not touch_icon.is_file():
        raise ValueError('Missing required generated apple-touch-icon.png')
    fonts = json.loads((site/'downloads/provenance/fonts.json').read_text())['fonts']
    body_font = fonts['pontano-sans']['normal']['url']
    origin = urlsplit(body_font)
    font_head = ('<link rel="preconnect" href="' + origin.scheme + '://' + origin.netloc + '" crossorigin>\n'
                 '<link rel="preload" as="font" type="font/woff2" href="' + body_font + '" crossorigin>\n')
    for path in site.rglob('*.html'):
        text = path.read_text(encoding='utf-8')
        prefix = '../' * len(path.relative_to(site).parent.parts)
        # The declared PNG-to-ICO action owns the favicon. Remove mdBook's
        # built-in icon links, including its hashed default artwork.
        text = re.sub(r'<link\b[^>]*\brel="(?:shortcut )?icon"[^>]*>\s*', '', text)
        icon_link = ('<link rel="icon" type="image/x-icon" sizes="16x16 32x32 48x48 64x64 256x256" '
                     'href="' + prefix + 'favicon.ico?v=' + icon_version + '">\n')
        touch_link = ('<link rel="apple-touch-icon" sizes="180x180" href="' + prefix
                      + 'apple-touch-icon.png?v=' + digest(touch_icon)[:12] + '">\n')
        # Remove mdBook's unused local Open Sans / Source Code Pro loader.
        text = re.sub(r'<link\b[^>]*href="[^"]*fonts/fonts(?:-[^"/]+)?\.css"[^>]*>\s*', '', text)
        text = text.replace('</head>', font_head + icon_link + touch_link + '<link rel="manifest" href="' + prefix + 'site.webmanifest">\n</head>', 1)
        text = re.sub(r'<nav\b[^>]*class="nav-(?:wide-)?wrapper"[^>]*>.*?</nav>', '', text, flags=re.S)
        text = re.sub(r'<p>[^<]*(?:<kbd>[^<]*</kbd>[^<]*)+navigate between chapters</p>', '', text)
        for theme in ('rust', 'coal', 'ayu', 'default_theme'):
            text = re.sub(r'<li role="none"><button[^>]*id="mdbook-theme-' + theme + r'"[^>]*>.*?</button></li>', '', text)
        for theme, label in [('light', 'Light'), ('navy', 'Dark')]:
            text = re.sub(r'(id="mdbook-theme-' + theme + r'"[^>]*>)[^<]+', r'\g<1>' + label, text)
        auto = '<li role="none"><button role="menuitem" class="grade-auto" id="grade-theme-auto">Auto</button></li>'
        text = re.sub(r'(<ul[^>]*id="mdbook-theme-list"[^>]*>)', r'\1' + auto, text)
        # A compound screenshot stays legible through its full-size image link.
        text = re.sub(r'(<img src="([^\"]*(?:figures|screenshots|illustrations)[^\"]*\.(?:png|svg))"[^>]*>)', r'<a class="figure-link" href="\2">\1</a>', text)
        # mdBook rebases src for print.html, but not custom data attributes.
        # The still lives beside its animation in every output context.
        def align_still(match):
            tag = match[0]
            image = re.search(r'\bsrc="([^"]+)"', tag)
            still = re.search(r'\bdata-still="([^"]+)"', tag)
            if not image or not still:
                return tag
            target = str(Path(image[1]).parent / Path(still[1]).name)
            return tag[:still.start(1)] + target + tag[still.end(1):]
        text = re.sub(r'<img\b[^>]*>', align_still, text)
        # Reserve each media box before lazy loading. Otherwise a decoded image
        # above a paragraph can move the text while the reader is selecting it.
        def reserve_image(match):
            tag = match[0]
            source = re.search(r'\bsrc="([^"]+)"', tag)
            if not source:
                return tag
            target = path.parent / unquote(source[1])
            if target.suffix not in ('.png', '.webp', '.svg'):
                return tag
            with target.open('rb') as stream:
                header = stream.read(30)
            if target.suffix == '.svg':
                svg = ElementTree.parse(target).getroot()
                width, height = int(svg.attrib['width']), int(svg.attrib['height'])
            elif header.startswith(b'\x89PNG\r\n\x1a\n'):
                width, height = struct.unpack('>II', header[16:24])
            elif header[:4] == b'RIFF' and header[8:16] == b'WEBPVP8X':
                width = 1 + int.from_bytes(header[24:27], 'little')
                height = 1 + int.from_bytes(header[27:30], 'little')
            else:
                raise ValueError(f'Unsupported or corrupt book image: {target}')
            if width < 1 or height < 1:
                raise ValueError(f'Invalid book image dimensions: {target}')
            tag = re.sub(r'\s(?:width|height)="[^"]*"', '', tag)
            return tag[:-1] + f' width="{width}" height="{height}">'
        text = re.sub(r'<img\b[^>]*>', reserve_image, text)
        text = re.sub(r'(<h1 class="menu-title">)(.*?)(</h1>)',
                      lambda m: m[1] + '<a href="' + prefix + 'index.html"><img class="brand-icon" src="' + prefix + 'assets/icons/perceptual-grade-32-transparent.png" srcset="' + prefix + 'assets/icons/perceptual-grade-64-transparent.png 2x" alt="" width="32" height="32"><span>' + m[2] + '</span></a>' + m[3], text)
        # Move the toolbar outside the translated mobile reading column so
        # opening the sidebar cannot shift a supposedly full-width header.
        bar = re.search(r'(<div id="mdbook-menu-bar"[^>]*>.*?</div>\s*</div>)(?=\s*<div id="mdbook-search-wrapper")', text, re.S)
        if bar:
            text = text[:bar.start()] + text[bar.end():]
            text = text.replace('<nav id="mdbook-sidebar"', bar[1] + '\n<nav id="mdbook-sidebar"', 1)
        if labels is not None:
            text = language_chrome(text, path.relative_to(site), language, labels)
        main = re.search(r'<main>(.*?)</main>', text, re.S)
        if main:
            words = labels[language] if labels is not None else {'footer':'Perceptual Grade handbook', 'credits':'Credits', 'license':'License'}
            footer = ('<footer class="book-footer">' + html.escape(words['footer'])
                      + ' <a href="' + prefix + 'reference/credits.html">' + html.escape(words['credits'])
                      + '</a> <a href="' + prefix + 'reference/license.html">' + html.escape(words['license']) + '</a></footer>')
            text = text.replace('</main>', footer + '</main>', 1)
        path.write_text(text, encoding='utf-8')
    for pattern in ('favicon*.png', 'favicon*.svg'):
        for unused in site.glob(pattern):
            unused.unlink()
    if (site/'fonts').exists():
        shutil.rmtree(site/'fonts')


def check_chapters(book, language="en"):
    source = book / ("src" if language == "en" else language)
    summary = (source / 'SUMMARY.md').read_text(encoding='utf-8')
    paths = re.findall(r'\]\(([^)#]+\.md)\)', summary)
    if len(paths) != len(set(paths)):
        raise ValueError('Duplicate chapter paths in SUMMARY.md')
    chapters = {p.relative_to(source).as_posix() for p in source.rglob('*.md')
                if p.relative_to(source).parts[0] not in ('vendor', 'assets', 'downloads') and p.name != 'SUMMARY.md'}
    missing = set(paths) - chapters
    orphaned = chapters - set(paths)
    if missing or orphaned:
        raise ValueError(f'Missing chapters: {sorted(missing)}; unlisted chapters: {sorted(orphaned)}')
    return paths


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.refs = []
        self.iframes = []
        self.font_hints = []
        self.runtime_tags = []
        self.has_math = False
        self.feed(text)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        self.runtime_tags.append((tag, attrs))
        if 'data-tex' in attrs:
            self.has_math = True
        if tag == 'a' and 'name' in attrs:
            self.ids.add(attrs['name'])
        if tag == 'link' and attrs.get('rel') in ('preconnect', 'preload'):
            self.font_hints.append(attrs)
        elif 'href' in attrs:
            self.refs.append((attrs['href'], tag != 'a'))
        if 'src' in attrs:
            if tag == 'iframe':
                self.iframes.append(attrs['src'])
            else:
                self.refs.append((attrs['src'], True))
        if 'srcset' in attrs:
            self.refs.extend((item.strip().split()[0], True) for item in attrs['srcset'].split(','))
        if tag == 'video' and 'poster' in attrs:
            self.refs.append((attrs['poster'], True))
        if tag == 'img' and 'data-still' in attrs:
            self.refs.append((attrs['data-still'], True))


def local_target(root, origin, reference, runtime, allowed_resources=()):
    url = urlsplit(reference)
    if url.scheme or url.netloc:
        if runtime and url.scheme not in ('data', 'mailto') and reference not in allowed_resources:
            raise ValueError(f'External runtime resource in {origin.relative_to(root)}: {reference}')
        return None
    if not url.path:
        return origin
    if url.path.startswith('/'):
        raise ValueError(f'Nonportable root-relative URL in {origin.relative_to(root)}: {reference}')
    target = (origin.parent / unquote(url.path)).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f'Link escapes the deployed site: {reference}')
    if target.is_dir():
        target = target / 'index.html'
    if not target.is_file():
        raise ValueError(f'Broken local link in {origin.relative_to(root)}: {reference}')
    return target


def validate_site(directory):
    root = directory.resolve()
    fonts_file = root/'downloads/provenance/fonts.json'
    font_manifest = json.loads(fonts_file.read_text())
    allowed_fonts = {spec['normal']['url'] for spec in font_manifest['fonts'].values()}
    for name, spec in font_manifest['fonts'].items():
        if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', spec['version']):
            raise ValueError('Expected an exact CDN font version: ' + name)
        expected = (f'https://cdn.jsdelivr.net/npm/@fontsource-variable/{name}@{spec["version"]}'
                    f'/files/{name}-latin-wght-normal.woff2')
        if spec['normal']['url'] != expected:
            raise ValueError('Unexpected CDN font URL: ' + spec['normal']['url'])
    math_manifest = json.loads((root/'downloads/provenance/katex.json').read_text())
    katex = math_manifest['katex']
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', katex['version']):
        raise ValueError('Expected an exact CDN KaTeX version')
    math_resources = {}
    for key, filename in (('stylesheet', 'katex.min.css'), ('script', 'katex.min.js')):
        expected = f'https://cdn.jsdelivr.net/npm/katex@{katex["version"]}/dist/{filename}'
        if katex[key]['url'] != expected:
            raise ValueError('Unexpected CDN KaTeX URL: ' + katex[key]['url'])
        math_resources[expected] = key
    font_origins = {urlsplit(url).scheme+'://'+urlsplit(url).netloc for url in allowed_fonts}
    pages = {p: Page(p.read_text(encoding='utf-8')) for p in root.rglob('*.html')}
    if root / 'index.html' not in pages:
        raise ValueError('Site has no index.html')
    checked = 0
    for path, page in pages.items():
        integrated_math = set()
        for tag, attrs in page.runtime_tags:
            references = [(key, attrs[key]) for key in ('src', 'poster', 'data-still') if key in attrs]
            if tag != 'a' and 'href' in attrs:
                references.append(('href', attrs['href']))
            references.extend(('srcset', item.strip().split()[0])
                              for item in attrs.get('srcset', '').split(',') if item.strip())
            for attribute, reference in references:
                if reference not in math_resources:
                    continue
                kind = math_resources[reference]
                valid = ((kind == 'script' and tag == 'script' and attribute == 'src'
                          and 'defer' in attrs and 'async' not in attrs
                          and attrs.get('type') in (None, 'text/javascript', 'application/javascript'))
                         or (kind == 'stylesheet' and tag == 'link' and attribute == 'href'
                             and attrs.get('rel') == 'stylesheet'
                             and attrs.get('type') in (None, 'text/css')))
                if (not valid or attrs.get('crossorigin') != 'anonymous'
                        or attrs.get('integrity') != math_manifest['integrity'][kind]):
                    raise ValueError(f'Invalid CDN KaTeX integration in {path.relative_to(root)}: {reference}')
                integrated_math.add(reference)
        if page.has_math and integrated_math != set(math_resources):
            raise ValueError(f'Missing CDN KaTeX integration in {path.relative_to(root)}')
        for hint in page.font_hints:
            valid = (hint['rel'] == 'preconnect' and hint.get('href') in font_origins or
                     hint['rel'] == 'preload' and hint.get('as') == 'font' and hint.get('href') in allowed_fonts)
            if not valid or 'crossorigin' not in hint:
                raise ValueError(f'Unexpected external resource hint in {path.name}: {hint}')
            checked += 1
        # Only this specific video may use an external iframe. The permission
        # does not apply to scripts, other runtime assets or different videos.
        checked += page.iframes.count(INTRO_VIDEO_EMBED)
        references = page.refs + [(ref, True) for ref in page.iframes if ref != INTRO_VIDEO_EMBED]
        for ref, runtime in references:
            target = local_target(root, path, ref, runtime, math_resources)
            fragment = unquote(urlsplit(ref).fragment)
            if target in pages and fragment and fragment not in pages[target].ids:
                raise ValueError(f'Broken fragment in {path.relative_to(root)}: {ref}')
            checked += 1
    for path in root.rglob('*.css'):
        for match in re.finditer(r'url\(\s*[\"\']?([^\"\')\s]+)', path.read_text(encoding='utf-8')):
            local_target(root, path, match.group(1), True, allowed_fonts)
            checked += 1
    for path in root.rglob('*.webmanifest'):
        webmanifest = json.loads(path.read_text())
        for icon in webmanifest['icons']:
            local_target(root, path, icon['src'], True)
            checked += 1
        for key in ('start_url', 'scope'):
            local_target(root, path, webmanifest[key], False)
            checked += 1
    if not (root / '.nojekyll').is_file():
        raise ValueError('Missing .nojekyll for GitHub Pages deployment')
    return {'html_pages': len(pages), 'local_references_checked': checked,
            'cdn_font_files': len(allowed_fonts), 'cdn_katex_files': len(math_resources)}


def copy_markdown_downloads(book, directory):
    """Preserve downloadable reports that mdBook omits from its rendered output."""
    source = Path(book) / 'src' / 'downloads'
    destination = Path(directory) / 'downloads'
    for report in source.rglob('*.md'):
        output = destination / report.relative_to(source)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(report, output)


def restore_markdown_download_links(directory):
    """Keep nonchapter Markdown reports downloadable after mdBook rewrites links."""
    root = Path(directory).resolve()
    downloads = root / 'downloads'
    repaired = 0
    for page in root.rglob('*.html'):
        def restore(match):
            nonlocal repaired
            reference = html.unescape(match[2])
            url = urlsplit(reference)
            if url.scheme or url.netloc or not url.path.endswith('.html'):
                return match[0]
            target = (page.parent / unquote(url.path)).resolve()
            if (not target.is_relative_to(downloads) or target.exists()
                    or not target.with_suffix('.md').is_file()):
                return match[0]
            repaired += 1
            replacement = urlunsplit(('', '', url.path[:-5] + '.md', url.query, url.fragment))
            return match[1] + html.escape(replacement, quote=True) + match[3]
        original = page.read_text(encoding='utf-8')
        updated = re.sub(r'(<a\b[^>]*\bhref=")([^"]*)(")', restore, original, flags=re.I)
        if updated != original:
            page.write_text(updated, encoding='utf-8')
    return repaired


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--book', type=Path, required=True)
    parser.add_argument('--mdbook', type=Path, required=True)
    parser.add_argument('--pins', type=Path, required=True)
    parser.add_argument('--rust-versions', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    pins = tool_pins(args.pins, args.rust_versions)
    executable = args.mdbook.resolve()
    version = subprocess.run([str(executable), '--version'], check=True, capture_output=True, text=True).stdout.strip()
    if version != 'mdbook v' + pins['mdbook']['version']:
        raise ValueError(f'Expected pinned mdBook, received {version}')
    chapters = check_chapters(args.book)
    localized = {language: check_chapters(args.book, language) for language in LANGUAGES}
    if any(paths != chapters for paths in localized.values()):
        raise ValueError('Language chapter paths must match exactly; missing pages never fall back to English.')
    labels = json.loads((args.book/'locales.json').read_text(encoding='utf-8'))
    if set(labels) != set(LANGUAGES):
        raise ValueError('Every supported language requires its explicit UI catalog.')
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    site = output / 'site'
    if site.exists():
        shutil.rmtree(site)
    site.mkdir()
    inputs = inventory(args.book)
    numbering = Path(__file__).with_name('parts.py')
    if not numbering.is_file():
        raise ValueError('Missing required part-numbering preprocessor: parts.py')
    for language in LANGUAGES:
        with tempfile.TemporaryDirectory(prefix='pg-book-', dir=output) as temporary:
            book = Path(temporary) / 'book'
            # CAS inputs may be read-only. The renderer edits this private copy;
            # copy bytes without preserving input file permissions.
            shutil.copytree(args.book, book, copy_function=shutil.copyfile)
            for directory in [book, *(path for path in book.rglob('*') if path.is_dir())]:
                directory.chmod(directory.stat().st_mode | 0o700)
            if language != 'en':
                for name in [*chapters, 'SUMMARY.md']:
                    shutil.copyfile(args.book/language/name, book/'src'/name)
            config = (book/'book.toml').read_text(encoding='utf-8')
            config = re.sub(r'^language = "[^"]+"', 'language = '+json.dumps(language), config, flags=re.M)
            if language != 'en':
                config = re.sub(r'^description = ".*"', 'description = "Perceptual Grade"', config, flags=re.M)
            command = shlex.join([sys.executable, str(numbering.resolve())])
            config += ('\n[preprocessor.part-numbers]\ncommand = ' + json.dumps(command)
                       + '\nafter = ["links", "index"]\n')
            (book/'book.toml').write_text(config, encoding='utf-8')
            for name in chapters:
                path = book/'src'/name
                path.write_text(prepare_math(path.read_text(encoding='utf-8')), encoding='utf-8')
            edition = site/language
            rendered = subprocess.run([str(executable), 'build', str(book), '--dest-dir', str(edition)],
                                      check=True, capture_output=True, text=True)
            messages = rendered.stdout + rendered.stderr
            if re.search(r'^\s*ERROR\b', messages, re.MULTILINE):
                raise ValueError('mdBook reported an error:\n' + messages)
        error_page = edition/'404.html'
        if error_page.exists():
            text = error_page.read_text(encoding='utf-8')
            text = re.sub(r'((?:href|src)=\")/(?!/)', r'\1', text)
            error_page.write_text(text,encoding='utf-8')
        if language == 'zh-Hans':enable_chinese_search(edition)
        polish_pages(edition, language, labels)
        share_assets(site, language)
    landing(site, args.book/'theme/language.js', labels)
    (site/'.nojekyll').write_bytes(b'')
    copy_markdown_downloads(args.book, site)
    restore_markdown_download_links(site)
    checks = validate_site(site)
    manifest = {
        'schema': 1,
        'build_target': 'root//products/perceptual-grade-book:site',
        'invocation': 'buck2' if os.environ.get('PG_BUCK_ACTION') == '1' else 'authoring-preview',
        'tools': pins,
        'tool_definitions_sha256': digest(args.pins),
        'rust_dependencies': json.loads(args.rust_versions.read_text(encoding='utf-8')),
        'rust_dependencies_sha256': digest(args.rust_versions),
        'builder_sha256': digest(Path(__file__)),
        'part_numbering_sha256': digest(Path(__file__).with_name('parts.py')),
        'input_files': inputs,
        'chapters': chapters,
        'languages': localized,
        'language_builder_sha256': digest(Path(__file__).with_name('languages.py')),
        'validation': checks,
        'site_files': inventory(site),
    }
    data = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + '\n'
    (output / 'site-manifest.json').write_text(data, encoding='utf-8')
    (site / 'site-manifest.json').write_text(data, encoding='utf-8')
    print(f'mdBook {pins["mdbook"]["version"]}: {len(chapters)} chapters, {checks["local_references_checked"]} resource/link checks')


if __name__ == '__main__':
    main()

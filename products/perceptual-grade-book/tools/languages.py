"""Assemble two explicit mdBook editions with shared assets and remembered routing."""
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit, urlunsplit

LANGUAGES = ('en', 'zh-Hans')
SHARED = ('assets', 'downloads', 'favicon.ico', 'apple-touch-icon.png',
          'android-192.png', 'android-512.png', 'android-512-maskable.png', 'site.webmanifest')
GLOBE = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c5 5 5 13 0 18-5-5-5-13 0-18Z"/></svg>'


def language_chrome(text, page, language, labels):
    """Keep language navigation independent of mdBook's section navigation."""
    prefix = '../' * (len(page.parent.parts) + 1)
    controls = labels[language]
    choices=[]
    alternates=[]
    for target in LANGUAGES:
        href=prefix+target+'/'+page.as_posix()
        current=' aria-current="page"' if target==language else ''
        choices.append(f'<a href="{href}" data-book-language="{target}" lang="{target}" hreflang="{target}"{current}>{html.escape(labels[target]["name"])}</a>')
        alternates.append(f'<link rel="alternate" hreflang="{target}" href="{href}">')
    widget=(f'<details class="language-picker"><summary title="{html.escape(controls["choose"])}" aria-label="{html.escape(controls["choose"])}" aria-expanded="false">'
            +GLOBE+'</summary><div class="language-options">'+''.join(choices)+'</div></details>')
    text=text.replace('<div class="right-buttons">','<div class="right-buttons">'+widget,1)
    if language == 'zh-Hans':
        text=text.replace('</head>', f'<script src="{prefix}chinese-search.js"></script>\n</head>',1)
    text=text.replace('</head>','\n'.join(alternates)+f'\n<script src="{prefix}language.js" defer></script>\n</head>',1)
    for before,after in controls['ui'].items():
        text=text.replace(before,after)
    return text


def share_assets(site, language):
    """Move shared output once, checking that the other edition produced the same bytes."""
    edition=site/language
    for name in SHARED:
        source, destination=edition/name,site/name
        if not source.exists():
            raise ValueError('Missing shared book resource: '+name)
        if destination.exists():
            if source.is_dir():
                left={p.relative_to(source).as_posix():p.read_bytes() for p in source.rglob('*') if p.is_file()}
                right={p.relative_to(destination).as_posix():p.read_bytes() for p in destination.rglob('*') if p.is_file()}
                if left!=right:raise ValueError('Language editions disagree on shared resource: '+name)
                shutil.rmtree(source)
            else:
                if source.read_bytes()!=destination.read_bytes():raise ValueError('Language editions disagree on shared resource: '+name)
                source.unlink()
        else:
            shutil.move(str(source),str(destination))
    def rebase(path, value):
        url=urlsplit(value)
        if url.scheme or url.netloc or not url.path:return value
        target=(path.parent/url.path).resolve()
        if not target.is_relative_to(edition.resolve()):return value
        relative=target.relative_to(edition.resolve())
        if not relative.parts or relative.parts[0] not in SHARED:return value
        new=os.path.relpath(site/relative,path.parent)
        return urlunsplit(('', '', new, url.query, url.fragment))
    for path in edition.rglob('*.html'):
        text=path.read_text(encoding='utf-8')
        text=re.sub(r'\b(href|src|data-still)="([^"]*)"',lambda m:m[1]+'="'+rebase(path,m[2])+'"',text)
        text=re.sub(r'\bsrcset="([^"]*)"',lambda m:'srcset="'+', '.join(rebase(path,v.strip().split()[0])+' '+v.strip().split()[1] for v in m[1].split(','))+'"',text)
        path.write_text(text,encoding='utf-8')


def enable_chinese_search(edition):
    scripts=list(edition.glob('searcher-*.js'))
    if len(scripts)!=1:raise ValueError('Expected one mdBook search client.')
    script=scripts[0];text=script.read_text(encoding='utf-8')
    old='searchindex = elasticlunr.Index.load(config.index);'
    if text.count(old)!=1:raise ValueError('Pinned mdBook search integration changed.')
    text=text.replace(old,'searchindex = window.PGChineseSearch.create(config.index.documentStore.docs);')
    name='searcher-'+hashlib.sha256(text.encode()).hexdigest()[:12]+'.js'
    (edition/name).write_text(text,encoding='utf-8')
    for path in edition.rglob('*.html'):
        path.write_text(path.read_text(encoding='utf-8').replace(script.name,name),encoding='utf-8')
    script.unlink()


def landing(site, script, labels):
    if not script.is_file():raise ValueError('Missing language-selection script.')
    shutil.copyfile(script,site/'language.js')
    search_script=script.with_name('chinese-search.js')
    if not search_script.is_file():raise ValueError('Missing Chinese search implementation.')
    shutil.copyfile(search_script,site/'chinese-search.js')
    choices=' '.join(f'<a href="{lang}/index.html" lang="{lang}" data-book-language="{lang}">{html.escape(labels[lang]["name"])}</a>' for lang in LANGUAGES)
    text='''<!doctype html>
<html lang="en" data-language-entry="true"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Introduction - Perceptual Grade</title>
<link rel="icon" href="favicon.ico" type="image/x-icon" sizes="16x16 32x32 48x48 64x64 256x256">
<link rel="apple-touch-icon" href="apple-touch-icon.png" sizes="180x180">
<link rel="manifest" href="site.webmanifest">
<script src="language.js"></script>
<style>body{font:18px/1.6 system-ui,sans-serif;max-width:42rem;margin:12vh auto;padding:24px}a{color:inherit;margin-right:24px}</style>
</head><body><h1>Perceptual Grade</h1><nav aria-label="Language">'''+choices+'</nav></body></html>\n'
    (site/'index.html').write_text(text,encoding='utf-8')

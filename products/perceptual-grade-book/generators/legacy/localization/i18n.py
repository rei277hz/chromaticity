"""Standalone GNU gettext catalogs with semantic, locale-independent IDs.

JSON sources are compiled with Babel at build time. Runtime uses only the
Python standard library. Native RNA strings are resolved through en.json at
registration because Blender stores display strings rather than message IDs.
"""
from pathlib import Path
import gettext
import json
import unicodedata

CONTEXT = 'Perceptual Grade'
_DIRECTORY = Path(__file__).parent.parent / 'locales'
CATALOGS = {path.stem: json.loads(path.read_text(encoding='utf-8'))
            for path in sorted(_DIRECTORY.glob('*.json'))}
if 'en' not in CATALOGS:
    raise RuntimeError('Perceptual Grade requires an English catalog')
for _locale, _messages in CATALOGS.items():
    if _messages.keys() != CATALOGS['en'].keys():
        raise RuntimeError('Perceptual Grade locale ID sets differ: ' + _locale)
# Blender renamed Simplified Chinese; both host identifiers resolve one catalog.
_ALIASES = {'zh_CN': 'zh_HANS'}
_TRANSLATORS = {}
for _locale in CATALOGS:
    with (_DIRECTORY / _locale / 'LC_MESSAGES' / 'perceptual_grade.mo').open('rb') as _file:
        _translator = gettext.GNUTranslations(_file)
    if any(_translator.gettext(key) != value for key, value in CATALOGS[_locale].items()):
        raise RuntimeError('Perceptual Grade compiled locale is out of date: ' + _locale)
    _TRANSLATORS[_locale] = _translator
_registered = False


def _language(preference):
    try:
        import bpy
    except ModuleNotFoundError:
        return 'en'
    view = bpy.context.preferences.view
    if not getattr(view, preference):
        return 'en'
    locale = view.language
    if locale == 'DEFAULT':
        locale = bpy.app.translations.locale
    locale = _ALIASES.get(locale, locale)
    if locale in CATALOGS:
        return locale
    base = locale.split('_', 1)[0]
    return base if base in CATALOGS else 'en'


def language():
    return _language('use_translate_interface')


def tooltip_language():
    return _language('use_translate_tooltips')


def tr(message_id, *, locale=None, **values):
    if message_id not in CATALOGS['en']:
        raise KeyError('Unknown Perceptual Grade message ID: ' + str(message_id))
    result = _TRANSLATORS[locale or language()].gettext(message_id)
    return result.format(**values) if values else result


def native(message_id, **values):
    """Resolve the host's RNA source string from the English catalog."""
    return tr(message_id, locale='en', **values)


def tip(message_id, **values):
    """Dynamic operator/socket tooltip, following the tooltip preference."""
    return tr(message_id, locale=tooltip_language(), **values)


class Message(str):
    """A deferred message ID for draw code that also accepts raw numbers."""
    def __new__(cls, message_id):
        if message_id not in CATALOGS['en']:
            raise KeyError('Unknown Perceptual Grade message ID: ' + message_id)
        return super().__new__(cls, message_id)


M = Message


def display(value):
    return tr(value) if isinstance(value, Message) else str(value)


def wrap(message, columns):
    """Wrap the resolved text, counting CJK glyphs as two cells."""
    message = display(message)
    rows = []; row = ''; width = 0
    for token in message.split(' '):
        pieces = list(token) if any(unicodedata.east_asian_width(c) in 'WF' for c in token) else [token]
        for i, piece in enumerate(pieces):
            gap = ' ' if row and i == 0 and len(pieces) == 1 else ''
            size = sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in gap + piece)
            if row and width + size > columns:
                rows.append(row); row = ''; width = 0; size -= len(gap); gap = ''
            row += gap + piece; width += size
    if row:
        rows.append(row)
    return rows


def host_messages(locale):
    """Blender bridge: custom-context names, default-context tooltips.

    Blender performs tooltip lookup using its default context, independently
    of a property's translation_context. General short labels stay scoped.
    """
    messages = {}
    for message_id in CATALOGS['en']:
        source = native(message_id)
        translated = tr(message_id, locale=locale)
        messages[(CONTEXT, source)] = translated
        if message_id.startswith('tooltip.') or message_id in {
            'product.name', 'socket.reference', 'socket.color', 'socket.alpha', 'socket.image'
        }:
            messages[('*', source)] = translated
    return messages


def register():
    global _registered
    import bpy
    unregister()
    messages = {locale: host_messages(locale) for locale in CATALOGS if locale != 'en'}
    messages.update({alias: messages[locale] for alias, locale in _ALIASES.items() if locale in messages})
    bpy.app.translations.register(__name__, messages)
    _registered = True


def unregister():
    global _registered
    import bpy
    if _registered:
        bpy.app.translations.unregister(__name__)
        _registered = False


def update_node_title(node):
    """Follow language changes while keeping a user's custom node label."""
    from ..graph import stacks
    label = tr('node.stack.title' if stacks.is_stack(node) else 'node.grade.title')
    if node.label == node.get('_pg_auto_label') and node.label != label:
        node.label = label
        node['_pg_auto_label'] = label


def marker(kind, value):
    return tr(f'marker.{kind}.{value}')

"""Semantic JSON catalogs and Blender's interface translation bridge."""

from pathlib import Path
import gettext
import json
from string import Formatter


CONTEXT = "Perceptual Grade"
_DIRECTORY = Path(__file__).parent / "locales"
_ALIASES = {"zh_CN": "zh_HANS"}


def _fields(text):
    return {(name, spec, conversion)
            for _, name, spec, conversion in Formatter().parse(text)
            if name is not None}


def _load_catalogs(directory):
    catalogs = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(Path(directory).glob("*.json"))
    }
    if "en" not in catalogs:
        raise RuntimeError("Perceptual Grade requires an English locale catalog")
    english = catalogs["en"]
    for locale, entries in catalogs.items():
        if entries.keys() != english.keys():
            raise RuntimeError(f"Perceptual Grade locale IDs differ: {locale}")
        for message_id, value in entries.items():
            if not isinstance(value, str) or not value.strip():
                raise RuntimeError(f"Invalid {locale} translation: {message_id}")
            if _fields(english[message_id]) != _fields(value):
                raise RuntimeError(f"Placeholder mismatch for {locale}:{message_id}")
    return catalogs


CATALOGS = _load_catalogs(_DIRECTORY)
_TRANSLATORS = {}
for _locale, _messages in CATALOGS.items():
    with (_DIRECTORY / _locale / "LC_MESSAGES" / "perceptual_grade.mo").open("rb") as _file:
        _translator = gettext.GNUTranslations(_file)
    if any(_translator.gettext(message_id) != value
           for message_id, value in _messages.items()):
        raise RuntimeError(f"Perceptual Grade compiled locale is stale: {_locale}")
    _TRANSLATORS[_locale] = _translator
_registered = False


def resolve_locale(locale):
    """Resolve Blender locale identifiers to a shipped catalog."""
    locale = _ALIASES.get(locale, locale)
    if locale in CATALOGS:
        return locale
    base = locale.split("_", 1)[0]
    return base if base in CATALOGS else "en"


def language_for(view, translations, preference):
    """Follow Blender's interface and tooltip preferences independently."""
    if not getattr(view, preference, False):
        return "en"
    locale = view.language
    if locale == "DEFAULT":
        locale = translations.locale
    return resolve_locale(locale)


def language():
    import bpy
    return language_for(
        bpy.context.preferences.view,
        bpy.app.translations,
        "use_translate_interface",
    )


def tooltip_language():
    import bpy
    return language_for(
        bpy.context.preferences.view,
        bpy.app.translations,
        "use_translate_tooltips",
    )


def tr(message_id, *, locale=None, **values):
    try:
        if message_id not in CATALOGS["en"]:
            raise KeyError(message_id)
        message = _TRANSLATORS[resolve_locale(locale or language())].gettext(message_id)
    except KeyError as error:
        raise KeyError("Unknown Perceptual Grade message ID: " + str(message_id)) from error
    return message.format(**values) if values else message


def native(message_id, **values):
    """Resolve an English source string for Blender's native translation API."""
    return tr(message_id, locale="en", **values)


def host_messages(locale):
    """Map semantic IDs to Blender's concrete source strings and contexts."""
    locale = resolve_locale(locale)
    messages = {}
    for message_id, source in CATALOGS["en"].items():
        translated = _TRANSLATORS[locale].gettext(message_id)
        context_key = (CONTEXT, source)
        if context_key in messages and messages[context_key] != translated:
            raise RuntimeError(f"Conflicting Blender translation source: {source}")
        messages[context_key] = translated
        if (message_id.startswith(("tooltip.", "description."))
                or message_id.endswith("_description")
                or message_id in {
                    "panel.category", "socket.color", "socket.alpha",
                }):
            wildcard_key = ("*", source)
            if wildcard_key in messages and messages[wildcard_key] != translated:
                raise RuntimeError(f"Conflicting Blender tooltip source: {source}")
            messages[wildcard_key] = translated
    return messages


def register():
    global _registered
    import bpy
    unregister()
    messages = {
        locale: host_messages(locale)
        for locale in CATALOGS
        if locale != "en"
    }
    messages.update({
        alias: messages[locale]
        for alias, locale in _ALIASES.items()
        if locale in messages
    })
    bpy.app.translations.register(__name__, messages)
    _registered = True


def unregister():
    global _registered
    if not _registered:
        return
    import bpy
    bpy.app.translations.unregister(__name__)
    _registered = False

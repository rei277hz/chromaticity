"""Identities and buffer formats shared by Bake snapshot capture and hydration."""

from pathlib import Path


def library_path(host, library):
    if library is None:
        return None
    absolute = host.path.abspath(
        library.filepath, library=getattr(library, "parent", None),
    )
    return str(Path(absolute).expanduser().resolve(strict=False))


def datablock_key(host, value):
    return str(value.name), library_path(host, getattr(value, "library", None))


def resolve_datablocks(host, collection, keys):
    keys = set(keys)
    if not keys:
        return {}
    names = {name for name, _library in keys}
    matches = {}
    for value in collection:
        if value.name in names:
            key = datablock_key(host, value)
            if key not in keys:
                continue
            if key in matches:
                raise ValueError(f"Ambiguous Bake datablock identity {key!r}")
            matches[key] = value
    if missing := keys - matches.keys():
        key = next(iter(missing))
        raise ValueError(f"Missing Bake datablock {key!r}")
    return matches


def route_datablock(host, collection, route, field):
    key = route.get(f"{field}_key")
    if key is not None:
        key = tuple(key)
        return resolve_datablocks(host, collection, (key,))[key]
    name = route.get("scene" if field == "scene" else f"{field}_name")
    return collection.get(name) if name is not None else None


def image_format(image):
    return {
        "source": str(image.source),
        "image_type": str(image.type),
        "channels": int(image.channels),
        "is_float": bool(image.is_float),
        "use_half_precision": bool(getattr(image, "use_half_precision", False)),
        "colorspace": str(image.colorspace_settings.name),
        "alpha_mode": str(image.alpha_mode),
    }

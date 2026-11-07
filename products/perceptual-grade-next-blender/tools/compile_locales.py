"""Validate semantic JSON catalogs and compile deterministic GNU MO files."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
from string import Formatter

from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo


_EPOCH = datetime(1980, 1, 1, tzinfo=timezone.utc)


def _fields(text):
    return {(name, spec, conversion)
            for _, name, spec, conversion in Formatter().parse(text)
            if name is not None}


def compile_locales(catalog_dir, output_dir):
    catalog_dir, output_dir = Path(catalog_dir), Path(output_dir)
    catalogs = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(catalog_dir.glob("*.json"))
    }
    if "en" not in catalogs:
        raise ValueError("Missing en.json")
    for locale, entries in catalogs.items():
        if not isinstance(entries, dict):
            raise ValueError(f"{locale}: catalog must be a JSON object")
        missing = catalogs["en"].keys() - entries.keys()
        extra = entries.keys() - catalogs["en"].keys()
        if missing or extra:
            raise ValueError(
                f"{locale}: missing IDs {sorted(missing)}, extra IDs {sorted(extra)}"
            )
        for message_id, value in entries.items():
            if not isinstance(message_id, str) or not message_id or "." not in message_id:
                raise ValueError(f"Invalid message ID: {message_id!r}")
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{locale}: empty/non-string translation for {message_id}")
            if _fields(catalogs["en"][message_id]) != _fields(value):
                raise ValueError(f"{locale}: format placeholders differ for {message_id}")

    for locale, entries in catalogs.items():
        catalog = Catalog(
            locale=locale,
            domain="perceptual_grade",
            charset="utf-8",
            creation_date=_EPOCH,
            revision_date=_EPOCH,
        )
        for message_id, translation in sorted(entries.items()):
            if " " in message_id:
                raise ValueError(f"Invalid message ID: {message_id!r}")
            catalog.add(message_id, translation)
        output = output_dir / locale / "LC_MESSAGES" / "perceptual_grade.mo"
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as stream:
            write_mo(stream, catalog, use_fuzzy=False)
        print(f"{locale}: {len(entries)} messages")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    compile_locales(args.catalog_dir, args.output_dir)


if __name__ == "__main__":
    main()

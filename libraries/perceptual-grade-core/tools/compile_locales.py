"""Compile shared-ID JSON catalogs to GNU MO using Babel."""
from pathlib import Path
import argparse,json
from datetime import datetime, timezone
from string import Formatter
from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo

EPOCH = datetime(1980, 1, 1, tzinfo=timezone.utc)


def fields(text):
    return {(name, spec, conv) for _, name, spec, conv in Formatter().parse(text) if name is not None}


def compile_catalogs(directory, output):
    catalogs = {path.stem: json.loads(path.read_text(encoding='utf-8'))
                for path in sorted(directory.glob('*.json'))}
    if 'en' not in catalogs:
        raise ValueError('Missing en.json')
    for locale, entries in catalogs.items():
        missing = catalogs['en'].keys() - entries.keys()
        extra = entries.keys() - catalogs['en'].keys()
        if missing or extra:
            raise ValueError(f'{locale}: missing IDs {sorted(missing)}, extra IDs {sorted(extra)}')
        for key, value in entries.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'{locale}: empty/non-string translation for {key}')
            if fields(catalogs['en'][key]) != fields(value):
                raise ValueError(f'{locale}: format placeholders differ for {key}')
    for locale, entries in catalogs.items():
        catalog = Catalog(locale=locale, domain='perceptual_grade', charset='utf-8', creation_date=EPOCH, revision_date=EPOCH)
        for key, value in sorted(entries.items()):
            assert key and ' ' not in key and '.' in key, key
            catalog.add(key, value)
        path = output / locale / 'LC_MESSAGES/perceptual_grade.mo'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('wb') as stream:
            write_mo(stream, catalog, use_fuzzy=False)
        print(f'{locale}: {len(entries)} messages')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    compile_catalogs(args.catalog_dir, args.output_dir)

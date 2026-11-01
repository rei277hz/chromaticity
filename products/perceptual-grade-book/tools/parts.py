"""mdBook preprocessor: number each part independently, retaining shared navigation."""
import json
import sys


def number_parts(book):
    def chapters(items, prefix=()):
        number = 0
        for item in items:
            if isinstance(item, dict) and 'PartTitle' in item:
                if prefix:
                    raise ValueError('Book parts must be at the root of SUMMARY.md.')
                number = 0
            elif isinstance(item, dict) and 'Chapter' in item:
                chapter = item['Chapter']
                if chapter['number'] is None:
                    if chapter['sub_items']:
                        raise ValueError('Unnumbered pages cannot contain numbered sections.')
                    continue
                number += 1
                current = (*prefix, number)
                if len(current) > 2:
                    raise ValueError('The contents may contain chapters and sections only.')
                chapter['number'] = list(current)
                chapters(chapter['sub_items'], current)
    chapters(book['items'])
    return book


if __name__ == '__main__':
    if sys.argv[1:] == ['supports', 'html']:
        sys.exit(0)
    if sys.argv[1:]:
        raise SystemExit('Only the HTML renderer is supported.')
    context, book = json.load(sys.stdin)
    json.dump(number_parts(book), sys.stdout, ensure_ascii=False)

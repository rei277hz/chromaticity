"""Parse generated DCTL controls and numerical body without UI sidecars."""
import re


def controls(source):
    result = []
    for line in source.splitlines():
        if not line.startswith('DEFINE_UI_PARAMS('):
            continue
        name, label, kind, tail = line[len('DEFINE_UI_PARAMS('):-1].split(', ', 3)
        values = tail.split(', ', 4)
        item = dict(name=name, label=label, type=kind, default=float(values[0].removesuffix('f')))
        if kind in ('DCTLUI_SLIDER_FLOAT', 'DCTLUI_SLIDER_INT'):
            item.update(zip(('min', 'max', 'step'), map(lambda x: float(x.removesuffix('f')), values[1:4])))
        if kind == 'DCTLUI_COMBO_BOX':
            item['options'] = [group.split(', ') for group in re.findall(r'\{([^}]*)\}', tail)]
        result.append(item)
    if not result or len({item['name'] for item in result}) != len(result):
        raise ValueError('Missing or duplicate DCTL controls')
    return result


def section(source, begin, end):
    """Extract an explicitly delimited numerical body for host compilation."""
    return source.split(begin, 1)[1].split(end, 1)[0]

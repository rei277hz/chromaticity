"""Scalar summaries for native scope diagnostics; no Blender dependency."""
from collections import Counter
from math import isfinite


def summarize(events):
    """Keep inclusive phase costs separate from event and wait counts."""
    phases = {}
    helpers = {}
    waits = {}
    reasons = Counter()
    counts = Counter()
    captures = set()
    for event in events:
        counts[str(event.get('event', 'unknown'))] += 1
        if event.get('capture') and event.get('event') == 'request_created':
            captures.add(str(event['capture']))
        if event.get('reason'):
            reasons[str(event['reason'])] += int(event.get('count', 1))
            seconds = event.get('seconds')
            if type(seconds) in (float, int) and isfinite(seconds) and seconds >= 0:
                waits[str(event['reason'])] = waits.get(str(event['reason']), 0.) + seconds
        phase, seconds = event.get('phase'), event.get('seconds')
        if phase and type(seconds) in (float, int) and isfinite(seconds) and seconds >= 0:
            entry = phases.setdefault(str(phase), dict(count=0, seconds=0., max_seconds=0.))
            entry['count'] += 1
            entry['seconds'] += seconds
            entry['max_seconds'] = max(entry['max_seconds'], seconds)
        for phase, seconds in event.get('helper_timings', {}).items():
            if phase.endswith('_seconds') and type(seconds) in (float, int) and isfinite(seconds) and seconds >= 0:
                entry = helpers.setdefault(phase, dict(count=0, seconds=0., max_seconds=0.))
                entry['count'] += 1
                entry['seconds'] += seconds
                entry['max_seconds'] = max(entry['max_seconds'], seconds)
    return dict(events=dict(sorted(counts.items())), reasons=dict(sorted(reasons.items())),
                capture_identities=len(captures), inclusive_phases=phases,
                helper_phases=helpers, wait_seconds=waits,
                durations_are_additive=False)

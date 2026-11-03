"""Portable summaries for the synthetic native Grade GUI drag experiment."""
from collections import Counter
from math import ceil
from statistics import median


def summary(values):
    """Descriptive sample quantiles; p95 uses the nearest-rank convention."""
    values = sorted(values)
    if not values:
        return None
    return dict(count=len(values), p50_seconds=median(values),
                p95_seconds=values[ceil(.95*len(values))-1],
                minimum_seconds=values[0], maximum_seconds=values[-1])


def summarize_samples(samples):
    """Only an exact current sample/revision with both pixel witnesses completes."""
    completed = []
    for row in samples:
        draw = row.get('draw')
        if draw is None:
            continue
        if row.get('outcome') == 'superseded':
            raise ValueError('A superseded sample cannot certify a current draw')
        if (draw['sample_id'], draw['revision']) != (row['sample_id'], row.get('revision')):
            raise ValueError('Draw identity does not match the accepted sample')
        if not draw['token_matches'] or not draw['preview_matches']:
            raise ValueError('The framebuffer does not contain the expected preview')
        if draw['at_seconds'] < row['accepted_seconds']:
            raise ValueError('Draw predates acceptance')
        completed.append(row)
    groups = []
    for scenario in dict.fromkeys(row['scenario'] for row in samples):
        accepted = [row for row in samples if row['scenario'] == scenario]
        selected = [row for row in completed if row['scenario'] == scenario]
        superseded = sum(row.get('outcome') == 'superseded' for row in accepted)
        phases = sorted({name for row in selected for name in row.get('phases', {})})
        groups.append(dict(scenario=scenario, accepted_count=len(accepted), drawn_count=len(selected),
                           superseded_count=superseded,
                           missing_count=len(accepted)-len(selected)-superseded,
                           sample_ids=[dict(session=row.get('session'), sample_id=row['sample_id'])
                                       for row in selected],
                           accepted_to_matching_draw=summary([
                               row['draw']['at_seconds']-row['accepted_seconds'] for row in selected]),
                           scenario_entry=summary([
                               row['draw']['at_seconds']-row['accepted_seconds'] for row in selected
                               if row.get('scenario_entry')]),
                           first_activation=summary([
                               row['draw']['at_seconds']-row['accepted_seconds'] for row in selected
                               if row.get('first_activation_families')]),
                           repeated_updates=summary([
                               row['draw']['at_seconds']-row['accepted_seconds'] for row in selected
                               if not row.get('scenario_entry')]),
                           phases={name: summary([row['phases'][name] for row in selected
                                                  if name in row.get('phases', {})]) for name in phases}))
    superseded = sum(row.get('outcome') == 'superseded' for row in samples)
    first_families = sorted({name for row in completed for name in row.get('first_activation_families', [])})
    return dict(accepted_count=len(samples), drawn_count=len(completed), superseded_count=superseded,
                missing_count=len(samples)-len(completed)-superseded, groups=groups,
                first_activation_by_family={name: summary([
                    row['draw']['at_seconds']-row['accepted_seconds'] for row in completed
                    if name in row.get('first_activation_families', [])]) for name in first_families},
                outcome_counts=dict(Counter(row.get('outcome', 'pending') for row in samples)))

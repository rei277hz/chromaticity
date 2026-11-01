"""Summarize a pg_scope_trace ZIP without executing its contents.

Run with Buck: buck2 run //products/perceptual-grade-blender:scope_trace_report -- --archive TRACE.zip
    --output REPORT.json --extension perceptual_grade.zip
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import zipfile


TICKET_FIELDS = ('node_pointer', 'owner', 'key', 'signal', 'epoch',
                 'scheduler_session', 'scope_key')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def summary(values):
    values = sorted(values)
    if not values:
        return {'count': 0}
    return dict(count=len(values), minimum_ms=values[0],
                median_ms=statistics.median(values), maximum_ms=values[-1],
                p95_ms=values[math.ceil(.95 * len(values)) - 1],
                p95_method='nearest-rank', p95_at_least_100_samples=len(values) >= 100)


def same_ticket(left, right):
    return all(left.get(name) == right.get(name) for name in TICKET_FIELDS)


def ms(start, end):
    return (end['monotonic_ns'] - start['monotonic_ns']) / 1e6


def span(start, end):
    return dict(begin_sequence=start['sequence'], end_sequence=end['sequence'],
                duration_ms=ms(start, end))


def read_archive(path):
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist()
                 if not name.startswith('__MACOSX/') and not name.endswith('/')]
        logs = [name for name in names if name.endswith('.jsonl')]
        metadata = [name for name in names if name.endswith('.metadata.json')]
        if len(logs) != 1 or len(metadata) != 1:
            raise ValueError('Expected exactly one JSONL log and one metadata JSON')
        events = [json.loads(line) for line in archive.read(logs[0]).splitlines() if line]
        meta = json.loads(archive.read(metadata[0]))
    if not events:
        raise ValueError('Empty trace')
    return events, meta


def compare_extension(path, metadata):
    with zipfile.ZipFile(path) as archive:
        sources = {name: digest(archive.read(name)) for name in archive.namelist()
                   if name.endswith('.py') and not name.startswith('__MACOSX/')}
    recorded = metadata.get('source_sha256', {})
    matches, differences, missing = [], [], []
    for name, expected in recorded.items():
        candidates = [value for key, value in sources.items()
                      if key == name or key.endswith('/' + name)]
        if not candidates:
            missing.append(name)
        elif expected in candidates:
            matches.append(name)
        else:
            differences.append(name)
    return dict(path=str(path), sha256=digest(path.read_bytes()),
                recorded_sources=len(recorded), matching_sources=len(matches),
                differing_sources=differences, missing_sources=missing)


def paired_durations(events):
    ends = {'capture_begin': ('capture_end', 'capture_wait', 'capture_error'),
            'scope_submit_begin': ('scope_submit', 'scope_submit_error'),
            'run_send_begin': ('run_send', 'run_send_error'),
            'job_message_begin': ('job_message_end', 'job_message_error'),
            'scope_decode_begin': ('scope_decode_end', 'scope_decode_error'),
            'scope_preview_decode_begin': ('scope_preview_decode_end','scope_preview_decode_error')}
    pending, groups, unmatched = {}, defaultdict(list), []
    for event in events:
        name = event['event']
        if name in ends:
            pending[event['call']] = event
        elif 'call' in event and event['call'] in pending:
            start = pending[event['call']]
            if name not in ends[start['event']]:
                continue
            del pending[event['call']]
            key = (start['event'], event.get('operation', start.get('operation')),
                   event.get('message_kind', start.get('message_kind')), name)
            groups[key].append(span(start, event))
    unmatched.extend(event['sequence'] for event in pending.values())
    return [dict(begin_event=key[0], operation=key[1], message_kind=key[2],
                 end_event=key[3], **summary([item['duration_ms'] for item in values]),
                 evidence=values) for key, values in sorted(groups.items(), key=lambda item: str(item[0]))], unmatched


def job_report(events):
    grouped = defaultdict(list)
    for event in events:
        if 'job_order' in event:
            grouped[(event.get('session'), event['job_order'], event.get('attempt'))].append(event)
    reports = []
    for (session, order, attempt), records in grouped.items():
        first = records[0]
        report = dict(session=session, job_order=order, attempt=attempt,
                      operation=first.get('operation'), role=first.get('role'),
                      evidence_sequences=[record['sequence'] for record in records])
        submits = [record for record in records if record['event'] == 'job_submit']
        sends = [record for record in records if record['event'] == 'run_send']
        completes = [record for record in records if record['event'] == 'job_message_begin'
                     and record.get('message_kind') in ('complete', 'failed', 'cancelled')]
        previews = [record for record in records if record['event'] == 'job_message_begin'
                    and record.get('message_kind') == 'preview']
        scope_submits = [record for record in records if record['event'] == 'scope_submit']
        report['generations'] = sorted({record['generation'] for record in records
                                        if 'generation' in record})
        if submits and sends:
            report['submission_to_dispatch'] = span(submits[0], sends[0])
        if sends:
            report.update({name: value for name, value in sends[-1].items()
                           if name.startswith('input_payload_')})
        if completes:
            receipt = completes[-1]
            report['terminal_message'] = receipt['message_kind']
            report['matches_active'] = receipt.get('matches_active')
            report.update({name: value for name, value in receipt.items()
                           if name.startswith('output_payload_')})
            if sends:
                report['dispatch_to_receipt'] = span(sends[-1], receipt)
            adoption = next((record for record in records if record['event'] == 'job_message_end'
                             and record.get('call') == receipt.get('call')), None)
            if adoption:
                report['foreground_message_handling'] = span(receipt, adoption)
        else:
            receipt, adoption = None, None
        visual_adoption=None
        if previews:
            preview=previews[-1]
            report.update({name.replace('output_payload_','visual_payload_'):value
                           for name,value in preview.items() if name.startswith('output_payload_')})
            if sends:report['dispatch_to_visual_receipt']=span(sends[-1],preview)
            visual_adoption=next((record for record in records if record['event']=='job_message_end'
                                  and record.get('call')==preview.get('call')),None)
            if visual_adoption:report['foreground_visual_message_handling']=span(preview,visual_adoption)
        decodes = [record for record in records if record['event'] == 'scope_decode_begin']
        decoded = [record for record in records if record['event'] == 'scope_decode_end']
        if decodes and decoded:
            report['scope_result_thaw'] = span(decodes[0], decoded[-1])
        preview_decodes=[record for record in records if record['event']=='scope_preview_decode_begin']
        preview_decoded=[record for record in records if record['event']=='scope_preview_decode_end']
        if preview_decodes and preview_decoded:
            report['scope_visual_thaw']=span(preview_decodes[0],preview_decoded[-1])
        cloud_decode=next((record for record in reversed(preview_decoded+decoded)
                           if record.get('cloud_backend')),None)
        if cloud_decode:
            report['cloud']={name.removeprefix('cloud_'):value for name,value in cloud_decode.items()
                             if name.startswith('cloud_')}
        if scope_submits:
            submitted = scope_submits[0]
            report['scope_key'] = submitted['scope_key']
            captures = [event for event in events if event['event'] == 'capture_end'
                        and event.get('scope_key') == submitted['scope_key']
                        and event['sequence'] < submitted['sequence']]
            requests = [event for event in events if event['event'] == 'scope_request'
                        and event.get('scope_key') == submitted['scope_key']
                        and event['sequence'] < submitted['sequence']]
            ticket = captures[-1] if captures else (requests[-1] if requests else None)
            if ticket:
                report['scope_ticket'] = {key: ticket[key] for key in TICKET_FIELDS}
                publications = [event for event in events if event['event'] == 'scope_publish'
                                and same_ticket(ticket, event)
                                and event['sequence'] > submitted['sequence']]
                finals=[event for event in publications if adoption and event['sequence']>=adoption['sequence']]
                if finals:
                    publication = finals[0]
                    report['publication_accepted'] = publication['accepted']
                    report['handling_to_publication'] = span(adoption, publication)
                    report['submission_to_publication'] = span(submitted, publication)
                visual=next((event for event in publications if event.get('scope_part')=='visual'),None)
                if visual and visual_adoption and visual['sequence']>=visual_adoption['sequence']:
                    report['visual_handling_to_publication']=span(visual_adoption,visual)
                    report['submission_to_visual_publication']=span(submitted,visual)
        reports.append(report)
    return reports


def drag_cadence(events,begin,release):
    """Count admitted lagging results during the gesture, without latest-key filtering."""
    node=begin['node_pointer']
    local=[event for event in events if begin['sequence']<event['sequence']<release['sequence']]
    requests=[event for event in events if event['event']=='scope_request' and event.get('node_pointer')==node]
    key_owners=defaultdict(set)
    for event in events:
        if event['event']=='scope_request' and event.get('scope_key') is not None:
            key_owners[event['scope_key']].add(event.get('node_pointer'))
    unique_keys={key for key,owners in key_owners.items() if owners=={node}}
    publications=[event for event in local if event['event']=='scope_publish'
                  and event.get('accepted') and event.get('node_pointer')==node]
    result=dict(duration_ms=ms(begin,release),channels={})
    for channel in sorted({event.get('channel','unknown') for event in publications} |
                          {event.get('channel','unknown') for event in local if event['event']=='scope_request'
                           and event.get('node_pointer')==node}):
        groups={}
        for part in ('visual','stats','full'):
            selected=[event for event in publications if event.get('channel')==channel
                      and event.get('scope_part','full')==part]
            matching={(event.get('scope_key'),part) for event in selected}
            draws=[event for event in local if event['event']=='warp_draw'
                   and event.get('scope_key') in unique_keys
                   and (event.get('scope_key'),event.get('scope_part','full')) in matching]
            ages=[]
            for publication in selected:
                request=next((event for event in reversed(requests)
                    if event['sequence']<publication['sequence'] and same_ticket(event,publication)),None)
                if request:ages.append(ms(request,publication))
            groups['p95' if part=='stats' else part]=dict(publications=len(selected),draws=len(draws),
                publications_per_second=1000*len(selected)/result['duration_ms'] if result['duration_ms'] else 0.,
                publication_gap=summary(ms(a,b) for a,b in zip(selected,selected[1:])),
                draw_gap=summary(ms(a,b) for a,b in zip(draws,draws[1:])),result_age=summary(ages),
                publication_sequences=[event['sequence'] for event in selected])
            groups['p95' if part=='stats' else part]['ambiguous_draw_keys']=len(
                {event.get('scope_key') for event in selected}-unique_keys)
        result['channels'][channel]=groups
    scope_keys=unique_keys
    submits=[event for event in local if event['event']=='scope_submit' and event.get('scope_key') in scope_keys]
    jobs={(event.get('session'),event.get('job_order'),event.get('attempt')) for event in submits}
    scoped=[event for event in local
            if (event.get('session'),event.get('job_order'),event.get('attempt')) in jobs]
    result['cancellations']=len({event.get('handle') for event in scoped if event['event']=='scope_cancel'})
    result['transfers']={label:dict(arrays=sum(event.get(prefix+'_arrays',0) for event in scoped
                                              if event['event']==name),
        bytes=sum(event.get(prefix+'_bytes',0) for event in scoped if event['event']==name))
        for label,name,prefix in (('input','run_send','input_payload'),('output','job_message_begin','output_payload'))}
    retirements=[event for event in local if event['event']=='scope_retired' and event.get('node_pointer')==node]
    gaps=[]
    for retired in retirements:
        following=next((event for event in submits if event['sequence']>retired['sequence']),None)
        if following:gaps.append(ms(retired,following))
    result['retirement_to_next_submission']=summary(gaps)
    return result


def gesture_report(events):
    begins = {event['gesture']: event for event in events
              if event['event'] == 'gesture_begin' and 'gesture' in event}
    releases = [event for event in events if event['event'] == 'gesture_release'
                and event.get('gesture') in begins]
    requests = [event for event in events if event['event'] == 'scope_request']
    publications = [event for event in events if event['event'] == 'scope_publish'
                    and event.get('accepted') and event.get('channel') == 'full']
    draws = [event for event in events if event['event'] == 'warp_draw']
    result = []
    for release in releases:
        begin = begins[release['gesture']]
        node = begin['node_pointer']
        following = next((event for event in events if event['event'] == 'gesture_begin'
                          and event.get('node_pointer') == node
                          and event['sequence'] > release['sequence']), None)
        boundary = following['sequence'] if following else float('inf')
        report = dict(gesture=release['gesture'], node=begin.get('node'), node_pointer=node,
                      begin_sequence=begin['sequence'], release_sequence=release['sequence'],
                      next_gesture_begin_sequence=following['sequence'] if following else None,
                      during_drag=drag_cadence(events,begin,release))
        before_release = [event for event in requests if event.get('node_pointer') == node
                          and event['sequence'] <= release['sequence']]
        active = before_release[-1] if before_release else None
        if not active or active['channel'] != 'full':
            report['exclusion'] = 'Latest request at release was not a full scope; later page selection is not gesture latency'
            result.append(report)
            continue
        # A reset/rebind starts a new request universe, even if there is no later drag.
        changed_session = next((event for event in requests if event.get('node_pointer') == node
                                and event['sequence'] > release['sequence']
                                and event['scheduler_session'] != active['scheduler_session']), None)
        if changed_session:
            boundary = min(boundary, changed_session['sequence'])
        local = [event for event in requests if event.get('node_pointer') == node
                 and event['channel'] == 'full' and begin['sequence'] < event['sequence'] < boundary
                 and event['scheduler_session'] == active['scheduler_session']]
        if not local:
            report['exclusion'] = 'No changed full-scope request for this gesture'
            result.append(report)
            continue
        final_request = local[-1]
        report['final_request_sequence'] = final_request['sequence']
        report['scope_ticket'] = {key: final_request[key] for key in TICKET_FIELDS}
        matching = [event for event in publications if same_ticket(event, final_request)
                    and event['sequence'] > release['sequence']]
        for phase,label in (('visual','visual'),('stats','p95')):
            publication=next((event for event in matching if event.get('scope_part')==phase
                              and event['sequence']<boundary),None)
            if publication is None:continue
            latest_before=[event for event in requests if event.get('node_pointer')==node
                           and event['channel']=='full' and event['sequence']<=publication['sequence']]
            if not latest_before or not same_ticket(latest_before[-1],publication):continue
            report['release_to_'+label+'_publication']=span(release,publication)
            draw=next((event for event in draws if event.get('scope_key')==final_request['scope_key']
                       and event.get('scope_part')==phase
                       and publication['sequence']<=event['sequence']<boundary),None)
            if draw:report['release_to_'+label+'_draw']=span(release,draw)
        if matching:
            publication = matching[0]
            report['exact_request_publication'] = span(release, publication)
            current = [event for event in requests if event.get('node_pointer') == node
                       and event['channel'] == 'full' and event['sequence'] <= publication['sequence']]
            uninterrupted = publication['sequence'] < boundary
            latest = bool(current and same_ticket(current[-1], publication))
            report['uninterrupted'] = uninterrupted
            report['latest_request_at_publication'] = latest
            if uninterrupted and latest:
                report['release_to_current_publication'] = span(release, publication)
                draw = next((event for event in draws if event.get('scope_key') == final_request['scope_key']
                             and publication['sequence'] <= event['sequence'] < boundary), None)
                if draw:
                    report['release_to_first_warp_draw'] = span(release, draw)
                    report['publication_to_first_warp_draw'] = span(publication, draw)
                    report['cloud_backend'] = draw.get('cloud_backend', 'point-arrays')
                    if 'duration_ms' in draw:
                        report['first_warp_draw_callback_ms'] = draw['duration_ms']
                else:
                    report['draw_unavailable'] = 'No first matching Warp draw before next gesture/reset; page may not be visible or key already drawn'
            else:
                report['exclusion'] = 'A subsequent gesture/reset intervened or a newer request existed at publication'
        else:
            report['exclusion'] = 'No accepted publication for final request after release'
        result.append(report)
    return result


def cloud_report(events, jobs, gestures):
    """Keep CPU fallback separate from healthy GPU measurements."""
    backends = sorted({job['cloud']['backend'] for job in jobs if job.get('cloud', {}).get('backend')}
                      | {event['cloud_backend'] for event in events if event.get('cloud_backend')}
                      | {gesture['cloud_backend'] for gesture in gestures if gesture.get('cloud_backend')})
    result = {}
    for backend in backends:
        selected_jobs = [job for job in jobs if job.get('cloud', {}).get('backend') == backend]
        selected_events = [event for event in events if event.get('cloud_backend') == backend]
        selected_gestures = [gesture for gesture in gestures if gesture.get('cloud_backend') == backend]
        phases = {}
        for name in ('cpu_seconds', 'preparation_seconds', 'compute_submission_seconds', 'raster_submission_seconds',
                     'readback_seconds', 'cpu_raster_seconds'):
            phases[name.removesuffix('_seconds')] = summary(
                [1000 * job['cloud'][name] for job in selected_jobs if name in job['cloud']])
        result[backend] = dict(jobs=len(selected_jobs),
            payloads=[{name: job[name] for name in ('job_order', 'input_payload_bytes', 'input_payload_arrays',
                                                 'output_payload_bytes', 'output_payload_arrays',
                                                 'visual_payload_bytes','visual_payload_arrays') if name in job}
                      for job in selected_jobs], helper_phases=phases,
            foreground_phases={name: summary([event['duration_ms'] for event in selected_events
                                             if event['event'] == name and 'duration_ms' in event])
                               for name in ('cloud_coverage_conversion', 'cloud_texture_upload',
                                            'cloud_raster_draw', 'warp_draw')},
            gesture_summaries={name: summary([gesture[name]['duration_ms'] for gesture in selected_gestures
                                              if name in gesture])
                               for name in ('release_to_current_publication', 'release_to_first_warp_draw',
                                            'release_to_visual_publication','release_to_p95_publication',
                                            'release_to_visual_draw','release_to_p95_draw')})
    return result


def generate(path, extension=None):
    events, metadata = read_archive(path)
    pairs, unmatched = paired_durations(events)
    jobs = job_report(events)
    gestures = gesture_report(events)
    report = dict(schema=4, archive=dict(path=str(path), sha256=digest(path.read_bytes())),
                  environment={key: metadata.get(key) for key in ('created', 'blender', 'blender_build', 'python', 'platform')},
                  event_count=len(events), event_counts=dict(Counter(event['event'] for event in events)),
                  span_ms=ms(events[0], events[-1]),
                  contiguous_sequences=all(right['sequence'] == left['sequence'] + 1 for left, right in zip(events, events[1:])),
                  monotonic_timestamps=all(right['monotonic_ns'] >= left['monotonic_ns'] for left, right in zip(events, events[1:])),
                  valid_gesture_releases=len(gestures),
                  empty_release_calls=sum(event['event'] == 'gesture_release' and 'gesture' not in event for event in events),
                  paired_durations=pairs, unmatched_begin_sequences=unmatched,
                  jobs=jobs, gestures=gestures,
                  cloud_backends=cloud_report(events, jobs, gestures),
                  gesture_summaries={key: summary([gesture[key]['duration_ms'] for gesture in gestures if key in gesture])
                                     for key in ('exact_request_publication', 'release_to_current_publication',
                                                 'release_to_first_warp_draw', 'publication_to_first_warp_draw',
                                                 'release_to_visual_publication','release_to_p95_publication',
                                                 'release_to_visual_draw','release_to_p95_draw')},
                  limitations=[
                      'Times include tracer overhead. Dispatch-to-receipt includes helper work, IPC and foreground polling; it is not pure CPU/GPU execution time.',
                      'Foreground message handling includes payload decoding, sealing and runtime handling; the trace cannot separate those components.',
                      'Active Stage-3 requests publish visible tone/page rasters before a matching statistics-only delta. First-draw instrumentation covers Warp only; visual and statistics draws are measured separately.',
                      'GPU compute/raster submission timings measure CPU submission, not GPU completion. Synchronous readback includes outstanding GPU work; upload and draw callbacks do not measure displayed frame presentation.',
                      'Cloud GPU and CPU-fallback measurements are reported separately. Latency p95 is the nearest-rank sample percentile; fewer than 100 samples are flagged and do not establish the experiment acceptance target.',
                      'Gesture latency requires the exact latest node/owner/key/signal/epoch/session/digest and excludes a subsequent same-node gesture or reset.',
                      'During-drag cadence counts accepted publications for the edited node only, including coherent lagging requests, and retains full/linear channels separately. Dependent scopes require their own gesture attribution. Draw/transfer keys shared by multiple nodes are excluded as ambiguous. Result age begins at its matching recorded request. Retirement and cancellation counts use their corresponding lifecycle events.',
                      'Exact-request completions after a new gesture are separately reported but are not uninterrupted released-current UI latency.',
                      'Warp draw identity includes view and tone. A release whose latest request was linear is excluded from full-scope latency; later page opening must not be counted as redraw delay.',
                      'Empty cleanup end(None) calls are excluded. Missing draw or publication measurements are not treated as zero.',
                  ])
    if extension:
        report['extension_comparison'] = compare_extension(extension, metadata)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--extension', type=Path)
    args = parser.parse_args()
    report = generate(args.archive, args.extension)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps(dict(output=str(args.output), event_count=report['event_count'],
                          gesture_summaries=report['gesture_summaries']), indent=2))


if __name__ == '__main__':
    main()

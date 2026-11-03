"""Display-referred HDR code-value metrics for native grading reports.

This module deliberately owns no Blender scene state.  ``HDRDisplay`` loads
the pinned Blender OCIO configuration lazily, while ``compare`` is pure NumPy
and can be tested without Blender.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys
import numpy as np


DISPLAY = "Rec.2100-PQ"
VIEW = "ACES 2.0 - HDR 1000 nits"
CODE_MAX = 1023.0


def _array(value, name, channels=3):
    result = np.asarray(value, dtype=np.float64)
    if result.ndim < 2 or result.shape[-1] != channels:
        raise ValueError(f'{name} must have a final dimension of {channels}')
    if not np.isfinite(result).all():
        raise ValueError(f'{name} contains nonfinite values')
    if not result.size:
        raise ValueError(f'{name} is empty')
    return result


def _stats(values, *, denominator=None):
    values = np.asarray(values, dtype=np.float64)
    flat = values.reshape(-1, values.shape[-1]) if values.ndim > 1 else values.reshape(-1, 1)
    result = {}
    for index, channel in enumerate(('R', 'G', 'B')[:flat.shape[-1]]):
        data = np.abs(flat[:, index])
        result[channel] = _distribution(data)
    peak = np.max(np.abs(flat), axis=-1)
    result['pixel_peak'] = _distribution(peak)
    if denominator is not None:
        denom = np.asarray(denominator).reshape(-1)
        eligible = denom >= 1.0
        percentages = np.divide(peak[eligible], denom[eligible],
                                out=np.zeros(np.count_nonzero(eligible)), where=denom[eligible] != 0) * 100.
        result['percentage'] = _distribution(percentages) if percentages.size else _distribution(np.array([], float))
        result['percentage_eligible_pixels'] = int(np.count_nonzero(eligible))
        result['near_black_pixels'] = int(np.count_nonzero(~eligible))
        result['zero_reference_pixels'] = int(np.count_nonzero(denom == 0.))
        result['near_black'] = _distribution(peak[~eligible])
    return result


def _distribution(data):
    data = np.asarray(data, dtype=np.float64).reshape(-1)
    if not data.size:
        return dict(count=0, mean=0., rmse=0., p50=0., p95=0., p99=0., p99_9=0., max=0.,
                    thresholds={str(x): 0 for x in (.1, .5, 1., 2.)})
    return dict(count=int(data.size), mean=float(np.mean(data)),
                rmse=float(np.sqrt(np.mean(data*data))),
                p50=float(np.percentile(data, 50)), p95=float(np.percentile(data, 95)),
                p99=float(np.percentile(data, 99)), p99_9=float(np.percentile(data, 99.9)),
                max=float(np.max(data)),
                thresholds={str(x): int(np.count_nonzero(data > x)) for x in (.1, .5, 1., 2.)})


def _signed_stats(values):
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    result = _distribution(values)
    result.update(min=float(np.min(values)) if values.size else 0.,
                  worsened=int(np.count_nonzero(values > 0)),
                  unchanged=int(np.count_nonzero(values == 0)),
                  improved=int(np.count_nonzero(values < 0)))
    return result


def _signed_distribution(data, denominator):
    """Distribution retaining the sign of worsening values."""
    data = np.asarray(data, dtype=np.float64).reshape(-1)
    denom = np.asarray(denominator, dtype=np.float64).reshape(-1)
    eligible = denom >= 1.
    percentage = 100. * data[eligible] / denom[eligible]
    result = _signed_stats(data)
    result.update(percentage=_signed_stats(percentage),
                  percentage_eligible_pixels=int(np.count_nonzero(eligible)),
                  near_black_pixels=int(np.count_nonzero(~eligible)),
                  zero_reference_pixels=int(np.count_nonzero(denom == 0.)),
                  near_black=_signed_stats(data[~eligible]),
                  positive_only=_distribution(data[data > 0.]))
    return result


def _witness(index, inputs, reference, baseline, candidate, *, reference_rgb=None,
             baseline_rgb=None, candidate_rgb=None, current_error, reduced_error,
             movement, worsening, denominator):
    def item(value):
        return None if value is None else np.asarray(value)[index].tolist()
    return dict(index=int(index), input_rgb=item(inputs),
                reference_code_rgb=item(reference), baseline_code_rgb=item(baseline),
                candidate_code_rgb=item(candidate), reference_rgb=item(reference_rgb),
                baseline_rgb=item(baseline_rgb), candidate_rgb=item(candidate_rgb),
                current_error=float(np.ravel(current_error)[index]), reduced_error=float(np.ravel(reduced_error)[index]),
                movement=float(np.ravel(movement)[index]), worsening=float(np.ravel(worsening)[index]),
                reference_peak_code=float(np.ravel(denominator)[index]))


def compare(reference_codes, baseline_codes, candidate_codes=None, *, inputs=None,
            reference_rgb=None, baseline_rgb=None, candidate_rgb=None):
    """Compare matched reference/current/candidate code RGB arrays.

    Percentages are intentionally based on the largest absolute reference
    channel and are defined only for pixels whose peak is at least one code.
    """
    reference = _array(reference_codes, 'reference_codes')
    baseline = _array(baseline_codes, 'baseline_codes')
    if baseline.shape != reference.shape:
        raise ValueError('baseline_codes shape mismatch')
    candidate = None if candidate_codes is None else _array(candidate_codes, 'candidate_codes')
    if candidate is not None and candidate.shape != reference.shape:
        raise ValueError('candidate_codes shape mismatch')
    if inputs is not None:
        inputs = np.asarray(inputs, dtype=np.float64)
        if inputs.ndim < 2 or inputs.shape[:-1] != reference.shape[:-1] or inputs.shape[-1] not in (3, 4):
            raise ValueError('inputs shape mismatch')
        if not np.isfinite(inputs).all():
            raise ValueError('inputs contains nonfinite values')
        if inputs.shape[-1] == 4:
            inputs = inputs[..., :3]
    for name, rgb in (('reference_rgb', reference_rgb), ('baseline_rgb', baseline_rgb),
                      ('candidate_rgb', candidate_rgb)):
        if rgb is not None and _array(rgb, name).shape != reference.shape:
            raise ValueError(f'{name} shape mismatch')
    current_error_channel = np.abs(baseline-reference)
    current_error = np.max(current_error_channel, axis=-1)
    denominator = np.max(np.abs(reference), axis=-1)
    result = dict(schema=1, code_range=[0., CODE_MAX], channels=['R','G','B'],
                  current=_stats(current_error_channel, denominator=denominator),
                  reference_peak_code=_distribution(denominator))
    scene = {name: (None if rgb is None else _array(rgb, name))
             for name, rgb in (('reference', reference_rgb), ('baseline', baseline_rgb),
                               ('candidate', candidate_rgb))}
    if candidate is None:
        result['candidate'] = None
        flat = lambda value: None if value is None else np.asarray(value).reshape(-1, 3)
        result['witnesses'] = {'current_error': _witness(int(np.argmax(current_error)), flat(inputs),
                                                          flat(reference), flat(baseline), None,
                                                          reference_rgb=flat(scene['reference']),
                                                          baseline_rgb=flat(scene['baseline']), candidate_rgb=None,
                                                          current_error=current_error,
                                                          reduced_error=current_error, movement=np.zeros_like(current_error),
                                                          worsening=np.zeros_like(current_error), denominator=denominator)}
        return result
    reduced_error_channel = np.abs(candidate-reference)
    reduced_error = np.max(reduced_error_channel, axis=-1)
    movement_channel = np.abs(candidate-baseline)
    movement = np.max(movement_channel, axis=-1)
    worsening = reduced_error-current_error
    signed = _signed_distribution(worsening, denominator)
    signed['channels'] = {channel: _signed_stats((reduced_error_channel-current_error_channel)[..., index])
                          for index, channel in enumerate(('R', 'G', 'B'))}
    result['candidate'] = dict(error=_stats(reduced_error_channel, denominator=denominator),
                               movement=_stats(movement_channel, denominator=denominator), worsening=signed)
    witnesses = {}
    flat = lambda value: None if value is None else np.asarray(value).reshape(-1, 3)
    witness_inputs = flat(inputs)
    witness_reference = flat(reference)
    witness_baseline = flat(baseline)
    witness_candidate = flat(candidate)
    witness_reference_rgb = flat(scene['reference'])
    witness_baseline_rgb = flat(scene['baseline'])
    witness_candidate_rgb = flat(scene['candidate'])
    for name, values in [('current_error', current_error), ('reduced_error', reduced_error),
                         ('movement', movement), ('worsening', worsening)]:
        index = int(np.argmax(values))
        witnesses[name] = _witness(index, witness_inputs, witness_reference, witness_baseline,
                                    witness_candidate, reference_rgb=witness_reference_rgb,
                                    baseline_rgb=witness_baseline_rgb,
                                    candidate_rgb=witness_candidate_rgb, current_error=current_error,
                                    reduced_error=reduced_error,
                                    movement=movement, worsening=worsening, denominator=denominator)
    result['witnesses'] = witnesses
    return result


@dataclass
class HDRDisplay:
    """Pinned OCIO display processors, keyed by input scene space."""
    spaces: tuple = ('Linear Rec.709', 'Linear Rec.2020', 'ACEScg')

    def __post_init__(self):
        import bpy
        resources = Path(bpy.utils.resource_path('LOCAL'))
        site = resources/'python/lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
        previous = sys.path
        try:
            sys.path = [str(site), *previous]
            import PyOpenColorIO as ocio
        finally:
            sys.path = previous
        config_path = resources/'datafiles/colormanagement/config.ocio'
        self._config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
        config = ocio.Config.CreateFromFile(str(config_path))
        self._processors = {}
        for space in self.spaces:
            transform = ocio.DisplayViewTransform(src=space, display=DISPLAY, view=VIEW)
            self._processors[space] = config.getProcessor(transform).getDefaultCPUProcessor()
        self.metadata = dict(display=DISPLAY, view=VIEW, code_max=CODE_MAX,
                             config_sha256=self._config_hash, blender_version=bpy.app.version_string,
                             ocio_version=ocio.__version__, exposure_stops=0, gamma=1, looks=[],
                             input_spaces=list(self.spaces), precision_boundary='float32 OCIO buffer',
                             processor_cache_ids={space: processor.getCacheID()
                                                  for space, processor in self._processors.items()},
                             code_arithmetic='float64', pq_already_in_display=True,
                             clipping=False, integer_quantization=False)

    def codes(self, rgb, space):
        if space not in self._processors:
            raise ValueError(f'Unsupported HDR input space: {space}')
        with np.errstate(over='ignore'):
            value = np.array(_array(rgb, 'rgb'), dtype=np.float32, order='C', copy=True)
        if not np.isfinite(value).all():
            raise ValueError('RGB input is not representable at the float32 OCIO boundary')
        self._processors[space].applyRGB(value.reshape(-1, 3))
        if not np.isfinite(value).all():
            raise ValueError('OCIO produced nonfinite display values')
        return value.astype(np.float64)*CODE_MAX

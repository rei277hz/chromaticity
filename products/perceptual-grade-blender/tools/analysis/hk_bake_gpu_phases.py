"""Instrument one already prepared reference GPU bake.

This small helper is deliberately separate from the benchmark driver.  The
caller owns Blender/GPU initialization, the immutable lookup table, and the
prepared :class:`BakeStack`/``Program`` objects.  ``run`` temporarily proxies
the program's shader and output texture, so its API intervals include the
synchronous compute dispatch and texture readback without changing the shader
or the program implementation.

The proxy is installed only for the duration of ``operation``.  In particular,
the operation may call ``stack.bake_native(..., 'GPU')`` and therefore upload a
fresh parameter texture through the patched ``GPUTexture`` constructor.  All
program objects are restored before this function returns, including when the
operation raises.
"""

from contextlib import ExitStack
import time

import numpy as np

from tools.analysis.inverse_gpu_startup import Shader, Texture, Trace


def _unwrap(value):
    """Return the raw value when a previous trace proxy is still attached."""
    return value.raw if isinstance(value, (Texture, Shader)) else value


def _same_bits(actual, expected):
    """Compare shape, dtype, and bytes without allowing NumPy coercion."""
    actual = np.asarray(actual)
    expected = np.asarray(expected)
    return bool(actual.shape == expected.shape and actual.dtype == expected.dtype
                and actual.tobytes(order="C") == expected.tobytes(order="C"))


def run(program, operation, rgb, expected=None):
    """Run and trace one operation using an existing GPU ``program``.

    Parameters
    ----------
    program:
        A prepared ``bake_inverse_gpu.Program``.  Its shader and output texture
        are temporarily replaced with tracing proxies.
    operation:
        Callable accepting exactly ``rgb``.  A typical operation is
        ``lambda values: stack.bake_native(values, 'GPU')``; the stack should
        already refer to ``program`` so that any parameter uploads happen
        inside the measured operation.
    rgb:
        Input rows passed to ``operation``.
    expected:
        Optional expected result.  When present, the report includes a strict
        shape/dtype/byte-for-byte comparison.

    Returns
    -------
    tuple
        ``(values, report)``.  ``report['api']`` contains per-API inclusive and
        exclusive totals from :class:`Trace`; ``host_remainder_seconds`` is
        the operation wall interval minus those API intervals.  API calls are
        serialized in the current compute path, so this remainder is the host
        orchestration/conversion portion, not a hardware-GPU timer.
    """
    import gpu

    raw_shader = _unwrap(program.shader)
    raw_output = _unwrap(program.output)
    trace = Trace()
    trial = 1
    trace.trial = trial

    # The trace patches GPU constructors/dispatch globally.  Keep the scope
    # narrow and always put the original program attributes back first.
    with ExitStack() as patches:
        trace.install(gpu, patches)
        program.shader = Shader(raw_shader, trace)
        program.output = Texture(raw_output, trace)
        started = time.perf_counter()
        try:
            values = trace.call("operation", operation, (rgb,))
        finally:
            wall = time.perf_counter() - started
            program.shader = raw_shader
            program.output = raw_output
            if hasattr(program, "parameters"):
                program.parameters = _unwrap(program.parameters)

    # All wrapped API events belong to this operation.  ``Trace.call`` records
    # nested intervals; summing the individual API intervals is valid for the
    # sequential Blender compute path, while the exclusive values provide the
    # non-overlapping accounting useful for nested wrappers.
    api = trace.totals(trial)
    # Exclude the enclosing operation marker from the API table.  It is useful
    # in the raw trace, but is neither a Blender API call nor host remainder.
    api.pop("operation", None)
    api_seconds = sum(float(row["seconds"]) for row in api.values())
    exclusive_api_seconds = sum(float(row["exclusive_seconds"]) for row in api.values())
    result = np.asarray(values)
    report = {
        "wall_seconds": float(wall),
        "api": api,
        "api_seconds": float(api_seconds),
        "exclusive_api_seconds": float(exclusive_api_seconds),
        "host_remainder_seconds": float(wall - exclusive_api_seconds),
        "events": trace.events,
        "bit_identical": None if expected is None else _same_bits(result, expected),
    }
    if report["host_remainder_seconds"] < -1e-9:
        raise ArithmeticError("Overlapping GPU API phase accounting")
    if expected is not None and not report["bit_identical"]:
        raise ArithmeticError("GPU phase instrumentation changed the bake result")
    return values, report


__all__ = ["run"]

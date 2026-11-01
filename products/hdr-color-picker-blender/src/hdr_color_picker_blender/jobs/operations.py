"""Picker-only helper operations; no grading imports or host references."""


def dispatch(operation, inputs, context):
    if operation != 'picker_slice':
        raise ValueError('Unknown picker operation: ' + operation)
    from ...hdr_color_picker_core import render_slice
    context.checkpoint()
    result = render_slice(**inputs)
    context.checkpoint()
    return result

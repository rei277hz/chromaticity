"""Evaluate the independent reference from a JSON request on stdin.

Example: {"operation":"forward","values":[[0.18,0.18,0.18]],"linear":{"exposure":1}}
"""
import json
import sys
from .model import Model, Settings, LinearSettings
from .export import OutputCompressionSettings, OutputDensitySettings
from .grading import ToneSettings, ColorSettings
from .unified_chroma import UnifiedChromaSettings


def main():
    request = json.load(sys.stdin)
    baseline = request.get('tone_chroma')
    settings = Settings(white=request.get('white', 'D65'),
                        linear=LinearSettings(**request.get('linear', {})),
                        tone=ToneSettings(**request.get('tone', {})),
                        color=ColorSettings(**request.get('color', {})),
                        tone_chroma=UnifiedChromaSettings(**baseline) if baseline is not None else None,
                        output_density=OutputDensitySettings(**request.get('output_density', {})),
                        output_compression=OutputCompressionSettings(**request.get('output_compression', {})))
    model = Model(settings, request.get('space', 'Linear Rec.709'))
    operation = request.get('operation', 'forward')
    if operation == 'forward':
        result = dict(value=model.forward(request['values']).tolist())
    elif operation == 'inverse':
        inverse = model.inverse(request['values'])
        result = dict(value=inverse.value.tolist(), residual=inverse.residual.tolist(), status=inverse.status.tolist())
    else:
        raise ValueError('Operation must be forward or inverse')
    json.dump(result, sys.stdout, allow_nan=False)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()

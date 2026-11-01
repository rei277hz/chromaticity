"""Derive the fixed shadow anchor from neutral appearance and log-gap spacing.

This build-time calculation deliberately imports no grading implementation or
calibration literal. Production uses the report's nearest binary64 value.
"""
import argparse
from decimal import Context, Decimal, localcontext
import json
from pathlib import Path


D = Decimal
PRECISION = 80
ITERATIONS = 256


def neutral_j(y, fl, gamma):
    """Neutral J_A, white=100, for luminance relative to reference white."""
    if not y:
        return D(0)
    white_p = fl ** D('.42')
    white_response = white_p / (D('27.13') + white_p)
    p = (fl * y) ** D('.42')
    return 100 * ((p / (D('27.13') + p)) / white_response) ** gamma


def neutral_y(j, fl, gamma):
    white_p = fl ** D('.42')
    white_response = white_p / (D('27.13') + white_p)
    u = white_response * (j / 100) ** (1 / gamma)
    return (D('27.13') * u / (1 - u)) ** (1 / D('.42')) / fl


def regression(shadow, midgray, white, high):
    gaps = (shadow, midgray - shadow, white - midgray, high - white)
    logs = tuple(gap.ln() for gap in gaps)
    beta = sum((D(i) - D('1.5')) * value for i, value in enumerate(logs)) / 5
    alpha = sum(logs) / 4 - D('1.5') * beta
    residuals = tuple(value - alpha - beta * i for i, value in enumerate(logs))
    derivative = 2 * (residuals[0] / shadow - residuals[1] / (midgray - shadow))
    stationarity = (midgray - shadow) * residuals[0] - shadow * residuals[1]
    return gaps, alpha, beta, residuals, derivative, stationarity


def derive():
    with localcontext(Context(prec=PRECISION)):
        reference, midgray_y, high_nits = D(203), D('.18'), D(1000)
        la = D('.1') * reference
        k = 1 / (5 * la + 1)
        fl = D('.2') * k**4 * 5 * la + D('.1') * (1 - k**4)**2 * (5 * la)**(D(1) / 3)
        gamma = D('.525') * (D('1.48') + D('.1').sqrt())
        midgray = neutral_j(midgray_y, fl, gamma)
        white, high = D(100), neutral_j(high_nits / reference, fl, gamma)
        a_gap, b_gap = white - midgray, high - white

        # With t=S/(M-S), g' = C+.8+.1 ln(t)+.2 ln(1+t)+.3/t+.7t.
        # ln(t)>=1-1/t and AM-GM give g'>C+.9+2 sqrt(.14)>0.
        c = (3 * a_gap.ln() - b_gap.ln() - 2 * midgray.ln()) / 10
        uniqueness_bound = c + D('.9') + 2 * D('.14').sqrt()
        if uniqueness_bound <= 0:
            raise ValueError('The global uniqueness bound must be positive')

        left, right = midgray / 1024, midgray * 1023 / 1024
        initial_bracket = (left, right)
        initial_signs = tuple(regression(s, midgray, white, high)[-1] for s in initial_bracket)
        if not initial_signs[0] < 0 < initial_signs[1]:
            raise ValueError('The stationary point is not bracketed')
        for _ in range(ITERATIONS):
            midpoint = (left + right) / 2
            if regression(midpoint, midgray, white, high)[-1] < 0:
                left = midpoint
            else:
                right = midpoint
        shadow = (left + right) / 2
        gaps, alpha, beta, residuals, derivative, stationarity = regression(shadow, midgray, white, high)
        scale, ratio = alpha.exp(), beta.exp()
        fitted_gaps = tuple((alpha + beta * i).exp() for i in range(4))
        low_y = neutral_y(shadow, fl, gamma)
        exact_ratio = b_gap / a_gap
        exact_first, exact_second = a_gap / exact_ratio**2, a_gap / exact_ratio
        implied_midgray = exact_first + exact_second
        strings = lambda values: [str(value) for value in values]
        return {
            'schema': 1,
            'precision_digits': PRECISION,
            'calibration': dict(zip(
                ('reference_white_nits', 'midgray_y', 'high_nits', 'fl', 'gamma'),
                strings((reference, midgray_y, high_nits, fl, gamma)))),
            'landmarks': dict(zip(('black', 'shadow', 'midgray', 'white', 'high'),
                                  strings((D(0), shadow, midgray, white, high)))),
            'fit': {
                'criterion': 'sum((ln(d_i) - alpha - beta*i)^2), i=0..3',
                'gaps': strings(gaps), 'fitted_gaps': strings(fitted_gaps),
                'log_residuals': strings(residuals),
                'relative_residuals': strings(gap / fitted - 1 for gap, fitted in zip(gaps, fitted_gaps)),
                'a': str(scale), 'r': str(ratio),
                'objective': str(sum(e * e for e in residuals)),
                'derivative': str(derivative),
            },
            'solution': {'low_y': str(low_y), 'low_y_binary64': float(low_y),
                         'shadow_nits': str(reference * low_y),
                         'neutral_roundtrip_error': str(neutral_j(low_y, fl, gamma) - shadow)},
            'solver': {
                'method': 'bracketed_bisection', 'iterations': ITERATIONS,
                'initial_bracket': strings(initial_bracket),
                'initial_bracket_stationarity': strings(initial_signs),
                'bracket': strings((left, right)),
                'bracket_stationarity': strings(regression(s, midgray, white, high)[-1] for s in (left, right)),
                'stationarity': str(stationarity),
                'uniqueness_derivative_lower_bound': str(uniqueness_bound),
                'uniqueness_proof': (
                    'F\'(S)=2g(S)/(S(M-S)); g=(M-S)e0-S*e1. '
                    'For t=S/(M-S)>0 and C=(3ln(W-M)-ln(H-W)-2ln(M))/10, '
                    'g\'=C+.8+.1ln(t)+.2ln(1+t)+.3/t+.7t. '
                    'ln(t)>=1-1/t, ln(1+t)>0 and AM-GM imply '
                    'g\'>C+.9+2sqrt(.14)>0. '
                    'g tends to -infinity at S=0 and +infinity at S=M; '
                    'therefore its unique root is the unique global minimum of F.'),
            },
            'exact_progression': {
                'ratio': str(exact_ratio), 'required_first_gap': str(exact_first),
                'required_second_gap': str(exact_second),
                'implied_midgray': str(implied_midgray), 'mismatch': str(implied_midgray - midgray),
                'explanation': 'The last two fixed gaps determine r; their backward continuation does not reach fixed M.',
            },
        }


def summary(report):
    landmarks, fit, solution = (report[key] for key in ('landmarks', 'fit', 'solution'))
    def number(value):
        return f'{D(value):.12f}'
    lines = [
        '# Derived shadow anchor', '',
        'Reproduce with `buck2 build //libraries/perceptual-grade-core:shadow_anchor`.', '',
        f"Use **LOW_Y = {solution['low_y_binary64']!r}** (nearest binary64).",
        f"Shadow J_A = {number(landmarks['shadow'])}; luminance = {number(solution['shadow_nits'])} nits.", '',
        'Calibration: neutral appearance at 203-nit white, 18% midgray and 1000-nit high.',
        'Minimize squared log errors of the four gaps against a fitted geometric progression.',
        f"Fitted ratio r = {number(fit['r'])}; objective = {number(fit['objective'])}.", '',
        '| Landmark | J_A | Gap | Relative error against fit |',
        '|---|---:|---:|---:|', '| Black | 0 | — | — |',
    ]
    for i, name in enumerate(('shadow', 'midgray', 'white', 'high')):
        error = 100 * D(fit['relative_residuals'][i])
        lines.append(f"| {name.title()} | {number(landmarks[name])} | {number(fit['gaps'][i])} | {error:+.6f}% |")
    exact, solver = report['exact_progression'], report['solver']
    lines += ['', 'An exact progression is impossible with the other landmarks fixed:',
              f"the last two gaps force r={number(exact['ratio'])}, placing M at {number(exact['implied_midgray'])}",
              f"instead of {number(landmarks['midgray'])}.", '',
              f"Solved independently with {PRECISION}-digit Decimal arithmetic and {ITERATIONS} bisections.",
              solver['uniqueness_proof'],
              f"Global lower bound for g': {number(solver['uniqueness_derivative_lower_bound'])}.", '',
              'Neutral equations (Y relative to reference white):', '', '```text',
              'L_A=.1*203; k=1/(5*L_A+1)',
              'F_L=.2*k^4*5*L_A+.1*(1-k^4)^2*(5*L_A)^(1/3)',
              'gamma=.525*(1.48+sqrt(.1))',
              'p_w=F_L^.42; w=p_w/(27.13+p_w); p=(F_L*Y)^.42',
              'J_A(Y)=100*((p/(27.13+p))/w)^gamma',
              'u=w*(S/100)^(1/gamma); LOW_Y=(27.13*u/(1-u))^(1/.42)/F_L',
              '```', '',
              'The neutral-response inverse gives LOW_Y; no grading literal or runtime solver is used.',
              'Full-precision decimal results and the final root bracket are in `report.json`.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    report = derive()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    (args.output_dir / 'summary.md').write_text(summary(report), encoding='utf-8')


if __name__ == '__main__':
    main()

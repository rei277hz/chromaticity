"""Deterministic independent validation inputs; no product fixtures required."""
from dataclasses import replace
import numpy as np
from color_tools.perceptual_grade_nodes import LinearSettings, ToneSettings

SPACES = ('Linear Rec.709', 'Linear Rec.2020', 'ACEScg')
# Authored Gizmo/slider ranges, not the widened RNA storage bounds used for
# matrix decomposition. Sources: core/model/{linear,tone}.py and graph/nodes.py.
LINEAR_RANGES = {'exposure':(-6.,6.), 'source_xy':(0.,.9), 'balance':(-2.,2.),
                 'spread':(-100.,150.), 'heading':(-180.,180.)}
TONE_RANGES = ((0.,2.),(.01,50.),(.1,250.),(10.,1000.),(100.,10000.))
PEAKS = (500,1000,2000,4000)
FITS = range(-2,3)  # Existing UI choices intersect the experiment's Tone Fit <= 2 cap.


def assert_ui_settings(linear, tone):
    """Keep the precision corpus inside the authored UI control contract."""
    from color_tools.perceptual_grade_reference.grading import Tone, ToneSettings as RefTone
    for name,(lo,hi) in LINEAR_RANGES.items():
        value=np.asarray(getattr(linear,name))
        if not np.all((value >= lo)&(value <= hi)):
            raise ValueError(f'{name} is outside the Gizmo/slider range')
    if linear.matrix is not None:
        raise ValueError('Arbitrary matrix overrides are API tests, not UI precision cases')
    for value,(lo,hi) in zip(tone.input_nits,TONE_RANGES):
        if not lo <= value <= hi:
            raise ValueError('Tone anchor is outside its UI range')
    if tone.fit not in FITS or tone.peak_nits not in PEAKS or tone.reference_nits != 203.:
        raise ValueError('Tone fit/viewing/peak is outside the accepted experiment domain')
    ref=Tone(RefTone())
    if np.any(np.diff(ref.nits_to_j(tone.input_nits)) < .001-1e-12):
        raise ValueError('Tone anchors violate the UI landmark spacing')


def grades():
    base = LinearSettings()
    yield 'reset', base, ToneSettings()
    yield 'linear', replace(base, exposure=.7, source_xy=(.34, .36),
                           balance=(.15, -.12), spread=(20., -15.), heading=(8., -12.)), ToneSettings()
    yield 'tone', base, ToneSettings(input_nits=(0., 8., 40., 235., 1150.))
    yield 'narrow', base, ToneSettings(input_nits=(.2, .21, 42., 250., 1300.), fit=2.)
    yield 'dark', replace(base, exposure=-1.5), ToneSettings(input_nits=(.01, 1., 90., 400., 4000.), fit=-2.)
    yield 'combined', replace(base, exposure=.3, source_xy=(.30, .35),
                             balance=(.1, -.05), spread=(-15., 30.), heading=(-6., 8.)), ToneSettings(input_nits=(0., 7., 45., 203., 1000.), fit=1., peak_nits=2000.)
    yield 'poles', replace(base, exposure=6.), ToneSettings(input_nits=(0., .01, .1, 10., 100.))


def ui_boundaries():
    """Individual slider extremes, with tone anchor ordering retained."""
    base=LinearSettings()
    tone=ToneSettings(input_nits=(0.,8.,40.,235.,1150.))
    for name in ('exposure','balance','spread','heading'):
        for value in LINEAR_RANGES[name]:
            for axis in range(1 if name=='exposure' else 2):
                pair=[0.,0.];pair[axis]=value
                linear=replace(base,**{name:value if name=='exposure' else tuple(pair)})
                yield f'{name}_{axis}_{value:g}',linear,tone
    for xy in ((.25,.3),(.4,.4),(.5,.3)):
        yield f'source_{xy[0]}_{xy[1]}',replace(base,source_xy=xy),tone
    # The square's corners and edge midpoints are valid RNA values but project
    # onto the CAT16-positive polygon before the matrix is built. These are the
    # native cases most likely to expose a nearly-zero adaptation gain.
    for index, xy in enumerate(((0., 0.), (.9, 0.), (.9, .9), (0., .9),
                                (.45, 0.), (.9, .45), (.45, .9), (0., .45))):
        yield f'source_boundary_{index}', replace(base, source_xy=xy), tone
    for fit in FITS:
        yield f'fit_{fit}',base,replace(tone,fit=fit)
    for peak in PEAKS:
        yield f'peak_{peak}',base,replace(tone,peak_nits=peak)
    # Each endpoint is exercised in an ordered, directly UI-reachable curve.
    for index,nits in enumerate(((2.,8.,40.,235.,1150.),(0.,.01,40.,235.,1150.),
                                 (0.,50.,80.,235.,1150.),(0.,.01,.1,235.,1150.),
                                 (0.,8.,250.,300.,1150.),(0.,1.,5.,10.,1150.),
                                 (0.,8.,40.,1000.,1500.),(0.,1.,5.,50.,100.),
                                 (0.,8.,40.,235.,10000.))):
        yield f'anchor_endpoint_{index}',base,replace(tone,input_nits=nits)

    # Every neighboring pair can reach .001 J with suitable preceding values:
    # solve the
    # next nits value from J(previous)+.001, using the same reference viewing
    # response as the actual landmark clamp. This exercises the exact minimum
    # gap accepted by the UI without inventing out-of-range controls.
    from color_tools.perceptual_grade_reference.grading import Tone, ToneSettings as RefTone
    reference = Tone(RefTone())

    def j_to_nits(target, lo, hi):
        low, high = float(lo), float(hi)
        for _ in range(90):
            middle = (low+high)/2
            if float(reference.nits_to_j(middle)) < target:
                low = middle
            else:
                high = middle
        return (low+high)/2

    minimum_pairs = ((0, .2, .01, 50.), (1, 5., .1, 250.), (2, 20., 10., 1000.),
                     (3, 100., 100., 10000.))
    for index, previous, lo, hi in minimum_pairs:
        anchors = [0., 5., 20., 100., 1000.]
        anchors[index] = previous
        target = float(reference.nits_to_j(previous))+.001
        anchors[index+1] = j_to_nits(target, lo, hi)
        yield f'tone_minimum_gap_{index}', base, replace(tone, input_nits=tuple(anchors), fit=2)

    # Simultaneous Midtones/White/Highlights minimum gaps are the strongest
    # measured scalar stress within the accepted Tone Fit 2 range.
    for previous in (100., 200., 249.):
        target = float(reference.nits_to_j(previous))
        white = j_to_nits(target+.001, 10., 1000.)
        highlights = j_to_nits(target+.002, 100., 10000.)
        anchors = (0., 5., previous, white, highlights)
        yield f'tone_joint_minimum_gap_{previous:g}', base, replace(tone, input_nits=anchors, fit=2)


def samples(count=1024):
    """Finite float32 pixels with explicit black/neutral/HDR/sign edge cases."""
    rng = np.random.default_rng(20261027)
    values = rng.uniform(-1, 1, (count, 3)) * 10**rng.uniform(-8, np.log10(1024), (count, 1))
    levels = np.r_[0., np.geomspace(1e-8, 1024., 20)]
    rays = np.array(((1,1,1),(-1,-1,-1),(1,0,0),(0,1,0),(0,0,1),
                     (1,1,0),(0,1,1),(1,0,1),(-.1,.3,1),(1,-.2,.01)), float)
    explicit = (levels[:,None,None]*rays[None,:,:]).reshape(-1,3)
    values[:min(len(explicit),count)] = explicit[:count]
    if count > len(explicit)+6:
        values[len(explicit):len(explicit)+6] = [[.18,.18,.18+1e-7],[1,1-1e-6,1],
                                                [1024,1024,1023.999],[-1024,1024,0],
                                                [1e-30,0,-1e-30],[0,0,0]]
    return values.astype(np.float32)


def rgba(count=1024):
    values = samples(count)
    alpha = np.linspace(0., 1., count, dtype=np.float32)
    return np.column_stack((values, alpha))

"""Portable, reference-schema settings for the native forward experiment."""
from dataclasses import dataclass, field

LOW_Y = 0.015507796089266005
D65 = (.3127, .329)
SPACES = ('Linear Rec.709', 'Linear Rec.2020', 'ACEScg')
ZERO44 = ((0.,) * 4,) * 4
ZERO46 = ((0.,) * 6,) * 4
ZERO42 = ((0., 0.),) * 4


@dataclass(frozen=True)
class LinearSettings:
    """Linear controls in the reference convention (balance gain is 2**-balance)."""
    exposure: float = 0.
    source_xy: tuple = D65
    balance: tuple = (0., 0.)
    spread: tuple = (0., 0.)
    heading: tuple = (0., 0.)
    matrix: tuple | None = None

    def __post_init__(self):
        for name in ('source_xy', 'balance', 'spread', 'heading'):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if self.matrix is not None:
            object.__setattr__(self, 'matrix', tuple(tuple(row) for row in self.matrix))


@dataclass(frozen=True)
class ToneSettings:
    """Reference-schema controls; preparation accepts Tone Fit in [-2, 2]."""
    input_nits: tuple = (0., LOW_Y*203., .18*203., 203., 1000.)
    fit: float = 0.
    reference_nits: float = 203.
    peak_nits: float = 1000.

    def __post_init__(self):
        object.__setattr__(self, 'input_nits', tuple(self.input_nits))


@dataclass(frozen=True)
class WebSettings:
    """Four tonal rows of six cyclic Rec.709 hue/chroma/scale handles."""
    log_chroma: tuple = ZERO46
    hue_degrees: tuple = ZERO46
    log_scale: tuple = ZERO46

    def __post_init__(self):
        for name in ('log_chroma', 'hue_degrees', 'log_scale'):
            object.__setattr__(self, name, tuple(tuple(row) for row in getattr(self, name)))

    @property
    def active(self):
        return any(value != 0 for name in ('log_chroma', 'hue_degrees', 'log_scale')
                   for row in getattr(self, name) for value in row)


@dataclass(frozen=True)
class ColorSettings:
    """Reference Color schema; columns are low/high chroma and a/b opponents."""
    lightness: tuple = ZERO44
    chroma: tuple = ZERO44
    adaptance: tuple = ZERO42
    lightness_fit: float = 0.
    chroma_fit: float = 0.
    global_gain: float = 0.
    adaptance_half_saturation: float = .25
    web: WebSettings = field(default_factory=WebSettings)

    def __post_init__(self):
        for name in ('lightness', 'chroma', 'adaptance'):
            object.__setattr__(self, name, tuple(tuple(row) for row in getattr(self, name)))
        if isinstance(self.web, dict):
            object.__setattr__(self, 'web', WebSettings(**self.web))
        if not isinstance(self.web, WebSettings):
            raise ValueError('web must be WebSettings or a web settings object')


@dataclass(frozen=True)
class Settings:
    """Convenient portable aggregate; no Blender or UI state is retained."""
    linear: LinearSettings = field(default_factory=LinearSettings)
    tone: ToneSettings = field(default_factory=ToneSettings)
    space: str = 'Linear Rec.709'
    color: ColorSettings = field(default_factory=ColorSettings)

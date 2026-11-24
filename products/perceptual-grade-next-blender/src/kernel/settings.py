"""Portable, reference-schema settings for the native forward experiment."""
from dataclasses import dataclass, field

LOW_Y = 0.015507796089266005
D65 = (.3127, .329)
SPACES = ('Linear Rec.709', 'Linear Rec.2020', 'ACEScg')
TONE_PEAKS = (500, 1000, 2000, 4000)
TONE_CHROMA_LIMITS = {
    'black_compression_nits': (0., 2.), 'muted_gain': (-2., 2.),
    'vivid_gain': (-2., 2.), 'saturation_crossover': (.05, .95),
    'shadow_chroma': (-2., 2.), 'highlight_chroma': (-2., 2.),
    'tone_crossover': (10., 160.),
}
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
    """Original Unified Chroma Tone and chroma controls."""
    input_nits: tuple = (LOW_Y*203., .18*203., 203., 1000.)
    fit: float = 0.
    reference_nits: float = 203.
    peak_nits: float = 1000.
    black_compression_nits: float = 0.
    muted_gain: float = 0.
    vivid_gain: float = 0.
    saturation_crossover: float = .5
    shadow_chroma: float = 0.
    highlight_chroma: float = 0.
    tone_crossover: float = 45.

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
    """Stage 3 Warp settings. Tonal J/C drivers belong to Stage 2 Tone."""
    adaptance: tuple = ZERO42
    adaptance_half_saturation: float = .25
    web: WebSettings = field(default_factory=WebSettings)

    def __post_init__(self):
        object.__setattr__(self, 'adaptance', tuple(tuple(row) for row in self.adaptance))
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


@dataclass(frozen=True)
class StackEntrySettings:
    settings: Settings
    direction: str = "FORWARD"


def split_stack_entries(entries):
    """Bare Grade settings are the original, all-forward Stack input."""
    entries = tuple(StackEntrySettings(item) if isinstance(item, Settings) else item
                    for item in entries)
    return tuple(item.settings for item in entries), tuple(item.direction for item in entries)


def stack_directions(count, directions=None):
    if directions is None:
        return ("FORWARD",) * count
    if not isinstance(directions, (tuple, list)) or len(directions) != count:
        raise ValueError("Stack directions must match the number of Grades")
    if any(item not in ("FORWARD", "INVERSE") for item in directions):
        raise ValueError("Stack directions must be FORWARD or INVERSE")
    return tuple(directions)

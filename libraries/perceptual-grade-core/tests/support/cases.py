"""Small deterministic inputs shared by numerical and device contracts."""
import numpy as np
from color_tools.perceptual_grade_core.model import color, linear, tone, transforms


def samples():
    rng = np.random.default_rng(122065)
    return np.vstack((rng.uniform(.05, 1, (48, 3)) * 10**rng.uniform(-4, 1.5, (48, 1)),
                      np.geomspace(1e-8, 128, 16)[:, None] * np.ones((1, 3)),
                      [[0, 0, 0], [-.1, .3, 2], [.1, -.03, .5], [.3, .1, -.02], [-.1, -.1, -.1]]))


def parameters(space='Linear Rec.709'):
    return (linear.neutral_parameters(space),
            tone.Parameters(input_midtones=40, input_white=235, input_highlights=1150),
            color.Parameters(global_gain=.2, web_hue_1_0=5, web_hue_2_4=-4,
                             web_chroma_2_1=.06, web_scale_1_2=.025, j_high_1=-2, c_high_2=.1,
                             adaptance_a_1=.4, adaptance_b_2=-.25))


def stack(space='Linear Rec.709'):
    lp, tp, cp = parameters(space)
    settings = transforms.Settings.from_parameters(lp, tp, cp, space)
    return transforms.Stack([settings], space)

"""Create a detached full native grade; run with the component available in Blender."""
from color_tools.perceptual_grade_nodes import (
    LinearSettings, ToneSettings, ColorSettings, WebSettings, prepare,
)
from color_tools.perceptual_grade_nodes.graph import build_group


def build_example(tree_type='ShaderNodeTree'):
    prepared = prepare(
        LinearSettings(exposure=.7, balance=(.15, -.12)),
        ToneSettings(input_nits=(0., 8., 40., 235., 1150.)),
        color=ColorSettings(
            lightness=((2., -3., 1., -.5), (3., 2., -1., .5),
                       (-2., 4., .5, -1.), (1., -2., 1., .5)),
            global_gain=.2, adaptance=((2., -1.), (-1., 2.), (3., 1.), (-2., -1.)),
            web=WebSettings(log_chroma=((.1, -.1, .05, 0., -.05, .1),)*4),
        ),
    )
    built = build_group(prepared, tree_type, name='Full native Grade example')
    print('Detached group:', built.tree.name, 'expanded nodes:', built.stats.expanded_nodes)
    print('Packed helper bytes:', built.stats.texture_bytes)
    print('Connect and retain built.tree before saving; dispose after removing its users.')
    return built


if __name__ == '__main__':
    built = build_example()

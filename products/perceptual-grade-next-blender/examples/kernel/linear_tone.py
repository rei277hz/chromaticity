"""Create one detached native group in a host with this component on sys.path.

No active scene, material, compositor, render settings, or user data is replaced.
The returned BuiltGrade owns the new group and its packed coefficient image.
"""
from color_tools.kernel import LinearSettings, ToneSettings, prepare
from color_tools.kernel.graph import build_group


def build_example(tree_type='ShaderNodeTree'):
    prepared = prepare(
        linear=LinearSettings(exposure=.7, source_xy=(.34, .36),
                              balance=(.15, -.12), spread=(20., -15.), heading=(8., -12.)),
        tone=ToneSettings(input_nits=(0., 8., 40., 235., 1150.), fit=0., peak_nits=1000.),
        space='Linear Rec.709',
    )
    built = build_group(prepared, tree_type, name='Raw Linear + Tone example', export=False)
    print('Created detached group:', built.tree.name)
    print('Expanded nodes:', built.stats.expanded_nodes)
    print('Coefficient images owned by this result:', [image.name for image in built.images])
    print('Connect built.tree to a native group node before saving it in a project.')
    print('After removing its users, call built.dispose() to release the owned resources.')
    return built


if __name__ == '__main__':
    # Use 'CompositorNodeTree' to create the corresponding compositor group.
    built = build_example()

load("@prelude//:prelude.bzl", "native")

def python_tool(name, main_module, srcs, deps = []):
    native.python_library(name = name + "_sources", srcs = srcs, base_module = "", deps = deps)
    native.python_binary(name = name, main_module = main_module, deps = [":" + name + "_sources"])

def _tree_impl(ctx):
    return [DefaultInfo(default_output = ctx.actions.copied_dir("tree", ctx.attrs.srcs))]

source_tree = rule(
    impl = _tree_impl,
    attrs = {"srcs": attrs.dict(attrs.string(), attrs.source())},
)

def _generate_impl(ctx):
    output = ctx.actions.declare_output("output", dir = True)
    ctx.actions.run(
        cmd_args(ctx.attrs.tool[RunInfo], ctx.attrs.args, "--output-dir", output.as_output()),
        category = "generate",
        identifier = ctx.label.name,
    )
    return [DefaultInfo(
        default_output = output,
        sub_targets = {name: [DefaultInfo(default_output = output.project(path))] for name, path in ctx.attrs.outputs.items()},
    )]

generate = rule(
    impl = _generate_impl,
    attrs = {
        "tool": attrs.exec_dep(providers = [RunInfo]),
        "args": attrs.list(attrs.arg(), default = []),
        "outputs": attrs.dict(attrs.string(), attrs.string()),
    },
)

def _verification_group_impl(ctx):
    reports = {}
    for index, dependency in enumerate(ctx.attrs.deps):
        for output in dependency[DefaultInfo].default_outputs:
            reports[str(index)] = output
    return [DefaultInfo(default_output = ctx.actions.copied_dir("reports", reports))]

verification_group = rule(
    impl = _verification_group_impl,
    attrs = {"deps": attrs.list(attrs.dep())},
)

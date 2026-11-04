"""Deterministic book generation with required named output files."""

def _generate_impl(ctx):
    output = ctx.actions.declare_output("output", dir = True)
    expected = cmd_args()
    for path in sorted(ctx.attrs.outputs.values()):
        expected.add("--expected-output", path)
    ctx.actions.run(
        cmd_args(
            ctx.attrs._validator[RunInfo],
            "--output-dir",
            output.as_output(),
            expected,
            "--",
            ctx.attrs.tool[RunInfo],
            ctx.attrs.args,
        ),
        category = "book_generate",
        identifier = ctx.label.name,
        env = {
            "PG_BUCK_ACTION": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONHASHSEED": "0",
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "SOURCE_DATE_EPOCH": "315532800",
        },
    )
    return [DefaultInfo(
        default_output = output,
        sub_targets = {name: [DefaultInfo(default_output = output.project(path))] for name, path in ctx.attrs.outputs.items()},
    )]

book_generate = rule(
    impl = _generate_impl,
    attrs = {
        "tool": attrs.exec_dep(providers = [RunInfo]),
        "args": attrs.list(attrs.arg(), default = []),
        "outputs": attrs.dict(attrs.string(), attrs.string()),
        "_validator": attrs.default_only(attrs.exec_dep(default = "root//products/perceptual-grade-book/generators:action", providers = [RunInfo])),
    },
)

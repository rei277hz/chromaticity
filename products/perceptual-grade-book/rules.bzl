"""The legacy renderer's declared executable and input closure."""

def _documentation_impl(ctx):
    output = ctx.actions.declare_output("output", dir = True)
    ctx.actions.run(
        cmd_args(
            ctx.attrs.tool[RunInfo],
            "--mdbook",
            ctx.attrs.mdbook[RunInfo],
            "--book",
            ctx.attrs.book,
            "--pins",
            ctx.attrs.pins,
            "--rust-versions",
            ctx.attrs.rust_versions,
            "--output-dir",
            output.as_output(),
        ),
        category = "pg_documentation",
        env = {
            "PG_BUCK_ACTION": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "SOURCE_DATE_EPOCH": "315532800",
        },
    )
    return [DefaultInfo(default_output = output, sub_targets = {
        "html": [DefaultInfo(default_output = output.project("site"))],
        "manifest": [DefaultInfo(default_output = output.project("site-manifest.json"))],
    })]

documentation = rule(
    impl = _documentation_impl,
    attrs = {
        "tool": attrs.exec_dep(providers = [RunInfo]),
        "mdbook": attrs.exec_dep(providers = [RunInfo]),
        "book": attrs.source(allow_directory = True),
        "pins": attrs.source(),
        "rust_versions": attrs.source(),
    },
)

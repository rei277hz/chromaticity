"""Build-time verification of the book's pinned browser CDN dependencies."""

def _cdn_assets_impl(ctx):
    output = ctx.actions.declare_output("output", dir = True)
    ctx.actions.run(
        cmd_args(
            ctx.attrs.tool[RunInfo],
            "--pins",
            ctx.attrs.pins,
            "--sources",
            ctx.attrs.sources,
            "--output-dir",
            output.as_output(),
        ),
        category = "book_cdn",
        env = {"PG_BUCK_ACTION": "1", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return [DefaultInfo(default_output = output)]

cdn_assets = rule(
    impl = _cdn_assets_impl,
    attrs = {
        "pins": attrs.source(),
        "sources": attrs.source(allow_directory = True),
        "tool": attrs.exec_dep(providers = [RunInfo]),
    },
)

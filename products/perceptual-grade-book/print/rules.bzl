def _book_exports_impl(ctx):
    output = ctx.actions.declare_output("output", dir = True)
    ctx.actions.run(
        cmd_args(
            ctx.attrs.tool[RunInfo],
            "--site",
            ctx.attrs.site,
            "--book",
            ctx.attrs.book,
            "--publication",
            ctx.attrs.publication,
            "--site-prefix",
            ctx.attrs.site_prefix,
            cmd_args([["--language", language] for language in ctx.attrs.languages]),
            "--front-matter",
            ctx.attrs.front_matter,
            "--theme",
            ctx.attrs.theme,
            "--katex-js",
            ctx.attrs.katex_js,
            "--katex-css",
            ctx.attrs.katex_css,
            "--katex-package",
            ctx.attrs.katex_package,
            "--font-sans",
            ctx.attrs.font_sans,
            "--font-mono",
            ctx.attrs.font_mono,
            "--font-sans-license",
            ctx.attrs.font_sans_license,
            "--font-mono-license",
            ctx.attrs.font_mono_license,
            "--noto-package",
            ctx.attrs.noto_package,
            "--pdf-fonts",
            ctx.attrs.pdf_fonts,
            "--node",
            ctx.attrs.node,
            "--math-renderer",
            ctx.attrs.math_renderer,
            "--versions",
            ctx.attrs.versions,
            "--native-runtime",
            ctx.attrs.native_runtime,
            "--output-dir",
            output.as_output(),
        ),
        category = "pg_book_exports",
        env = {
            "PG_BUCK_ACTION": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "SOURCE_DATE_EPOCH": "315532800",
            "PG_BOOK_NATIVE_RUNTIME": ctx.attrs.native_runtime,
            "PAR_APPEND_LD_LIBRARY_PATH": cmd_args(ctx.attrs.native_runtime, "/usr/lib/x86_64-linux-gnu", delimiter = ""),
            "LD_LIBRARY_PATH": cmd_args(ctx.attrs.native_runtime, "/usr/lib/x86_64-linux-gnu", delimiter = ""),
            "FONTCONFIG_PATH": cmd_args(ctx.attrs.native_runtime, "/etc/fonts", delimiter = ""),
        },
    )
    return [DefaultInfo(
        default_output = output,
        sub_targets = {
            "pdf": [DefaultInfo(default_output = output.project("pdf"))],
            "epub": [DefaultInfo(default_output = output.project("epub"))],
            "documents": [DefaultInfo(default_output = output.project("documents"))],
            "manifest": [DefaultInfo(default_output = output.project("print-manifest.json"))],
        },
    )]

book_exports = rule(
    impl = _book_exports_impl,
    attrs = {
        "tool": attrs.exec_dep(providers = [RunInfo]),
        "site": attrs.source(allow_directory = True),
        "book": attrs.source(allow_directory = True),
        "publication": attrs.string(),
        "site_prefix": attrs.string(),
        "languages": attrs.list(attrs.string()),
        "front_matter": attrs.source(allow_directory = True),
        "theme": attrs.source(allow_directory = True),
        "katex_js": attrs.source(),
        "katex_css": attrs.source(),
        "katex_package": attrs.source(),
        "font_sans": attrs.source(),
        "font_mono": attrs.source(),
        "font_sans_license": attrs.source(),
        "font_mono_license": attrs.source(),
        "noto_package": attrs.source(),
        "pdf_fonts": attrs.source(allow_directory = True),
        "node": attrs.source(),
        "math_renderer": attrs.source(),
        "versions": attrs.source(),
        "native_runtime": attrs.source(allow_directory = True),
    },
)

def _chart_preview_impl(ctx):
    output = ctx.actions.declare_output("output", dir = True)
    options = cmd_args()
    if ctx.attrs.policy_manifest != None:
        options.add("--policy-manifest", ctx.attrs.policy_manifest, "--fonts", ctx.attrs.fonts)
    ctx.actions.run(
        cmd_args(ctx.attrs.tool[RunInfo], "--figures", ctx.attrs.figures, "--output-dir", output.as_output(), options),
        category = "pg_book_chart_preview",
        env = {
            "PG_BUCK_ACTION": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "SOURCE_DATE_EPOCH": "315532800",
            "PG_BOOK_NATIVE_RUNTIME": ctx.attrs.native_runtime,
            "PAR_APPEND_LD_LIBRARY_PATH": cmd_args(ctx.attrs.native_runtime, "/usr/lib/x86_64-linux-gnu", delimiter = ""),
            "LD_LIBRARY_PATH": cmd_args(ctx.attrs.native_runtime, "/usr/lib/x86_64-linux-gnu", delimiter = ""),
            "FONTCONFIG_PATH": cmd_args(ctx.attrs.native_runtime, "/etc/fonts", delimiter = ""),
        },
    )
    return [DefaultInfo(
        default_output = output,
        sub_targets = {name: [DefaultInfo(default_output = output.project(path))] for name, path in {
            "pdf": "chart-preview.pdf", "images": "pages", "manifest": "preview.json",
        }.items()},
    )]

chart_preview = rule(
    impl = _chart_preview_impl,
    attrs = {
        "tool": attrs.exec_dep(providers = [RunInfo]),
        "figures": attrs.source(allow_directory = True),
        "native_runtime": attrs.source(allow_directory = True),
        "policy_manifest": attrs.option(attrs.source(), default = None),
        "fonts": attrs.option(attrs.source(allow_directory = True), default = None),
    },
)

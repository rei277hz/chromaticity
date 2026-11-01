"""Rust distribution and web packaging rules, leaving compilation to the prelude."""

load("@prelude//rust:sources.bzl", "RustSources")

def _wasm_transition_impl(platform, refs):
    constraints = dict(platform.configuration.constraints)
    for value in [refs.cpu[ConstraintValueInfo], refs.os[ConstraintValueInfo]]:
        constraints[value.setting.label] = value
    return PlatformInfo(
        label = "wasm32-unknown-unknown",
        configuration = ConfigurationInfo(constraints = constraints, values = platform.configuration.values),
    )

_wasm_transition = transition(
    impl = _wasm_transition_impl,
    refs = {"cpu": "prelude//cpu/constraints:cpu[wasm32]", "os": "prelude//os/constraints:os[none]"},
)

def _rust_distribution_impl(ctx):
    output = ctx.actions.declare_output("sysroot", dir = True)
    command = cmd_args(ctx.attrs._builder[RunInfo], "distribution", "--output", output.as_output())
    for component, archive in ctx.attrs.archives.items():
        command.add("--component", component, archive)
    ctx.actions.run(command, category = "rust_distribution")
    tools = {
        "rustc": "bin/rustc",
        "cargo": "bin/cargo",
        "rustdoc": "bin/rustdoc",
        "clippy": "bin/clippy-driver",
        "wasm_ld": "lib/rustlib/" + ctx.attrs.host + "/bin/gcc-ld/wasm-ld",
        "rust_lld": "lib/rustlib/" + ctx.attrs.host + "/bin/rust-lld",
    }
    return [DefaultInfo(default_output = output, sub_targets = {
        name: [DefaultInfo(default_output = output.project(path)), RunInfo(args = cmd_args(output.project(path), hidden = [output]))]
        for name, path in tools.items()
    })]

rust_distribution = rule(impl = _rust_distribution_impl, attrs = {
    "host": attrs.string(),
    "archives": attrs.dict(attrs.string(), attrs.source()),
    "_builder": attrs.exec_dep(default = "root//tools/rust-build:builder", providers = [RunInfo]),
})

def _wasm_package_impl(ctx):
    output = ctx.actions.declare_output("package", dir = True)
    library = ctx.attrs.library[DefaultInfo].default_outputs[0]
    ctx.actions.run(
        cmd_args(
            ctx.attrs._builder[RunInfo],
            "bindgen",
            "--bindgen",
            ctx.attrs._bindgen[RunInfo],
            "--wasm",
            library,
            "--name",
            ctx.attrs.crate,
            "--output",
            output.as_output(),
        ),
        category = "wasm_bindgen",
    )
    return [DefaultInfo(default_output = output, sub_targets = {
        "js": [DefaultInfo(default_output = output.project(ctx.attrs.crate + ".js"))],
        "wasm": [DefaultInfo(default_output = output.project(ctx.attrs.crate + "_bg.wasm"))],
    })]

wasm_package = rule(impl = _wasm_package_impl, attrs = {
    "library": attrs.transition_dep(cfg = _wasm_transition),
    "crate": attrs.string(),
    "_builder": attrs.exec_dep(default = "root//tools/rust-build:builder", providers = [RunInfo]),
    "_bindgen": attrs.exec_dep(default = "root//third_party/rust:wasm-bindgen-cli-wasm-bindgen", providers = [RunInfo]),
})

def _rust_notices_impl(ctx):
    output = ctx.actions.declare_output("rust-notices.txt")
    ctx.actions.run(
        cmd_args(
            ctx.attrs._builder[RunInfo],
            "notices",
            "--output",
            output.as_output(),
            ctx.attrs.library[RustSources].tset.project_as_args("artifacts"),
        ),
        category = "rust_notices",
    )
    return [DefaultInfo(default_output = output)]

rust_notices = rule(impl = _rust_notices_impl, attrs = {
    "library": attrs.transition_dep(cfg = _wasm_transition, providers = [RustSources]),
    "_builder": attrs.exec_dep(default = "root//tools/rust-build:builder", providers = [RunInfo]),
})

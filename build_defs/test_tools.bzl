load("@prelude//cxx:cxx_toolchain_types.bzl", "CxxToolchainInfo")

def _compilers_impl(ctx):
    toolchain = ctx.attrs.toolchain[CxxToolchainInfo]
    output = ctx.actions.write_json("compilers.json", {
        "cl": cmd_args(toolchain.c_compiler_info.compiler),
        "cpp": cmd_args(toolchain.cxx_compiler_info.compiler),
    })

    # The JSON contains paths, so preserve their artifacts in the test's input
    # closure even though the test accesses those paths only at runtime.
    return [DefaultInfo(default_output = output, other_outputs = [
        cmd_args(toolchain.c_compiler_info.compiler),
        cmd_args(toolchain.cxx_compiler_info.compiler),
    ])]

compilers = rule(impl = _compilers_impl, attrs = {
    "toolchain": attrs.toolchain_dep(providers = [CxxToolchainInfo]),
})

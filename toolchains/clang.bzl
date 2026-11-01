load("@prelude//cxx:cxx_toolchain_types.bzl", "LinkerType")
load("@prelude//toolchains:cxx.bzl", "CxxToolsInfo")

def _clang_tools_impl(ctx):
    lean = ctx.attrs.lean[DefaultInfo].default_outputs[0]
    headers = ctx.actions.copied_dir("opencl", ctx.attrs.headers)

    # Clang/LLVM load sibling shared libraries and invoke sibling tools from the
    # pinned distribution. Keep that runtime closure when actions run remotely.
    compiler = cmd_args(lean.project("bin/clang"), "-isystem", lean.project("include/clang"), "-isystem", headers, hidden = [lean])
    cxx = cmd_args(compiler, "--driver-mode=g++")
    return [DefaultInfo(), CxxToolsInfo(
        compiler = compiler,
        cxx_compiler = cxx,
        compiler_type = "clang",
        asm_compiler = compiler,
        asm_compiler_type = "clang",
        archiver = cmd_args(lean.project("bin/llvm-ar"), hidden = [lean]),
        archiver_type = "gnu",
        linker = cmd_args(cxx, "-fuse-ld=lld"),
        linker_type = LinkerType(ctx.attrs.linker_type),
    )]

clang_tools = rule(impl = _clang_tools_impl, attrs = {
    "lean": attrs.exec_dep(default = "root//tools/verification:lean"),
    "headers": attrs.dict(attrs.string(), attrs.source()),
    "linker_type": attrs.string(default = select({"prelude//os:linux": "gnu", "prelude//os:macos": "darwin"})),
})

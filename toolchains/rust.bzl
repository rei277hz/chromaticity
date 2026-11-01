"""Pinned Rust compiler and the CXX linker metadata needed for wasm cdylibs."""

load("@prelude//cxx:cxx_toolchain_types.bzl", "CxxToolchainInfo", "LinkerInfo", "LinkerType", "ShlibInterfacesMode", "cxx_toolchain_infos")
load("@prelude//linking:link_info.bzl", "LinkStyle")
load("@prelude//linking:lto.bzl", "LtoMode")
load("@prelude//rust:rust_toolchain.bzl", "PanicRuntime", "RustToolchainInfo")

def _pinned_rust_toolchain_impl(ctx):
    sysroot = ctx.attrs.distribution[DefaultInfo].default_outputs[0]
    flags = ["-Copt-level=3", "-Cdebuginfo=0", "-Cdebug-assertions=no", "--remap-path-prefix=.=/build"]
    wasm = ctx.attrs.target_triple == "wasm32-unknown-unknown"
    if wasm:
        # Prelude uses PIC for cdylib; wasm-bindgen needs Rust's normal static
        # wasm relocation model, including for rlibs consumed by that cdylib.
        flags.append("-Crelocation-model=static")
    return [DefaultInfo(), RustToolchainInfo(
        compiler = RunInfo(args = cmd_args(sysroot.project("bin/rustc"), hidden = [sysroot])),
        clippy_driver = RunInfo(args = cmd_args(sysroot.project("bin/clippy-driver"), hidden = [sysroot])),
        rustdoc = RunInfo(args = cmd_args(sysroot.project("bin/rustdoc"), hidden = [sysroot])),
        sysroot_path = sysroot,
        rustc_target_triple = ctx.attrs.target_triple,
        default_edition = "2021",
        rustc_flags = flags,
        panic_runtime = PanicRuntime("abort" if wasm else "unwind"),
        nightly_features = False,
        advanced_unstable_linking = False,
        doctests = False,
    )]

pinned_rust_toolchain = rule(
    impl = _pinned_rust_toolchain_impl,
    attrs = {
        "distribution": attrs.exec_dep(default = "root//tools/rust-build:distribution"),
        "target_triple": attrs.string(default = select({
            "prelude//cpu:wasm32": "wasm32-unknown-unknown",
            "prelude//os:linux": "x86_64-unknown-linux-gnu",
            "prelude//os:macos": "aarch64-apple-darwin",
        })),
    },
    is_toolchain_rule = True,
)

def _wasm_cxx_toolchain_impl(ctx):
    base = ctx.attrs.base[CxxToolchainInfo]
    linker = LinkerInfo(
        type = LinkerType("wasm"),
        linker = ctx.attrs.linker[RunInfo],
        linker_flags = [],
        post_linker_flags = [],
        archiver = base.linker_info.archiver,
        archiver_type = base.linker_info.archiver_type,
        archiver_supports_argfiles = True,
        archive_objects_locally = False,
        use_archiver_flags = True,
        binary_extension = "wasm",
        object_file_extension = "o",
        static_library_extension = "a",
        shared_library_name_default_prefix = "",
        shared_library_name_format = "{}.wasm",
        shared_library_versioned_name_format = "{}.wasm",
        link_binaries_locally = False,
        link_libraries_locally = False,
        lto_mode = LtoMode("none"),
        link_style = LinkStyle("static"),
        shlib_interfaces = ShlibInterfacesMode("disabled"),
        shared_dep_runtime_ld_flags = [],
        static_dep_runtime_ld_flags = [],
        static_pic_dep_runtime_ld_flags = [],
        independent_shlib_interface_linker_flags = [],
        generate_linker_maps = False,
        is_pdb_generated = False,
    )
    return [DefaultInfo()] + cxx_toolchain_infos(
        platform_name = "wasm32-unknown-unknown",
        c_compiler_info = base.c_compiler_info,
        cxx_compiler_info = base.cxx_compiler_info,
        binary_utilities_info = base.binary_utilities_info,
        header_mode = base.header_mode,
        internal_tools = base.internal_tools,
        linker_info = linker,
    )

wasm_cxx_toolchain = rule(
    impl = _wasm_cxx_toolchain_impl,
    attrs = {
        "base": attrs.toolchain_dep(default = "toolchains//:native_cxx", providers = [CxxToolchainInfo]),
        # rustc supplies '-flavor wasm' to the prelude's linker wrapper. Invoke
        # the generic driver, since wasm-ld would add that dispatch a second time.
        "linker": attrs.exec_dep(default = "root//tools/rust-build:distribution[rust_lld]", providers = [RunInfo]),
    },
    is_toolchain_rule = True,
)

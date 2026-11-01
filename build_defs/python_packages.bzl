"""Normal Python dependencies and intact, privately bundled package closures."""

load("@prelude//:prelude.bzl", "native")

PackageInfo = provider(fields = {"files": provider_field(dict), "owners": provider_field(dict), "package": provider_field(str), "packages": provider_field(dict)})

def _merge(files, owners, incoming, incoming_owners):
    for path, artifact in incoming.items():
        if path in files and (owners[path] != incoming_owners[path] or files[path] != artifact):
            fail("Conflicting Python package destination: " + path)
        files[path] = artifact
        owners[path] = incoming_owners[path]

def _merge_packages(packages, incoming):
    for name, spec in incoming.items():
        if name in packages:
            previous = packages[name]
            if previous["owner"] != spec["owner"]:
                fail("Conflicting Python component owner: " + name)

            # One library may split code and generated data to avoid a generator
            # dependency cycle. Every file still has one canonical source owner.
            packages[name] = {
                "owner": spec["owner"],
                "dependencies": sorted({dep: True for dep in previous["dependencies"] + spec["dependencies"]}),
                "files": sorted({path: True for path in previous["files"] + spec["files"]}),
            }
        else:
            packages[name] = spec

def _component_impl(ctx):
    files, owners, packages = {}, {}, {}
    for dependency in ctx.attrs.deps:
        info = dependency[PackageInfo]
        _merge(files, owners, info.files, info.owners)
        _merge_packages(packages, info.packages)
    own = {ctx.attrs.package + "/" + path: source for path, source in ctx.attrs.srcs.items()}
    _merge(files, owners, own, {path: str(ctx.label) for path in own})
    output = ctx.actions.copied_dir("packages", files)
    _merge_packages(packages, {ctx.attrs.package: {
        "owner": str(ctx.label).split(":")[0],
        "dependencies": [
            dependency[PackageInfo].package
            for dependency in ctx.attrs.deps
            if dependency[PackageInfo].package != ctx.attrs.package
        ],
        "files": sorted(ctx.attrs.srcs.keys()),
    }})
    manifest = ctx.actions.write_json("components.json", packages)
    return [
        DefaultInfo(default_output = output, sub_targets = {"manifest": [DefaultInfo(default_output = manifest)]}),
        PackageInfo(files = files, owners = owners, package = ctx.attrs.package, packages = packages),
    ]

_component = rule(impl = _component_impl, attrs = {
    "package": attrs.string(),
    "srcs": attrs.dict(attrs.string(), attrs.source()),
    "deps": attrs.list(attrs.dep(providers = [PackageInfo]), default = []),
})

def component_library(name, package, srcs, resources = {}, deps = [], external_deps = [], visibility = ["PUBLIC"]):
    """Declare one source owner; internal deps are component_library labels."""
    native.python_library(
        name = name,
        base_module = "color_tools." + package,
        srcs = srcs,
        resources = resources,
        deps = deps + external_deps,
        visibility = visibility,
    )
    files = dict(srcs)
    for path, source in resources.items():
        if path in files:
            fail("Resource shadows Python source: " + path)
        files[path] = source
    _component(
        name = name + "_bundle",
        package = package,
        srcs = files,
        deps = [label + "_bundle" for label in deps],
        visibility = visibility,
    )

def _extension_tree_impl(ctx):
    files, owners, packages = {}, {}, {}
    for dependency in ctx.attrs.deps:
        info = dependency[PackageInfo]
        _merge(files, owners, info.files, info.owners)
        _merge_packages(packages, info.packages)
    installed = dict(files)
    for path, source in ctx.attrs.entrypoints.items():
        if path in installed:
            fail("Product entrypoint shadows dependency: " + path)
        installed[path] = source
    output = ctx.actions.copied_dir("tree", installed)
    return [DefaultInfo(default_output = output)]

extension_tree = rule(impl = _extension_tree_impl, attrs = {
    "deps": attrs.list(attrs.dep(providers = [PackageInfo])),
    "entrypoints": attrs.dict(attrs.string(), attrs.source()),
})

# Component libraries and packaging

`build_defs/` owns the Buck rules that assemble declared sources, dependencies,
generated resources, and product artifacts. This guide describes the shared
Python component model implemented in [python_packages.bzl](python_packages.bzl).
Product build and installation commands live in each product's README; the
[repository guide](../README.md) links all products and libraries.

## Source ownership

A library owns reusable implementation and its tests. A product owns application
behavior, its entrypoint, packaging, and installed acceptance. Blender products
do not import, discover, register, or shut down one another. DCTL generation has
no Blender dependency.

The generic [Invariant framework](../libraries/invariant/README.md) has no Blender
capabilities. [Blender runtime](../libraries/blender-runtime/README.md) owns common
host services, while components with workflow policies use the shared typed
runtime and keep those policies pure. Host independence permits process or
filesystem I/O; purity is a separate requirement of policy modules and designated
mathematical models.

The [architecture gate](../tools/verification/README.md) checks declared direct
dependencies, relocatable imports, product isolation, and the absence of native
or product dependencies in mathematical packages.

## Buck component dependencies

`component_library` declares a normal Buck `python_library` in the development
namespace `color_tools.<component>`. It also creates a `<target>_bundle` target
with the complete component dependency closure; a target named `runtime`
therefore has a `runtime_bundle`. Internal `deps` identify component libraries;
`external_deps` supply ordinary Python dependencies such as NumPy.

Source and resource files retain their owner and package-relative destination.
The bundle merges intact packages and emits a `components.json` manifest of
owners, files, and direct dependencies. Conflicting owners or destinations and
resources shadowing Python sources are rejected. Code and generated resources
may use separate targets with the same component owner to avoid generator cycles.

Relative cross-component imports allow the identical source closure to relocate
under a private installed namespace. The repository is named chromaticity; its
existing Python development namespace remains `color_tools`.

```text
Development                            Installed extension (example)
color_tools.invariant                  bl_ext.repo.grade.invariant
color_tools.blender_runtime            bl_ext.repo.grade.blender_runtime
color_tools.perceptual_grade_core       bl_ext.repo.grade.perceptual_grade_core
color_tools.perceptual_grade_blender    bl_ext.repo.grade.perceptual_grade_blender
```

## Installed extension packages

`extension_tree` combines component bundles with product entrypoints and rejects
entrypoints that shadow dependency files. Each extension ZIP places intact
component packages directly beneath its root, next to the thin `__init__.py`
entrypoint and Blender manifest. In the preserved Grade product, physical `src/`
files form the `perceptual_grade_blender` package, and product `entrypoint.py`
becomes the ZIP's root `__init__.py`.

There is no source rewriting, `sys.path` overlay, or global application alias.
Separate ZIPs have separate Python module state and App domains. Blender supplies
NumPy at installation. Product resources, including runtime JSON where used,
remain explicitly inventoried.

Packaging compares the final archive's inventory and bytes with declared inputs
and rejects unsafe or conflicting paths. Preserved Grade and Picker packages
require applicable machine proof bundles bound to the shipped policies and
generated validators, plus the exact requirements, checker, and solver inputs.
Of the verification machinery, only generated contracts and their solver-free
evaluator enter the runtime; build and proof payloads remain outside the ZIP. See the
[archive integrity requirements](../tools/verification/README.md#archive-integrity).

Product-specific upgrade steps and data-format compatibility are documented in
the [Grade](../products/perceptual-grade-blender/README.md) and
[Picker](../products/hdr-color-picker-blender/README.md) READMEs. App identity,
Store isolation, and helper dependency handshakes are described in the
[Blender runtime guide](../libraries/blender-runtime/README.md).

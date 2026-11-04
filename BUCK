load("//build_defs:artifacts.bzl", "verification_group")

export_file(
    name = "documentation",
    src = "README.md",
    visibility = ["PUBLIC"],
)

alias(
    name = "perceptual_grade",
    actual = "//products/perceptual-grade-blender:extension",
    visibility = ["PUBLIC"],
)

alias(
    name = "perceptual_grade_next",
    actual = "//products/perceptual-grade-next-blender:extension",
    visibility = ["PUBLIC"],
)

alias(
    name = "hdr_color_picker",
    actual = "//products/hdr-color-picker-blender:extension",
    visibility = ["PUBLIC"],
)

alias(
    name = "dctl",
    actual = "//products/perceptual-grade-dctl:dctl",
    visibility = ["PUBLIC"],
)

alias(
    name = "perceptual_grade_book",
    actual = "//products/perceptual-grade-book:site",
    visibility = ["PUBLIC"],
)

alias(
    name = "hdr_color_picker_web",
    actual = "//products/hdr-color-picker-web:site",
    visibility = ["PUBLIC"],
)

# Retained color mathematics and all source-bound shared machine requirements.
verification_group(
    name = "verify",
    visibility = ["PUBLIC"],
    deps = [
        "//libraries/blender-runtime:verify",
        "//libraries/invariant:verify",
        "//libraries/perceptual-grade-reference/proofs:color_model",
        "//libraries/perceptual-grade-core/proofs:verify",
    ],
)

# Product-owned policies and the extension's delivery receipt.
verification_group(
    name = "verify_next",
    visibility = ["PUBLIC"],
    deps = [
        "//products/perceptual-grade-next-blender:extension",
        "//products/perceptual-grade-next-blender:verify_policies",
    ],
)

alias(
    name = "architecture",
    actual = ":documentation",
    visibility = ["PUBLIC"],
)

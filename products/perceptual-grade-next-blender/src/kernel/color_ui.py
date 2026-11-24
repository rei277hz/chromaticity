"""Shared Color control inventory for UI, animation, and bake freshness."""


COLOR_FIELDS = ("adaptance_half_saturation",) + tuple(
    f"adaptance_{axis}_{tone}"
    for tone in range(4)
    for axis in ("a", "b")
) + tuple(
    f"web_{family}_{tone}_{handle}"
    for family in ("chroma", "hue", "scale")
    for tone in range(4)
    for handle in range(6)
)
COLOR_DEFAULTS = {
    **{name: 0.0 for name in COLOR_FIELDS},
    "adaptance_half_saturation": 0.25,
}

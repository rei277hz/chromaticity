"""Generate the reference Rec.709 Warp geometry for each supported peak."""
import math

from color_tools.perceptual_grade_reference.grading import Color, ColorSettings, Tone, ToneSettings


def geometry_source(peaks, number):
    anchors = []
    corners = []
    for peak in peaks:
        tone = Tone(ToneSettings(peak_nits=peak))
        geometry = Color(ColorSettings(), tone).web.geometry
        anchors.append(", ".join(number(value) for value in geometry.anchors))
        corners.extend(
            ", ".join(f"{number(angle)}, {number(math.log(radius))}"
                      for angle, radius in zip(angle_row, radius_row))
            for angle_row, radius_row in zip(geometry.angles, geometry.radii)
        )

    anchor_rows = ",\n    ".join(anchors)
    corner_rows = ",\n    ".join(corners)
    return f"""// Reference Rec.709 rays solved at the output tonal anchors.
__CONSTANT__ float PG_WARP_ANCHORS[{len(peaks) * 4}] = {{
    {anchor_rows}
}};
__CONSTANT__ float PG_WARP_CORNERS[{len(peaks) * 48}] = {{
    {corner_rows}
}};
__DEVICE__ float pg_warp_anchor(int peakIndex, int row) {{
    return PG_WARP_ANCHORS[4 * peakIndex + row];
}}
__DEVICE__ float3 pg_warp_reference_corner(int peakIndex, int row, int handle) {{
    int index = 2 * (24 * peakIndex + 6 * row + handle);
    return make_float3(PG_WARP_CORNERS[index], PG_WARP_CORNERS[index + 1], 0.0f);
}}
"""

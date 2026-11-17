# Scene working spaces

Next uses a fixed D65 Grade reference white. The Linear panel displays
**Working White: D65** as a disabled value; it is not a Grade setting that can
be changed in this product version. The source-white xy controls remain
available for the creative Stage 1 correction.

The node adapts between the scene's RGB working space and its internal grading
coordinates. Supported Blender scene spaces are **Linear Rec.709**,
**Linear Rec.2020**, and **ACEScg**. Switching the scene space updates the
surrounding conversion matrices and causes the derived graph to reconcile. It
does not reinterpret the same numeric RGB triplet as the same color: Blender
must convert input RGB when colorimetrically equivalent values are intended.

Ordinary Grade nodes apply the Linear matrix before their native Tone/Color
graph. A Grade Stack samples the complete sequence in fixed linear ACEScg / ACES-white
coordinates, with scene conversion around the LUT. The LUT's sampling white is
an implementation boundary and does not change the Grade's fixed D65
appearance reference.

Changing a working space can require new graph data. If graph preparation or
recovery fails, Next shows a visible magenta result that preserves alpha and
blocks rendering until the current kernel is repaired. See [evaluation and
interpolation](https://rei277hz.github.io/perceptual-grade/technical/en/theory/lut.html) for the LUT coordinates and [Linear](linear.md)
for input decoding and Stage 1 controls.

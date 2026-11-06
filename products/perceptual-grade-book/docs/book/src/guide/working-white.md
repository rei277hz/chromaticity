# Choose a working white

**Working White belongs to the shared Grade** and always defaults to **D65**, including in an ACEScg project. It stays as selected when Blender’s working space changes. Open **Stage 1 in the sidebar** to change it. For a Stack, first click an enabled entry’s pencil. Every user of that Grade updates.

The choices match the DCTL presets: **D65, D60 daylight, ACES, D50, D55, D75, DCI white and Equal energy E**. Blender does not offer custom xy for this setting. ACES white and daylight D60 have slightly different coordinates and are separate choices.

## What the white means

The appearance model’s reference white describes the adaptation context used for grading. It is separate from the RGB primaries used to store the scene and from the white of the final display. D65 is a consistent default across projects; the extension does not infer it from the monitor, view transform or scene gamut.

For example, with **ACEScg scene data and a D65 Grade**, the extension converts scene RGB to XYZ and uses Bradford adaptation from ACES white to D65 before the three grading stages. It adapts the result back to ACES white and returns ACEScg RGB. Equal-channel scene neutrals reach the appearance model as D65 neutrals, rather than as unadapted ACES-white stimuli viewed against D65.

The node still grades **scene-linear values before Blender’s view transform**. Selecting D65 does not move grading after tone mapping or turn the node into a display-referred operation. It also does not override the creative white or display encoding chosen by an ACES Output Transform. A monitor’s white alone does not determine every upstream appearance-model white. ACES documents its [creative-white and display-encoding choices separately](https://docs.acescentral.com/system-components/output-transforms/parameters/).

Use the default D65 for a consistent grading context, or choose another preset deliberately. Judge the result through the intended view transform and display configuration.

## What changes when you switch

<table>
<thead>
<tr><th>Change</th><th>Result</th></tr>
</thead>
<tbody>
<tr><td>Blender’s scene working space</td><td>Scene adapters change. The shared Grade’s matrix, white and Tone/Color settings stay unchanged.</td></tr>
<tr><td>The Grade’s Working White</td><td>Stage 1 is expressed in the new white context. Its derived controls may change; its color correction is preserved. Tone/Color values stay unchanged, so their nonlinear appearance may change.</td></tr>
<tr><td>A Grade used in several nodes or Stacks</td><td>All users update. Make an independent Grade copy first when only one use should change.</td></tr>
</tbody>
</table>

Switching Blender’s working space preserves grading for **equivalent colors**, meaning that the input RGB values must also be converted by Blender. Reusing the same three numbers in a different RGB space describes a different color. Floating-point and interpolation precision still apply.

The extension stores Stage 1’s matrix with its reference white. Its Linear controls are derived editing views, rather than independently stored grading values. A singular or otherwise unrepresentable matrix can have approximate control readouts; the node indicates this and retains the actual matrix. Reset Linear restores the identity matrix.

## Three different uses of white

**Bradford** connects the scene and Grade white contexts and connects different whites in a Stack. Blender’s native scene-color conversion supplies the gamut and white adaptation at the scene boundary.

**Source White** remains a creative **CAT16** correction inside Stage 1. Matching Source White to the Grade’s Working White makes that adaptation neutral. Changing Source White is an artistic adjustment; it does not change the Grade’s Working White.

The red and blue control references retain the existing construction: first CAT16-adapt Rec.709 red and blue from D65 to the Grade white, then place each anchor at 30% of its adapted xy displacement from that white. They are not fixed around D65 when another working white is selected.

## LUTs, Stacks and saved files

A fixed internal linear RGB basis keeps the LUT sampling grid independent of Blender’s scene gamut. Ordinary nodes keep Stage 1 outside their nonlinear LUT. A Stack evaluates every complete grade analytically, including its white handling and Stage 1, before baking the single LUT (33³ preview, 65³ final). The outer scene-coordinate matrices are not additional grading stages or additional LUTs.

Changing a Grade white automatically invalidates affected LUTs. Switching only Blender’s working space updates the surrounding matrices and reuses the same grading LUT. Alpha passes through unchanged and RGB is not clipped at the conversions.

Saved native graphs retain their evaluated appearance without the extension. Live edits, animation updates and adapting those graphs after a working-space change require the extension to be enabled.

The DCTL keeps its own Destination White behavior. It does not automatically convert a stored correction matrix when that setting changes.

## Which white does a baked LUT use?

Every production LUT uses **fixed native linear ACEScg / ACES-white input and output coordinates**, even in a Rec.709 or Rec.2020 scene. This sampling white is separate from each Grade's chosen white, which still defaults to D65. The 65³ grid covers 0…1024 with 64 positive intervals and plain log1p κ = 0.01; 33³ previews use 32 intervals on the same axis. Original signed inputs and outputs are retained. Inputs outside the grid hold the nearest edge cell's value rather than extrapolating, because the interpolation fraction is clamped; [Direct and sampled evaluation](../theory/lut.md) gives the details and notes where the legacy generator differs.

Let \(A\) convert the current scene RGB to this fixed AP1/ACES-white basis, including gamut conversion and Bradford adaptation. Its inverse returns to scene coordinates. These matrices are combined where possible; they are not additional LUTs.

| Node | Before the LUT | Baked content | After the LUT |
|---|---|---|---|
| Ordinary Grade | Scene → fixed LUT coordinates, with the exact Stage 1 matrix composed into the input | Stages 2–3 using the selected Grade-white context, returning to fixed LUT coordinates | Fixed AP1/ACES-white coordinates → scene |
| Grade Stack | Scene → fixed AP1/ACES-white coordinates | Every enabled Grade's stages, selected inverse and white connection, evaluated analytically in sequence | Fixed AP1/ACES-white coordinates → scene |

Thus a **Stack has ACES-white LUT boundaries**, while its entries can use D65, ACES, D50 or any supported preset independently. Bradford connects their contexts during the analytic bake. Rendering samples only the final cube.

For an ACEScg scene, the outer conversion matches the LUT basis and cancels to identity in exact arithmetic, apart from native configuration/float rounding. Rec.709/D65 and Rec.2020/D65 scenes use their gamut conversion plus D65 → ACES Bradford adaptation before lookup, and the inverse afterward.

These numerical boundary conversions do not apply a second creative white balance. Each Grade's white handling is already included in its effective Stage 1 matrix and baked nonlinear function. The Stack calculation is \(\mathrm{out}=A^{-1}\mathcal L_{\mathrm{stack}}(A\,\mathrm{in})\).

Changing only Blender's working space changes \(A,A^{-1}\), **not the LUT contents**. Changing a Grade white changes the analytic function and triggers rebaking. Preview refinement changes sample density only; it retains these white and gamut conversions. See [Stack baking](inverse-stack.md#baking-and-scope-updates) and [the sampling choice](../theory/lut.md).

# Linear

> **Preserved release:** this usage chapter and its captures describe 1.23.2 and still lag the latest model. See [Understanding the model](../theory/structure.md) for the current reference; these controls do not describe Next’s future Warp implementation.

Linear correction gives the image a sound starting point before creative grading. It corrects the lighting cast and broad color relationships across the whole image, so Tone and Color can shape the look without compensating for an unwanted tint. Global Exposure raises or lowers the overall level; establish a useful level, then work through white balance and the relationships below.

## Balance white and color relationships

Source White is the familiar white-balance adjustment: make what should look white actually white. Find a surface that should be neutral under the intended lighting, such as white paper, a gray card or a neutral chart patch. Judge the surface and its scope trace together; a colored object is not a white reference.

In each example, first drag the extension’s Linear vectorscope until the neutral surface loses its unwanted cast. Reset Source White to its starting position, then repeat the correction by dragging the source-white point directly. These are two ways to make the same adjustment. Keep the correction from the second pass for the next demonstration.

In Resolve, use the Perceptual Grade DCTL’s Source White = Custom xy setting, then adjust Source White x and Source White y. These sliders reproduce either gesture. Leave Destination White at the value established by your CST setup.

<figure class="grade-demo">
<img src="../assets/demos/linear-white-balance.webp" data-still="../assets/demos/linear-white-balance-still.webp" alt="A and B correct white balance by dragging the vectorscope, reset Source White, then repeat by dragging the source-white point." loading="lazy">
<figcaption>For both images: drag the vectorscope, reset Source White, then drag the source-white point directly. Keep the final white balance.</figcaption>
</figure>

Balance changes the relative brightness of opposing colors while keeping the established white fixed. Increasing Cyan-Red Balance brightens cyan relative to red; increasing Yellow-Blue Balance brightens yellow relative to blue. This is useful when the neutral surfaces look right but one side of a color relationship feels too bright or too heavy.

Spread and Heading change those relationships in a different way. A wider Spread generally makes colors in that direction more saturated; a narrower Spread brings them toward white. Heading turns the direction, steering hue. All six controls preserve the established white, so these adjustments do not undo the white balance.

Continue from the first demonstration and use both Balance handles, both Spread handles and both Heading handles. In A, balance opposing color brightness, widen muted color relationships and refine their hue. In B, balance different brightness relationships, restrain stronger color and refine its hue. Watch the whole image as each relationship changes.

In the DCTL, the six corresponding sliders are Cyan-Red Balance, Yellow-Blue Balance, Cyan-Red Spread, Yellow-Blue Spread, Cyan-Red Heading and Yellow-Blue Heading.

<figure class="grade-demo">
<img src="../assets/demos/linear-correction.webp" data-still="../assets/demos/linear-correction-still.webp" alt="A and B continue from white balance, adjusting both Balance handles and all four Spread and Heading handles for different purposes." loading="lazy">
<figcaption>The remaining six controls: two Balance handles, two Spread handles and two Heading handles, with the previous white balance retained.</figcaption>
</figure>

## Example: match a photographed ColorChecker

Continue from the Linear pass. Use a photographed ColorChecker under the lighting you are correcting, and the [ColorChecker2014 EXR](../downloads/ACEScg_ColorChecker2014.exr) as the reference. The reference is ACEScg: set that explicitly on its Image Texture or Image node. Set the photograph’s own input encoding correctly too.

Connect the photograph to Color and the EXR’s Color/Image output to Color Reference. Crop and orient the photographed chart like the EXR, with as little background as practical. The grade applies to Color; Color Reference supplies an independent comparison trace.

![ColorChecker EXR wired to Color Reference](../assets/screenshots/colorchecker-connect.png)

<p class="figure-caption">The photograph and ACEScg EXR image nodes, both connections, and the Linear vectorscope with its reference trace.</p>

Compare the neutral patches first. Refine Source White and Global Exposure, then use the Balance, Spread and Heading handles to bring the colored-patch readings toward the reference. Watch several patches at once: a single global matrix is a compromise, and lighting, glare and camera rendering can prevent an exact match. Carry the resulting correction into Tone.

<figure class="grade-demo">
<img src="../assets/demos/colorchecker-match.webp" data-still="../assets/demos/colorchecker-match-still.webp" alt="Match each photographed chart to its EXR reference by aligning neutral and colored-patch vectorscope readings." loading="lazy">
<figcaption>Match each photographed chart to its EXR reference by aligning neutral and colored-patch vectorscope readings.</figcaption>
</figure>

The red reference trace is drawn over the main trace in Linear. A click on a blank scope or Tone-curve area toggles reference visibility across stages; dragging the Linear vectorscope adjusts source white. Click and drag have different purposes.

In Tone, the reference appears on the After waveform and curve histogram. In Color, the waveform and vectorscope show corresponding positions for the selected input-tone region. Histogram heights are normalized independently, so their heights are not an exposure measurement.

The extension’s waveform measures perceptual lightness, while its vectorscope shows displayed Rec.709 signal chroma. Resolve’s native scopes use their selected host scale. For Resolve, compare the photograph and reference through matching CST and display chains, then use the same named Linear sliders above; the DCTL does not have the extension’s Color Reference socket.

For scope sampling, flat images, Render Layers color passes, RGB constants, reroutes and Perceptual Grade chains are supported. Render first for Render Layers; use a baked image when a procedural network cannot be sampled.

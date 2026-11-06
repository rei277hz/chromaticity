# Appearance coordinates and grading

Stage 1 still works on linear RGB in the extension, or its equivalent linear XYZ in the DCTL. Before Stage 2, the corrected color enters modCAM16. Tone and Color then operate on appearance coordinates; the result is decoded back to linear color after Stage 3. This chapter introduces that representation, especially the coordinates used by the Color controls.

This part describes the analytic reference model in `libraries/perceptual-grade-reference`. Where a statement holds only for the 1.23.2 DCTL and Blender release — its Concentration control, its Adaptance strength control, its `0.4·U(J_A,h)` driver crossover, and its shipped colour tables — the chapter says so. Where the analytic reference constrains its own scope more narrowly than the products do, the chapter names the narrower scope. Without that split a legacy statement reads like a stale one, and the two need different responses.

modCAM16 is a revised color appearance model in the CAM16 family. It describes how a color looks under specified viewing conditions, separating lightness, chromatic strength and hue. Perceptual Grade uses its revised relationships and Helmholtz–Kohlrausch compensation, which accounts for chroma’s contribution to perceived lightness.

![Published modCAM16 model flow](../assets/illustrations/modcam16-model-flow.png)

<p class="figure-caption">Reference illustration: Agahian and Stolitzka, “Modeling Perceived Brightness in HDR Displays” (2025), Figure 2. XYZ and viewing conditions lead to relative lightness/chroma/hue or absolute brightness/colorfulness/hue. The figure describes their model framework, not this tool's node graph. <a href="https://doi.org/10.2352/CIC.2025.33.1.7">Source</a>.</p>

The main lightness coordinate is \(H\), also written \(J_{\mathrm{HK}}\). It includes the H–K contribution and is labelled J in the interface. Tone, Lightness J, the waveforms and tonal selection all use this coordinate. The achromatic component, \(J_A\), enters the saturation calculation and the inverse-domain guard.

Chroma \(C\) measures distance from neutral in the grading opponent plane; hue \(h\) gives the angle around it. The corresponding Cartesian coordinates are \(a=C\cos h\) and \(b=C\sin h\). Chroma controls change the radius, Hue rotation turns the plane, and the directional pads use its signed \(a\) and \(b\) coordinates.

At fixed \(h\), moving outward increases \(C\). Moving around the plane changes \(h\). Moving \(a\) or \(b\) can change both. A Lightness J adjustment changes \(H\); a Chroma \(C\) adjustment changes the radius; Adaptance shifts the opponent position; Hue rotation turns it. The tone curves determine how strongly each operation acts at different input lightness levels.

$$
H=J_{\mathrm{HK}}=\sqrt{J_A^2+66C}\quad (J_A\ge0),\qquad
C=\sqrt{a^2+b^2},\qquad h=\operatorname{atan2}(b,a).
$$

The identity holds on the nonnegative achromatic branch. Signed working colors below it reach the opposite side of the H–K pair, where the same \(C\) has a second, smaller lightness solution. With \(b=\sqrt{66C}\) the reference reflects about that midpoint instead of discarding the sign:

$$
H=2b-\sqrt{J_A^2+b^2}\quad (J_A<0).
$$

\(H\) therefore stays continuous through \(J_A=0\), where it is \(b\), rather than collapsing to \(\sqrt{66C}\). The inverse of this signed map is the energy \(E=J_A|J_A|\), carried separately through the Color stage; it is never recovered by subtracting \(66C\) from a rounded \(H^2\).

![Published relationship between modCAM16 lightness, chroma and hue](../assets/illustrations/modcam16-lightness-chroma.png)

<p class="figure-caption">Reference illustration: the same paper, Figure 3. The markers compare chroma and H–K-compensated lightness for several hues at two achromatic-lightness levels. This is a published model example, not a measurement of the running SDR/HDR grades. <a href="https://doi.org/10.2352/CIC.2025.33.1.7">Source</a>.</p>

The grading plane uses actual \(C\) as its radius. Do not substitute textbook CAM16-UCS \(M'\) or other compressed uniform-space coordinates for these \((a,b)\) values. The shared vocabulary does not make the numerical scales interchangeable.

Curves use \(j=H/100\). A reference-white neutral has \(H=100\); HDR lightness can continue above it. Defaults are Reference Nits = 203 and adapting luminance \(L_A=20.3\) nits, with dark-surround constants \(c=0.525\) and \(N_c=0.8\). Encode and decode share the same hue-eccentricity expression, including \(-0.1475\sin h\).

The remaining viewing constants are the background and the test white: the reference fixes background luminance \(Y_b=10\) and normalizes the cone responses by \(100W\), with the illuminant discounted. Earlier releases described the background as 20.3 nits. That value matches neither the reference nor the current products, and it changes the encoded response for every color, so it is worth stating plainly rather than leaving to the implementation.

The analytic reference accepts one configuration: Grade white D65 with Reference Nits 203. Its own entry point raises on any other white or reference, because its boundary tables are generated for that pair. The DCTL and Blender products offer the eight white presets and a wider Reference Nits range described in [Working White](../guide/working-white.md); those settings belong to the products, not to this analysis.

Two lightness coordinates exist and must not be conflated. \(H\), or \(J_{\mathrm{HK}}\), includes the H–K term and is what Tone remaps. The achromatic component \(J_A\) enters the saturation ratio and the inverse-domain guard, and is carried as signed energy rather than recomputed.

The [saturation-preserving tone curve](tone.md) remaps lightness while maintaining the tone-stage invariant. [Tone-shaped color operators](color.md) then blend adjustments across tonal regions. [Evaluation and interpolation](evaluation.md) follows the bounded H–K guard and the analytic, native and sampled implementations.

For signed working colors, the implementation lifts negative cone responses with a neutral offset, transforms both the lifted signal and that offset, then subtracts the transformed offset. Exact reset retains its identity bypass. The guard handles the separate real-achromatic-energy boundary after Color. The full model and engineering references are listed in [credits](../reference/credits.md).

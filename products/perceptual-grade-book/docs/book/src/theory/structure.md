# Appearance coordinates and grading

Stage 1 still works on linear RGB in the extension, or its equivalent linear XYZ in the DCTL. Before Stage 2, the corrected color enters modCAM16. Tone and Color then operate on appearance coordinates; the result is decoded back to linear color after Stage 3. This chapter introduces that representation, especially the coordinates used by the Color controls.

modCAM16 is a revised color appearance model in the CAM16 family. It describes how a color looks under specified viewing conditions, separating lightness, chromatic strength and hue. Perceptual Grade uses its revised relationships and Helmholtz–Kohlrausch compensation, which accounts for chroma’s contribution to perceived lightness.

![Published modCAM16 model flow](../assets/illustrations/modcam16-model-flow.png)

<p class="figure-caption">Reference illustration: Agahian and Stolitzka, “Modeling Perceived Brightness in HDR Displays” (2025), Figure 2. XYZ and viewing conditions lead to relative lightness/chroma/hue or absolute brightness/colorfulness/hue. The figure describes their model framework, not this tool's node graph. <a href="https://doi.org/10.2352/CIC.2025.33.1.7">Source</a>.</p>

The main lightness coordinate is \(H\), also written \(J_{\mathrm{HK}}\). It includes the H–K contribution and is labelled J in the interface. Tone, Lightness J, the waveforms and tonal selection all use this coordinate. The achromatic component, \(J_A\), enters the saturation calculation and the inverse-domain guard.

Chroma \(C\) measures distance from neutral in the grading opponent plane; hue \(h\) gives the angle around it. The corresponding Cartesian coordinates are \(a=C\cos h\) and \(b=C\sin h\). Chroma controls change the radius, Hue rotation turns the plane, and the directional pads use its signed \(a\) and \(b\) coordinates.

At fixed \(h\), moving outward increases \(C\). Moving around the plane changes \(h\). Moving \(a\) or \(b\) can change both. A Lightness J adjustment changes \(H\); a Chroma \(C\) adjustment changes the radius; Adaptance shifts the opponent position; Hue rotation turns it. The tone curves determine how strongly each operation acts at different input lightness levels.

$$
H=J_{\mathrm{HK}}=\sqrt{J_A^2+66C},\qquad
C=\sqrt{a^2+b^2},\qquad h=\operatorname{atan2}(b,a).
$$

![Published relationship between modCAM16 lightness, chroma and hue](../assets/illustrations/modcam16-lightness-chroma.png)

<p class="figure-caption">Reference illustration: the same paper, Figure 3. The markers compare chroma and H–K-compensated lightness for several hues at two achromatic-lightness levels. This is a published model example, not a measurement of the running SDR/HDR grades. <a href="https://doi.org/10.2352/CIC.2025.33.1.7">Source</a>.</p>

The grading plane uses actual \(C\) as its radius. Do not substitute textbook CAM16-UCS \(M'\) or other compressed uniform-space coordinates for these \((a,b)\) values. The shared vocabulary does not make the numerical scales interchangeable.

Curves use \(j=H/100\). A reference-white neutral has \(H=100\); HDR lightness can continue above it. Defaults are Reference Nits = 203, adapting luminance 20.3 nits and background luminance 20.3 nits, with dark-surround constants \(c=0.525\) and \(N_c=0.8\). Encode and decode share the same hue-eccentricity expression, including \(-0.1475\sin h\).

The [saturation-preserving tone curve](tone.md) remaps lightness while maintaining the tone-stage invariant. [Tone-shaped color operators](color.md) then blend adjustments across tonal regions. [Evaluation and interpolation](evaluation.md) follows the bounded H–K guard and the analytic, native and sampled implementations.

For signed working colors, the implementation lifts negative cone responses with a neutral offset, transforms both the lifted signal and that offset, then subtracts the transformed offset. Exact reset retains its identity bypass. The guard handles the separate real-achromatic-energy boundary after Color. The full model and engineering references are listed in [credits](../reference/credits.md).

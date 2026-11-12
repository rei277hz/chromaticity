# Tone

> **Preserved release:** this usage chapter and its captures describe 1.23.2 and still lag the latest model. See [Understanding the model](../theory/structure.md) for the current reference; these controls do not describe Next’s future Warp implementation.

Keep the completed Linear adjustments in A and B. Now shape the tonal relationships for each image’s purpose: stronger contrast in A, and more readable dark areas in B.

## Shape contrast and open the shadows

Use the same Tone landmarks for different purposes. In A, lower darker tones and lift brighter tones to form an S-shaped contrast curve. In B, lift dark and middle regions into a gamma-like shape while holding white and the brightest highlights close to their established relationship.

Drag a landmark on the Before waveform, or move its curve dot horizontally, to identify the input tone that should map toward that landmark’s target. The After waveform shows the result. Moving an input landmark right asks a higher input level to reach the same target; moving it left asks a lower level to reach that target. The curve blends these requests smoothly.

<figure class="grade-demo">
<img src="../assets/demos/tone-curve.webp" data-still="../assets/demos/tone-curve-still.webp" alt="A increases contrast with an S-shaped curve; B brightens darker areas with a gamma-like curve." loading="lazy">
<figcaption>A increases contrast with an S-shaped curve; B brightens darker areas with a gamma-like curve.</figcaption>
</figure>

In Resolve, the Perceptual Grade DCTL uses Input Black Nits, Input Shadows Nits, Input Midtones Nits, Input White Nits and Input Highlights Nits for the five landmarks. Remap Fit changes the curve fit. Reference Nits sets diffuse-white calibration, and Peak Anchor Nits sets the bright anchor.

These Nits inputs describe a neutral with the selected lightness. Read the resulting curve and waveform instead of expecting a hard pin through every landmark. After placing the levels, adjust Remap Fit to spread transitions more broadly or concentrate them around the landmarks.

## Compare SDR and HDR on the waveform

In Example A, look for the dark areas, midtones and a diffuse white such as paper. An SDR image commonly groups these below or around the reference-white line. Its bright detail may occupy only a narrow band near that line.

In Example B, identify a similar diffuse surface and then a brighter light source, window or specular reflection. The HDR waveform can place that bright feature well above diffuse white while the surface and midtones remain much lower. Compare these distinct regions; a bright peak is not the image’s average tone.

![Side-by-side SDR and HDR waveforms](../assets/screenshots/tone-waveforms.png)

<p class="figure-caption">A shows the SDR image and its compact tonal range; B shows the HDR image, diffuse white and clearly separated brighter highlights. Use the same waveform scale and label those features.</p>

The reference-white line is \(j=1\), or \(J=100\) in the lightness readout. With the default Reference Nits of 203, it represents a 203-nit neutral. The graph extends to the lightness of a 4000-nit neutral even when the grade uses a lower Peak Anchor Nits. The extension’s perceptual waveforms use this lightness scale; Resolve’s native scopes use the scale selected in Resolve.

That shared scale explains the empty headroom in A. Do not move ordinary midtones upward just to fill it. In B, leave a useful separation between diffuse white and the genuinely bright features rather than treating the brightest peak as ordinary white.

Keep the completed curve while moving on to Color.

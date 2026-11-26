# Grade Stacks

A **Grade Stack** combines an ordered list of shared Grades into one sampled
transform. Enabled entries run from top to bottom. Use the direction selector
on each entry to choose **Forward** (the default) or **Inverse**. An Inverse
entry can appear anywhere, including alone or next to another Inverse. It
searches for an input whose Grade result before AP1-D65 boundary mapping
matches the target. This applies to both RGB and appearance targets. Grading
can discard information, so the recovered input can be approximate or one of
several possible inputs. Inverse requires an invertible Linear transform.

An **Inverse → Forward** pair passes the recovered pre-Tone appearance directly
when the entries have the same Linear transform. Different Linear transforms
compose in CAT16 cone space. A **Forward → Inverse** pair passes the post-Color
appearance. Both handoffs carry signed values and avoid an RGB round trip.
Only a final Forward entry applies the AP1-D65 boundary mapping. A final Inverse
entry returns recovered signed RGB, which can exceed the LUT grid maximum of
1024.

## Arrange and edit entries

Use **Add Grade** to create an enabled empty entry, then choose a shared Grade
in its selector or use the entry's plus button to create a new Grade.
Use the entry controls to enable or bypass it, select its sidebar editing target,
move it up or down, or remove it. Unlinking the Grade leaves an empty entry;
removing the entry leaves the shared Grade datablock intact. A Stack with no
enabled Grades is identity.

Selecting an entry's edit control opens the sidebar for that shared Grade.
Changes update every ordinary Grade node and Stack entry that references it.
Create an independent Grade when one entry needs different parameters. Stack
membership and order belong to the node; the Grade settings belong to the
shared datablock.

## One LUT for the full sequence

The Stack evaluates all enabled Grades, including each Linear matrix, into one
65³ GPU-prepared LUT. While editing, a 33³ preview can install first; the final
65³ result follows. The preview uses every other final-grid coordinate; the GPU
helper evaluates the two resolutions separately. A complete prior result can
remain visible during updates, but rendering and normal saving wait for a
current full result.

The Stack can use a LUT with finite inverse approximations outside tolerance.
It warns how many vertices of the displayed preview or full LUT are affected
and reports the worst error as a multiple of tolerance.

Changing a referenced Grade, entry direction, enable state, or order changes the sampled
function. A current setting signature is required before a result can install.
After file load or before rendering, the extension reconciles the derived LUT. A
preparation failure is visible and fails closed with magenta output preserving
alpha.

The Stack works in fixed internal linear ACEScg / ACES-white coordinates. Scene
conversion surrounds the LUT, while all entries are evaluated within it. See
[Scene working spaces](working-white.md) and [evaluation and interpolation](https://rei277hz.github.io/perceptual-grade/technical/en/theory/lut.html).

# Grade Stacks

A **Grade Stack** combines an ordered list of shared Grades into one sampled
transform. In current Next, every enabled entry runs forward, from top to
bottom. The Stack is not an inverse-solving tool in this release.

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

Changing a referenced Grade, entry enable state, or order changes the sampled
function. A current setting signature is required before a result can install.
After file load or before rendering, Next reconciles the derived LUT. A
preparation failure is visible and fails closed with magenta output preserving
alpha.

The Stack works in fixed internal linear ACEScg / ACES-white coordinates. Scene
conversion surrounds the LUT, while all entries are evaluated within it. See
[Scene working spaces](working-white.md) and [evaluation and interpolation](https://rei277hz.github.io/perceptual-grade/technical/en/theory/lut.html).

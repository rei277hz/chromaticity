# Native export guards

The full forward graph applies the reference H–K repair once, using the frozen
post-Tone signed energy, then projects onto the native AP1 `[0, 1024]` cube.
Input RGB repair is absent. Both guards remain separate from raw appearance
handoffs and can be exercised independently.

H–K repair retains carried energy rather than recovering it by subtracting
rounded lightness and chroma. Its requested square is rationalized on the
negative-energy branch. The reference knee, energy repair, bounded lightness
lift and hue-preserving chroma reduction are unchanged. Negative H keeps the
raw state for the boundary guard. The graph reuses known chroma and offset
sockets; static magnitude bounds permit ordinary arithmetic where squared
operands are provably representable, otherwise scaled norms and explicit
representational saturation remain active.

## Boundary geometry and native correction

The boundary is parameterized by normalized neutral response `t`, hue `h`,
and normalized radius `u`, with `C = r_white * t * (1-t) * u`. A fixed
D65/203-nit, Bradford-adapted AP1 context owns the matrices and white limit.
`prepare_boundary(fl, aw, gamma)` loads immutable caller-owned geometry from the
packaged `output_boundary.npz`; `prepare(..., boundary=geometry)` can share it
across grades and tree types. The context is invariant across all currently
supported grading controls and scene spaces. Each native group still owns its
packed image. There is no global cache or reference-model runtime dependency.

`//products/perceptual-grade-next-blender:boundary_resource` generates the asset and
its validation report through the portable `:boundary_generator`. Code and
packaged resources are separate Buck dependencies to avoid a generator cycle.
The versioned resource retains the geometry, matrices and sampling contract
needed by the native correction. Runtime loading validates schema, arrays,
context and recorded gate metadata; it never repeats the dense root solve or
silently regenerates missing/incompatible data. Generation is a build-time cost,
while resource loading and native image packing remain runtime costs. The current
image-sized CPU fixture measures median loading at about 27 ms; see
[EVIDENCE.md](EVIDENCE.md) for exact producer identities, costs and timing limits.

The retained seed is a sampled representation of fixed cube geometry. This
change does not replace it with the compact fitted coefficients in the old
`d65_boundary.npz`; that alternative requires its own native implementation,
accuracy, storage and node-count comparison.

The packed float32 image has **513 hue columns × 321 response rows** and uses
bilinear Non-Color/channel-packed sampling. Three channels store separate
RGB-face tangent root estimates. The rows allocate 128 cells to `t=0…0.9`
and 192 to `t=0.9…1`; the final hue column closes the periodic seam. Storage
is **2,634,768 bytes (2.51 MiB)**. These are geometric root seeds, not RGB
colour-grading samples.

Shader sampling interpolates four nearest texels explicitly at level zero.
Implicit screen-space mip filtering would mix unrelated geometric coordinates;
the Compositor uses its native bilinear Map UV operation.

One native **Halley correction** uses the actual appearance decoder's first
and second radial derivatives. The correction denominator is restricted to
`[0.5, 1.5]` so distant inactive faces cannot attract the selected root.
Vector operations evaluate the three cone responses together. A small inward
radius allowance of `1.2e-5` handles float32 boundary rounding; it preserves
energy and hue. Black and white tips have explicit policies.

Near black, the root equations use normalized cone values. Near white they use
cone deficits, with a stable divided-difference polynomial near zero. A
compensated white-energy difference and fifth-order expansion preserve the
distance to white through a normalized energy deficit of `0.1`. The same stable
deficit supplies the solver's neutral response, avoiding GPU power-rounding
amplification in `1-t`. Constant row dots map normalized solver values and
derivatives; the physical RGB decoders retain neutral-preserving arithmetic.
The final candidate is decoded and tested against the actual native cube.
An already legal direct decode is preserved. An unresolved numerical trial
uses the legal neutral at the same energy; the RGB and native-radius gates
also cover this path, so containment alone cannot certify its accuracy.
Radius and pole-margin diagnostics describe the returned value, including
neutral fallback, preserved direct decodes and black/white endpoint policies.
Scene RGB is produced from the tested native value. It is not clipped to the
scene RGB cube: valid AP1 colours can have negative Rec.709 channels.

## Independent acceptance

The build-time generator rejects a nonfinite result or normalized corrected-radius error
above **`2e-5`**. Its 183,680 deterministic float32 probes include every one of
the 163,840 cell centers, random positions, both tips and float32 neighbors of
selector boundaries. The measured maximum is **`1.0623866e-5`** against an
independent bracketed float64 solve. The bracketed solver is additionally
compared with the reference model's actual-decoder cube projection. A deliberately
coarse hue table must fail generation. These finite checks are not an exhaustive
error proof over continuous hue and energy.

The library-local `tests:guards` target separately renders native Shader and
Compositor probes with matching float32 carried-energy inputs. It covers the
worst measured cell centers, previously difficult face changes, near-white
values and subnormal energy, as well as random interior/exterior samples.
The reference adapter bypasses only the optional capacity seed and retains the
reference decoder and 56-step boundary solve.

The full GPU report additionally runs the permanent `gpu_guards` fixture on
Eevee and Compositor GPU. It shares the independently defined float32 probe
corpus with the CPU tests and writes `guard-internal.json`. Its strict local
radius gate caught a near-white GPU power-rounding error even though the complete
RGB gate passed; the stable energy-deficit calculation above fixes that case.

The following Blender 5.2.2 measurements belong to the historical 2D-enabled
delivery. Current asset-bound receipts are listed in [EVIDENCE.md](EVIDENCE.md):

| Internal or isolated check | Gate | CPU maximum | Available GPU maximum |
| --- | ---: | ---: | ---: |
| H–K coordinates, robust and bounded paths | `1e-5` | `2.02935e-7` | `3.53562e-7` |
| H–K carried energy | `1e-5` | `2.44019e-6` | `2.44019e-6` |
| Returned projected radius, including inward rounding | `2e-5` | `1.57196e-5` | `1.62929e-5` |
| Isolated guarded scene RGB, three spaces/two contexts | `1e-4` | `2.44202e-5` | `2.48430e-5` |

Every tested native AP1 channel is exactly within `[0, 1024]`; all decoded
validity outputs are true. Radius checks apply to projected interior-energy
rays; preserved direct values, endpoint policies and forced neutral fallback
have separate assertions. The H–K fixtures exercise both the general and
statically bounded implementations. GPU coverage is Linux software OpenGL
llvmpipe, not physical GPU or Metal acceptance.

All five CPU guard tests passed in the historical acceptance batch, recorded in
`buck-out/nodes-stage3-final/acceptance-tests.log`. The permanent GPU fixture
passed all 14 cases of 256 samples; its source-bound results are included in
that historical GPU report. These receipts do not certify the current generated
asset and loader; current build identities belong to [EVIDENCE.md](EVIDENCE.md).

An earlier development run of geometry generation and its complete finite gate
took **10.57 seconds**. A later pre-packaging breakdown measured about 5.99 seconds
for the same fixed work. These historical timings are generation costs, not
current runtime loading latency. Current asset generation/loading, native
evaluation and complete graph counts belong to the handoff reports linked from
[EVIDENCE.md](EVIDENCE.md).

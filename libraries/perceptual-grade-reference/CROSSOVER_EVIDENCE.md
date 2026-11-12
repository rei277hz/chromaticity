# Historical reference Stage 3 crossover acceptance

This record describes the 2026-10-28 implementation. The corrected reference
now repairs H–K before Warp Scale, and reference-owned BakeStack CPU/GPU
backends support the 35/75 crossover. The old BakeStack rejection and deferred
acceleration statements below are historical. The saved build results are not
validation of the current implementation and are not instructions to rerun
core or frozen-product validation.

Date: 2026-10-28. The analytic reference now uses `r=(35/75)*abs(J_A)` with
visibility `V=C²/(C²+4)` and low/high weights `V*(r²,C²)/(C²+r²)`.
Neutral/black weights are zero. The float64 and scaled-number paths use the
same frozen post-Tone inputs. No capacity lookup is used for these weights.

Reference BakeStack rejects active low/high lightness/chroma controls before
preparing models or accelerated tables. Analytic Model, inverse, Stack and CLI
support them. Shared production CPU/GPU kernels retain the capacity equation;
explicit legacy adapters under test support preserve their verification.

| Verification | Result | Buck build ID |
| --- | --- | --- |
| Reference grading, inverse, analytic Stack/BakeStack support, CLI | 4 targets pass | `0d20c38c-e50a-4225-824b-8d1a4a3ebf8a` |
| Reference model/appearance/guards/Tone/web/Adaptance, support, node reference/native, architecture | 15 targets pass | `25ed24cf-dd7b-4569-aca8-4d8cf7d45c54` |
| Final BakeStack rejection and host-free import/GPU-factory contract | 2 targets pass | `7b91ab84-1112-4c72-9a8b-6049fdc417bb` |
| Retained legacy inverse-baking solver suite | 34 cases pass | `0e5cd0be-09c2-427a-80ce-c61db40ed00b` |
| Core appearance; Blender inverse and reference integration; DCTL numerical/interface/portability | 98 tests across 11 targets pass | `6c595cb9-29ea-44f9-977d-dedae46832ff` |
| Actual GPU inverse baking | 23 cases pass | `1fab370b-a5ef-4872-af60-9603007a8b5c` |
| Changed raw/full-grade GPU oracle comparisons | 2 cases pass | `7e77f61e-2c76-46d9-b71e-0e754e642a7a` |
| Product analysis executable builds and CLI smoke checks | 12 tools pass | `ebc6b257-4996-4a61-8369-397062cb1f07`, final rebuild `50fd36a0-7499-49d9-b0d5-5039233d1bd4` |
| Updated fixed-J_A/spindle plots and historical crossover comparison | Build passes; plots visually checked | `eead73c4-fb97-4fac-ac52-d0d445e3687a` |
| Visibility/crossover/raw-capacity historical studies with current-reference checks | 3 targets pass | `5ddbae5d-a128-4a10-95d9-bd1bbb8a0221` |
| Root `//:verify`, reference and Blender runtime bundles | Build passes | `818b0c19-65ff-4fa4-bd4b-3d1e9fcd820b` |

The analysis checks report maximum absolute driver discrepancy **0.0** over
274,625 compressed sample coordinates and in the raw-lattice check. The unit
properties cover midpoint ±75/35, sign symmetry, hue independence, neutral and
J_A=0 limits, complement/bounds, scalar/batch agreement, frozen inputs and
scaled values beyond float64 exponents. Folded inverse coverage retains both
known preimages (approximately C=3.69734 and 18.50520 for target C=3.5).
Normal grade-control acceptance uses UI-range values; representation stress and
the retained non-injective inverse fixture are separate mathematical tests.

The full GPU baking suite is **not green**: its unrelated
`test_actual_gpu_image_sampler_preserves_signed_values` calls the removed public
`scopes.sampling.sample_image` attribute. Eleven other cases, including both
changed oracle comparisons, pass; the latter also pass in the focused run above.
No runtime change was made for this unrelated test failure. GPU coverage here is
Linux Blender with Mesa llvmpipe, not macOS/Metal or hardware-GPU certification.

Runtime manifests were inspected: neither reference nor Blender includes the
legacy test-support module. Source hashes and retained build/test logs are in
`buck-out/reference-crossover-validation/summary.json`. The previous native-node
reports retain their original source identities; their Fit 3/Quintic 512 decision
and the general reference Tone limits are unchanged. Stage 3 native nodes and
accelerated support for the new law remain deferred. Existing capacity-based
Lean theorems continue to apply to the retained production equation.

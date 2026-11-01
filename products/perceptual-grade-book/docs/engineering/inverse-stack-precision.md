# Perceptual Grade 1.14.1: inverse and Stack precision

Both node types use the requested fixed 65³ signed HDR grid. The mixed Stack evaluates Forward A → Inverse B → Forward C directly at each final vertex, including all three Linear matrices. No intermediate LUT is sampled during its bake.

## Measurement contract

- Working space: Linear Rec.2020; 203 reference nits. Complete Grade parameters are in `inverse-stack-precision.json` and the executable measurement fixture.
- Four stored IMG_* photorealistic fixtures: 2,048 randomly selected pixels each, without clipping; deterministic seed 1140065. These are samples of the fixtures, not every original pixel.
- Synthetic probes: 2,048 positive HDR, 2,048 signed HDR and 256 probes spanning beyond the grid. The positive/HDR source domain reaches RGB=64; a forward transform can move inverse inputs beyond the LUT domain.
- Bake vertices use float64 equations and best-effort numerical inverse solves. Stored cubes use float32; off-grid evaluation uses physical-linear-RGB tetrahedra.
- Scalar error per pixel: e = max(abs(actual − reference)) / (1 + max(abs(reference))). All channels are scene-linear working RGB. These numbers are not perceptual ΔE and not percentages of signal brightness.
- The JSON also contains absolute RGB errors and relative errors with a 0.001 denominator floor. Small dark signals can have large relative errors even when absolute errors are small.

## Photographic fixtures: inverse interpolation

“Inverse vs analytic” compares the ordinary inverse LUT plus its post-matrix against the selected analytic inverse. “Reproduction” applies the analytic forward Grade to the LUT result and compares it with the requested inverse input.

| Fixture | Inverse vs analytic p99 | Inverse vs analytic max | Reproduction p99 | Reproduction max |
| --- | ---: | ---: | ---: | ---: |
| IMG_0436 | 0.000584913 | 0.00187013 | 0.000450854 | 0.00255388 |
| IMG_0441 | 0.00069611 | 0.00141119 | 0.000319068 | 0.000520432 |
| IMG_0446 | 0.000516505 | 0.00217021 | 0.000300738 | 0.00133335 |
| IMG_0472 | 0.00176767 | 0.0210142 | 0.0015841 | 0.0138756 |

The analytic inverse itself has photographic p99 normalized reproduction errors no higher than 2.24665e-11, and maximum 3.28135e-08. The maximum occurs in IMG_0446 and is higher than the earlier 1.14.0 result (3.70324e-11); a fixed bounded best-effort solver does not guarantee every off-grid request reaches its diagnostic tolerance. Final LUT interpolation errors remain much larger. The photographic interpolation figures are unchanged at the displayed precision.

## One mixed Stack versus three separate LUTs

Both approximations are compared with exactly the same float64 Forward A → Inverse B → Forward C sequence. Separate nodes retain each Linear matrix outside its own nonlinear LUT.

| Fixture | One Stack p99 | Three LUTs p99 | One Stack max | Three LUTs max |
| --- | ---: | ---: | ---: | ---: |
| IMG_0436 | 0.000508921 | 0.000580011 | 0.00540673 | 0.00398624 |
| IMG_0441 | 0.000580382 | 0.000592361 | 0.000829901 | 0.000746584 |
| IMG_0446 | 0.000571437 | 0.000709497 | 0.0010956 | 0.00098765 |
| IMG_0472 | 0.00186786 | 0.00179528 | 0.00541476 | 0.0115574 |

The single mixed Stack lowers p99 error in three fixtures and raises it slightly in IMG_0472. Maximum error is also not uniformly improved. Combining lookups removes intermediate interpolation, but redistributes sampling across the composed function.

## A fully forward sequence

| Fixture | One Stack p99 | Three LUTs p99 | One Stack max | Three LUTs max |
| --- | ---: | ---: | ---: | ---: |
| IMG_0436 | 0.000457732 | 0.000695693 | 0.0015988 | 0.00300406 |
| IMG_0441 | 0.000429844 | 0.00044156 | 0.000817876 | 0.00080369 |
| IMG_0446 | 0.00046734 | 0.000469158 | 0.000935126 | 0.000818906 |
| IMG_0472 | 0.00320707 | 0.00328965 | 0.0127718 | 0.0263148 |

## Broad signed/HDR and extrapolation stress tests

| Input population | Inverse vs analytic p99 / max | Mixed Stack p99 / max | Three mixed LUTs p99 / max |
| --- | ---: | ---: | ---: |
| positive-HDR | 0.0286465 / 0.0342432 | 0.00102377 / 0.00222706 | 0.00116649 / 0.00249255 |
| signed-HDR | 0.10299 / 0.285585 | 0.0791781 / 0.237214 | 0.107519 / 0.282664 |
| outside-grid | 0.482891 / 0.729892 | 0.574792 / 0.835925 | 0.71528 / 1.04503 |

These stress errors are substantial. The fixed grid is not uniformly accurate over extreme signed colors, selected-inverse branches or extrapolated inputs. Do not infer photographic accuracy, reversibility or global solver convergence from the grid size alone. The positive HDR inverse test can include extrapolation because its forward-transformed targets can exceed RGB ±64.

## Inverse solves at bake vertices

An approximate sample has complete-forward reproduction residual above 2e-8 before float32 storage. Counts reflect the bounded, deterministic solver policy; they are not proofs that those targets have no exact preimage.

| Bake | Inverse samples | Approximate | Fraction | Worst inverse residual |
| --- | ---: | ---: | ---: | ---: |
| Ordinary nonlinear inverse | 274,625 | 88 | 0.03204% | 0.0482578 |
| Inverse entry inside mixed Stack | 274,625 | 78 | 0.02840% | 0.0383937 |

The sample count and worst residual are stored with the packed image; the node displays an approximate-sample warning. The chosen presets contain no singular Linear matrices. Separate tests verify that singular settings use a finite pseudoinverse and report reproduction failures.

## Cost and host verification

- A Stack requires four tetrahedral vertex reads instead of twelve for three separate LUTs, with no separate runtime Linear matrix for its entries. This is an operation count, not a measured GPU speedup.
- Three repeated fresh numerical bakes: ordinary inverse 4.11–4.20 s (median 4.16 s); mixed Stack 4.61–5.00 s (median 4.96 s); forward Stack 0.93–0.95 s. The separate precision run took 4.60 / 5.23 / 1.27 s respectively. These exclude the 250 ms debounce and Blender publication. The ordinary benchmark meets five seconds here; the mixed Stack is marginal and exceeded it in the precision run. See `inverse-bake-performance.md` for the solver redesign, experimental comparisons and exact measurement scope.
- Native Blender 5.2.2 LTS tests render inverse and Stack graphs through CPU Cycles and the CPU compositor. Their maximum normalized difference from the matching cube/matrix evaluator is 1.95e-7 for the test scenes; alpha is preserved. This tests graph transport and lookup, separately from analytic approximation.
- Regression coverage includes matrix placement, nonunique inverse reproduction, black clipping, shared edits, independent list copies, stale completion rejection, background publication, animation dependencies, actual undo/redo, save/load, preference restoration and disabled-extension appearance.
- Validation runs use the repository’s explicit authoring-preview runner with the pinned Python/wheels. They do not replace the unavailable Buck2 release gate. Desktop interaction and GPU/Metal execution were not exercised.

## Reproduce

Run `tests/blender/evaluate_inverse_precision.py` using the prepared test environment (see the handbook’s authoring-preview instructions). It writes the full JSON and signature-keyed cube caches into `tests/blender/reports/`. Use `tests/blender/benchmark_inverse.py` for repeated fresh bakes without completed-cube cache reuse. The regular inverse proof fixture, production inverse tests and host tests are separate, so failures can be located at the correct layer.

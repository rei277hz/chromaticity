# Perceptual Grade 1.12.0 — p=2 implementation and validation

The complementary classifier is implemented in DCTL and the Blender Extension:

$$s=75C/J_A,\quad s_0=35,\quad C_n=2,\quad
q_s=\frac{C^2}{C^2+(35/75)^2J_A^2},\quad V=\frac{C^2}{C^2+4},\quad
d_\ell=V(1-q_s),\quad d_h=Vq_s.$$

Black and neutral chroma give zero weights. J_A is carried from encoding through
Tone; scaled ratios avoid overflow and subtraction cancellation. The classifier
is analytic in DCTL, native analytic graphs, Quintic2048, prepared scopes and
cube baking. The 14-curve Quintic table no longer contains a Cs row. The 3×6
contribution interpretation, hue/concentration operations and H–K guard remain
as documented in [the full forward/inverse handbook chapter](../book/src/development/forward-inverse-math.md).

Existing low/high settings keep their names and ranges but intentionally produce
a different grade. Revisit those controls when upgrading. Cached graph schemas
and package release identifiers are bumped to 1.12.0.

A render test exposed a compositor unchanged-core bug for negative neutral
inputs. Its shortcut now returns the lifted cones used for encoding, so the
neutral offset is subtracted exactly once.

## Executed grading suites

All 47 declared grading fixtures passed with their original numerical tolerances.
Each ran in an isolated tree using explicit `--authoring-preview` mode. This
mode never sets Buck provenance and does not satisfy the Buck release gate.

| Suite | Fixtures passed |
| --- | ---: |
| numerical | 18 |
| blender | 15 |
| parity | 3 |
| renders | 4 |
| dctl | 7 |

Runtime: pinned CPython 3.13.6, Blender/bpy 5.2.2 LTS, NumPy 2.5.3,
Colour 0.4.7, and the exact Linux wheel URLs and SHA-256 hashes in
`third_party/python-lock.json`. DCTL host compiled with g++ using C++17,
`-O2 -Wall -Wextra -Werror`.

- Broad DCTL acceptance: 131,799 host cases, all 55 contributions and 110 endpoint settings, signed HDR, bypasses and fallback.
- Focused independent p=2 DCTL check: 2,376 samples; maximum absolute driver error 2.47e-7.
- Actual Stage 3 CPU compositor/Cycles tests: Rec.709, Rec.2020 and ACEScg, alpha, negative/HDR values, strong grades and save/reopen. Maximum normalized compositor RGB error 1.433e-05 against compiled DCTL (limit .003).
- Both full-precision and half-buffer routes: 4,483 samples per grade, 17 grades, Quintic and cube evaluation.
- Full mathematical inverse: 48 mixed-color samples, 24 active guards; maximum absolute recovered RGB error 8.127e-14, forward reproduction error 1.248e-13.
- Guard inverse: 2,400 requests, 1,603 active; maximum componentwise normalized error 7.8e-13.
- Documented classifier Jacobian checked against finite differences: maximum absolute difference 2.71e-11. The new p=2 nonunique inverse example is verified through the full forward transform.
- All 555 mathematical expressions in the complete spec parse with KaTeX.

## Regression provenance

Historical NPZ and metadata files are unchanged. New p=2 baselines are separate
under `tests/blender/fixtures/p2`; hashes cover both old and new files. They use
an independent long-double rational driver formula. Tone, guard and interpolation
are reused in that baseline generator; this is explicitly not an independent
end-to-end colorimetry oracle. Independent Colour/DCTL parity and native renders
supply additional validation. Unaffected grades retain their historical checks.
The 12-grade LUT test keeps its original percentile tolerances.

## Packaging and documentation

Both localized DCTLs and the Blender extension are regenerated. The English
Color and interpolation chapters, generated driver figure and photo comparisons
use p=2. The complete forward/inverse document updates the two-variable inverse,
classifier derivatives, carried-J_A contract, fold example and numerical vectors.
The handbook is rebuilt using hash-verified mdBook 0.5.4. Unchanged generated
handbook resources are reused from the supplied baseline; changed numerical and
photo resources are regenerated. Supplemental checks all passed, including deterministic release packaging, source-input failure injection, text/catalog checks, handbook links, regenerated figures/photos, native benchmarks, MOV conversion, icons, fonts, intro video and language routing. The benchmark worker also needed its published Direct label mapped to Blender’s existing QUINTIC enum. Exact supplemental checks appear in
`supplemental-validation.json` alongside this report.

## Limits

Buck2 cannot launch in this environment because `/proc/self/exe` is unavailable.
The dependency/action graph and deterministic packaging are checked separately;
run `buck2 build //:release '//:docs_deploy[zip]'` and
`buck2 test //... -j 2 -- --timeout 1800` on a supported host for the release gate.

Resolve's UI parser and native Metal/CUDA/OpenCL execution were not available.
The OpenCL syntax subcheck reports a skip because clang is unavailable. CPU
DCTL compilation, Metal reserved-name checks and helper-scope compilation pass.
Blender tests use CPU rendering, not a desktop GPU certification.

The inverse test is a regular-branch mathematical demonstration. It is not a
production inverse-LUT baker, an exhaustive preimage search, or a convergence
proof for arbitrary signed/fallback cases. These constraints and implementation
requirements are retained in the full math specification.

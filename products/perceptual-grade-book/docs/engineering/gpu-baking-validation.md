# Installed GPU LUT baking validation — 1.23.0

The extension automatically selects Blender compute shaders for nonlinear Grade and Grade Stack LUTs on a supported physical graphics device. This report measures the installed numerical code, including fixed 1024×128 dispatch textures, nested-grid reuse and pooled device-flagged CPU recovery. No external GPU package or precompiled extension binary is shipped.

## Validation scope

The pinned Python 3.13.15 / BPy 5.2.2 LTS / NumPy 2.5.3 authoring-preview runtime used Mesa llvmpipe (LLVM 20.1.2), OpenGL: a **software renderer**. The fixture explicitly permits software devices; installed automatic selection rejects them. These timings cannot establish Apple Metal or other physical-device performance, a tenfold gain, desktop responsiveness, or the Buck2 release gate.

The installed integration fixture passed **54 checks**, including automatic acquisition, unchanged render engine, program retention, exact shared vertices, large/partial dispatches, worker rejection, pooled flagged/nonfinite recovery, cancellation, timer-only publication, coalescing, edits after completion, stale/cache-hit rejection, context loss, CPU fallback, foreground save/render completion, native Shader and encoded Compositor output/alpha, normal save and full unregister. An interactive scheduling boundary is emulated with real GPU objects and RNA; physical desktop drawing is still a separate check.

The independent GPU arithmetic fixture passed **39 checks** across eight whites, Fits −2/0/6, narrow curves, neutral/black/signed/HDR and photographic inputs. The updated Stack editing suite passed **53 pytest cases**. CPU progressive, Grade Stack, registration and extension-namespace fixtures also passed. Package validation checks the actual ZIP contents, hashes, catalogs and absence of native dependency binaries. The build declaration audit passed; it does not execute Buck2.

## Three fresh warm numerical bakes per workload

| Workload | CPU median | GPU-path median | Ratio | 33³ preview median | CPU repair median |
|---|---:|---:|---:|---:|---:|
| One inverse Grade | 4.656 s | 1.704 s | 2.73× | 0.407 s | 0.726 s |
| Forward → inverse → forward | 4.308 s | 0.826 s | 5.21× | 0.125 s | 0.043 s |
| Three forward Grades | 2.244 s | 0.467 s | 4.81× | 0.060 s | 0.000 s |

First-case shader creation plus driver/layout warm-up was **42.81 s**, including 3.09 s reported by shader creation. Warm measurements include upload/readback, complete analytic math, all inverse iterations, pooled CPU recovery, AP1 conversions and float32 cube storage. They exclude imports, evaluator construction, UI debounce/frame gaps, image packing/publication and rendering. Timings vary substantially on this shared host; all runs are retained.

The single-inverse case repaired 93 vertices per settled pair; the mixed Stack repaired 74; the forward Stack repaired none. Only device-flagged vertices enter the CPU pool. Every run evaluated 274,625 vertices and reused all 35,937 shared vertices bit for bit. CPU repair still contributes materially to inverse time. These results do **not** meet a universal tenfold speedup; measure the physical target device before claiming that goal.

The Grade parameters use the installed canonical Rec.709 grading basis with D65 Grade white, preserving the study’s XYZ correction matrices. This differs from the historical 1.22.0 experiment’s Rec.2020 Grade basis and repair policy; its timing/error tables are not an identical-workload comparison. The AP1/ACES [0,128] log1p κ=.01 sampling grid is unchanged.

## Photographic RGB and ACES 2.0 comparison

Four IMG_* fixtures each contribute 512 deterministic samples at −6/0/+6 stops, or 6,144 input samples per workload before domain filtering. Absolute RGB uses exact Stack inputs in Rec.2020/D65 [0,10]³. Display metrics use exact inputs in AP1/ACES [0,128]³. Both masks are independent and fixed at exact input; samples outside both are excluded. The four actual OCIO ACES 2.0 outputs use D65 creative white. GPU arithmetic, CPU LUT and GPU LUT are evaluated against the complete float64 reference separately.

These are the **largest per-case p99** over fixture × exposure × workload, not pooled percentiles or maximum-pixel errors. Rendered RGB is emitted-light RGB in nits.

| Metric | CPU LUT | GPU LUT |
|---|---:|---:|
| Rec.2020 absolute RGB | 0.03229084 | 0.03230815 |
| SDR100_Rec709 rendered RGB (nits) | 0.26009453 | 0.26017623 |
| SDR100_P3D65 rendered RGB (nits) | 0.22975186 | 0.22976622 |
| HDR1000_P3D65 rendered RGB (nits) | 1.42822626 | 1.42817760 |
| HDR1000_Rec2020 rendered RGB (nits) | 1.33999048 | 1.33949472 |
| SDR100_Rec709 ΔE_ITP | 1.64315549 | 1.64316232 |
| SDR100_P3D65 ΔE_ITP | 1.64315545 | 1.64316163 |
| HDR1000_P3D65 ΔE_ITP | 1.89368243 | 1.89368685 |
| HDR1000_Rec2020 ΔE_ITP | 1.89368216 | 1.89368754 |

GPU arithmetic alone had worst per-case p99 ΔE_ITP **0.00070350**. Interpolation dominates the reported LUT percentiles in this sample. Complete distributions, maxima, code values, luminance errors, fixture/view fingerprints and eligibility counts remain in JSON/CSV. These samples do not provide an error bound for arbitrary grades, strong folds or other devices.

Native Shader and Compositor normalized errors against the actual GPU-baked cube were respectively 3.94e-08 and 3.06e-07. Compositor alpha passed unchanged. Those are native CPU-render sampling checks of GPU-produced data; they are distinct from physical GPU rendering.

## Selection, precision and lifecycle

The sidebar shows the actual bake backend/device or CPU reason. This is independent of Cycles CPU/Metal preferences and the compositor render device. Matrix-only work, singular inverse matrices, software devices and unavailable/failed GPU contexts use CPU. Warm programs survive edits and ordinary undo/load resets. Unregister releases programs and drawing hooks. Foreground save/render completion uses CPU for unfinished work because those callbacks have no guaranteed drawing context; already completed current GPU cubes are reused. Matching GPU preview vertices and their audits are preserved during CPU refinement.

The float32 policy is `analytic-f32-relative3e-6-audited-v1`: residual scale max(1e−12, max(abs(target))), cutoff 3e−6, full-forward RGB recovery and a conservative device audit. A flagged vertex is reevaluated through the entire float64 CPU Stack. Flagged rows share one CPU pool per preview/refinement phase and cannot publish unrepaired. GPU diagnostics do not assert the CPU’s 2e−8 tolerance for unflagged vertices. The forward/inverse handbook defines all equations and diagnostics.

## Reproduction

```sh
buck2 test //:gpu_solver_math //:gpu_baking
buck2 run //:gpu_solver_benchmark -- \
  --blender /Applications/Blender.app/Contents/MacOS/Blender \
  --output /absolute/path/to/results/gpu-solver-performance.json \
  --full-grid --progressive --repeats 3 \
  --fixture-samples 2048 \
  --analysis-pythonpath /absolute/path/to/locked-analysis-wheels
```

`--repeats 3` means three fresh timed bakes, not three inverse iterations. Software correctness runs require explicit `--allow-software`. A cached Buck build output is an earlier timing result. Shader/driver cold costs, warm numerical time and publication/render time are different measurements. The source package retains the exact evaluated-source snapshots and all raw tables.

Files in the handbook downloads: `gpu-baking.json`, `gpu-baking-performance.json`, `gpu-baking-performance.csv`, `gpu-baking-photographic-errors.csv`. Source evidence is under `validation/gpu-baking/`.

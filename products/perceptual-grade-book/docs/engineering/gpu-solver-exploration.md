# GPU inverse-bake exploration (1.22.0 historical record)

This report describes the frozen 1.22.0 prototype. The 1.23.0 installed path, fixed dispatch layout and flagged CPU repair are documented in [the current integration report](gpu-baking-validation.md). Historical timing and precision tables below retain their original scope.

An inverse bake can run as a vertex-parallel compute program through Blender’s GPU API. The tested prototype keeps regular reconstruction, scalar H–K/Tone inverses, full-forward RGB recovery and every Grade in a Stack on the device. It reads the table once per phase and reuses all 33³ common vertices in the final 65³ table. The installed extension continues to use the verified CPU solver.

## Measured performance and its limits

These are three fresh warm runs on Blender 5.2.2 LTS, Python 3.13.15 and NumPy 2.5.3. The renderer was Mesa llvmpipe (LLVM 20.1.2), OpenGL: a software renderer. No physical GPU was available. Ratios describe this compute-API implementation on that renderer; they cannot establish NVIDIA, AMD, Intel or Apple GPU performance. The fixed-capacity parameter layout and all source fingerprints are retained in the JSON.

| Workload | CPU median | Compute-path median | Ratio | 33³ preview median |
|---|---:|---:|---:|---:|
| One inverse Grade | 5.345 s | 0.664 s | 8.05× | 0.094 s |
| Forward → inverse → forward | 5.472 s | 0.432 s | 12.66× | 0.085 s |
| Three forward Grades | 1.685 s | 0.216 s | 7.81× | 0.027 s |

Timing includes the nested preview/refinement pair, AP1 coordinate conversion, parameter/input packing, texture creation/upload, all device solves, readback and float32 cube storage. Exactly 274,625 vertices are evaluated per settled pair. Shared vertices are bit-for-bit reused. Evaluator construction, process/imports, UI debounce, Blender image publication and rendering are excluded. Timing variation is substantial on this shared host; all repetitions are retained.

Cold first use was **55.53 s**, including 4.63 s reported by shader creation and deferred driver work in the first dispatch. The shader program and parameter capacity must persist across edits; recompiling per bake would erase the warm gain. With the stable parameter texture layout, the first mixed-Stack warm-up took 0.462 s and did not repeat the cold layout cost. The cold cost also needs measurement on physical GPUs.

The 10× target is plausible for warm GPU bakes, but this experiment does not establish at least 10× for every workload, cold first use, or a physical GPU. The repeated single-inverse ratio was 8.05×; the mixed Stack was 12.66×. An earlier single run measured 11.09×/11.35× for those workloads. Keep both records instead of selecting only favorable repetitions.

## Solver and precision

The forward shader evaluates the analytic curves, p=2 C/J_A drivers, Hue/Concentration, Adaptance, H–K repair, signed lifting and Tone-only fallback. It shares matching kernel Fits and omits inactive coefficient families. Stage-1 matrices and their inverses are constructed in float64 on the CPU, then uploaded as float32. There is no intermediate sampled curve or Grade LUT.

The regular inverse solves log(J_A), log(C), reconstructs hue analytically, applies the fixed-reference scalar guard inverse, and undoes Tone with bracketed Newton. The GPU uses finite-difference Jacobian recovery and damped Broyden updates. Candidates pass the complete float32 nonlinear forward path. Unresolved vertices use three-dimensional target-relative RGB Broyden recovery with best-candidate/target/half-target seeds. This is a bounded best-effort inverse, not a closed-form inverse or a proof of unique preimages.

The GPU cutoff is 3e-6 against max(1e-12, max(abs(target))). The achromatic guard and tone scalar solves use float32-sized thresholds. The CPU retains its original policy: internal candidate scale 2e-10 and diagnostic tolerance 2e-8 against 1 + max(abs(target)). These are different numerical contracts. Near-black relative accuracy matters: a first prototype using the CPU normalization with a float32-sized cutoff skipped dark adjustments. Relative stopping removed that defect.

For the final full grid, 12,255 inverse vertices and 12,086 mixed-Stack vertices entered full RGB recovery (about 4.5% of the grid). Eighteen and twelve respectively remained above the conservative device audit cutoff. The device flags are based on its float32 forward evaluator; independent CPU checks remain the quality authority. The largest normalized stored-vertex differences from the CPU path were 4.26e-6 for the inverse, 8.01e-6 for the mixed Stack and 2.93e-5 for the forward Stack.

Almost all GPU preimages exceed the CPU’s much tighter 2e-8 diagnostic cutoff. The optional repair probe verifies every vertex, performs four float64 refinement iterations and applies the full CPU search to remaining rows. Median combined dispatch/readback/repair time was 4.86 s for the inverse, compared with 5.34 s for its CPU bake. This conservative hybrid does not approach a 10× gain. Repairing only device-flagged vertices would use a different quality policy; it was not measured or enabled here.

## Photographic RGB and ACES 2.0 error

The same 512 deterministic stored pixels per IMG_* fixture were evaluated at −6, 0 and +6 stops, for inverse, mixed-Stack and forward-Stack workloads: 6,144 input samples per workload, before independent domain filtering. This is a sampled study, not every original-image pixel. Fixtures and parameters are fingerprinted. Absolute RGB uses exact Stack inputs inside Rec.2020/D65 [0,10]³. Display metrics use exact inputs inside AP1/ACES [0,128]³. Inputs outside both masks are excluded. Eligible/excluded counts are in JSON.

All views use the actual pinned OCIO ACES 2.0 built-ins with D65 creative white: SDR 100 nits Rec.709/BT.1886, SDR 100 nits P3-D65/sRGB, HDR 1000 nits P3-D65/PQ and HDR 1000 nits Rec.2020/PQ. Arithmetic error and LUT interpolation error are separate. The current native AP1 0…128 log1p κ=.01 grid and physical-linear tetrahedral interpolation are unchanged.

The table shows the largest per-case p99 across image × exposure × workload. It is not a pooled percentile or maximum-pixel error. “Rendered RGB” is emitted-light RGB in nits; dividing by peak nits gives the existing peak-normalized metric.

| Metric | CPU-baked LUT | GPU-baked LUT |
|---|---:|---:|
| Rec.2020 absolute RGB | 0.03229084 | 0.03229742 |
| SDR100_Rec709 rendered RGB, nits | 0.26009453 | 0.26013285 |
| SDR100_P3D65 rendered RGB, nits | 0.22975186 | 0.22973664 |
| HDR1000_P3D65 rendered RGB, nits | 1.42822626 | 1.42875632 |
| HDR1000_Rec2020 rendered RGB, nits | 1.33999048 | 1.33945808 |
| SDR100_Rec709 ΔE_ITP | 1.64315549 | 1.64315032 |
| SDR100_P3D65 ΔE_ITP | 1.64315545 | 1.64314919 |
| HDR1000_P3D65 ΔE_ITP | 1.89368243 | 1.89367707 |
| HDR1000_Rec2020 ΔE_ITP | 1.89368216 | 1.89367782 |

In this sample, worst-case p99 absolute scene RGB changed by +0.0204%; the largest change in the reported rendered-RGB p99 values was +0.0371%. GPU arithmetic alone had worst per-case p99 ΔE_ITP ≤0.000722 across the four outputs. These data support further float32 GPU development. They do not establish an error bound for arbitrary grades, extreme folds, singular matrices or other devices. Encoded RGB, luminance, maximum errors and complete distributions remain in the JSON/CSV.

## Recommended production design

Keep one persistent shader/program owner per Blender GPU context. Supply edited Grade parameters through a stable-capacity texture, coalesce edits, dispatch the 33³ preview pool, then dispatch only remaining 65³ vertices after settling. Publish only results matching the current Grade/Stack signature, with exact shared-vertex reuse and device audit counts. Keep the existing CPU evaluator for independent verification, unsupported/no-context operation and chosen difficult-vertex recovery. No external CUDA/OpenCL package or native extension binary is needed.

GPU calls require a valid Blender GPU context. They cannot simply replace NumPy calls inside the current arbitrary Python bake worker. Desktop integration must schedule the GPU work in a supported context, preserve user scene/render state, cancel stale jobs and avoid blocking interactive edits during cold compilation or synchronous readback. The custom RenderEngine in the benchmark only supplies an isolated test context; it is not a proposed user-facing render engine. Headless render/save and concurrent-render behavior require explicit integration tests.

Use independent absolute-RGB and ACES-rendered error budgets to assess the float32 path. Retaining the full CPU residual contract requires broad repair and loses most of the speed benefit in this test. Device-flagged recovery plus independent image-error validation is a candidate for a fast path, still requiring stronger Grade coverage and hardware measurements before being enabled. Portable float64 GPU support is not assumed.

## Reproduction and validation

The handbook’s Testing chapter documents `//:cpu_solver_benchmark`, `//:gpu_solver_math`, `//:gpu_solver_smoke` and the fresh desktop `//:gpu_solver_benchmark` command. Pass `--full-grid --progressive --repeats 3 --repair`; add `--fixture-samples 2048 --analysis-pythonpath <locked-analysis-wheels>` for a larger photographic study. GPU shader compilation, first dispatch, warm bakes and CPU repair are emitted separately. A cached Buck action is an earlier timing result, so use the executable benchmark to collect new timings.

This environment ran the pinned Python/BPy authoring-preview fixtures, including 44 derivative checks, 80 before/after accuracy checks, existing inverse/forward/chroma/concentration/nested-grid checks, native Grade Stack and 53 Stack-editing pytest cases. The opt-in GPU arithmetic fixture passed 39 checks across all eight whites, Fit −2/0/6 including narrow kernels, identity, black, neutral/signed/HDR and photographic samples. Buck2 was unavailable; the registered Buck build/dependency gate and real Metal/Vulkan/hardware integration remain pending.

Files: `gpu-solver-performance.json`, `gpu-solver-performance.csv`, `gpu-solver-photographic-errors.csv`; exact evaluated code is retained under `validation/gpu-solver/stable-layout/evaluated-source/` in the source package. Earlier prototypes remain experiment records only. GPU tools/test fixtures are outside `src/blender/` and excluded from the installed extension.

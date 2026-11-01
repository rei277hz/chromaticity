# Picker assurance boundaries

Each extension installs private copies of reusable libraries and owns an explicit
App. Shared source does not create shared live state. See
[the shared App runtime](../../libraries/blender-runtime/README.md).

The picker uses handwritten Python policies for attempt, GPU health, retry,
startup and ownership, plus shared lifecycle and execution coordinators.
Owner-local `.inv` requirements are proved against those sources with Z3. Shared
actor-owned Stores validate admitted inputs and generated runtime contracts;
the Blender adapter retains exact App/Store identities and physical retirement.
Native observations remain explicit premises with separate integration checks.

Packaging checks the final ZIP inventory and exact bytes against declared source
inputs and requires proofs bound to the shipped policies and generated contracts.
Unsafe paths, destination conflicts, missing or altered source members,
and build/proof payloads reject the archive. The ZIP contains private dependency
packages and product resources. The picker has no runtime JSON resources.
Archive integrity checks establish what is shipped, not its native correctness.

Picker math tests retain archived Rust output only for independent ACES2
forward-transform references; archived radial coordinates do not define the
current mapping. Current coordinate behavior is checked with round trips,
lightness independence, the D65 center, and the Buck2 fit report. GPU
conformance and installed Blender tests separately exercise display conversion,
brush writes, workers and independent extension lifecycles. Driver lifetimes,
Python finalizer scheduling and Blender internals remain beyond those finite
tests. The retained Grade Lean color-model theorems do not certify the picker's
different color model.

The former INVARIANT/Z3 machine proofs, receipts and unfinished Rocq migration
are historical material in the external `perceptual-grade-proof-archive`
directory beside the repository. They are not inputs to current packages and
do not certify the current Python.

```sh
buck2 test //tools/verification/tests:archive //products/hdr-color-picker-blender/tests:packaging
buck2 test //libraries/hdr-color-picker-core/tests:math
buck2 test //products/hdr-color-picker-blender/tests:native
buck2 test //libraries/blender-runtime/tests:app //libraries/blender-runtime/tests:physical_ownership
```

[Display limits](DISPLAY.md) retain the physical HDR, manual painting and
macOS/Metal acceptance gates.

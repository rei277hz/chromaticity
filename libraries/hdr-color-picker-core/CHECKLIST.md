# Picker Saturation Radius Checklist

- [x] Record the future-proof mapping, D65 center, workload weights, and fit
      objective in this component's documents.
- [x] Mark the Buck2 radius fitter as current and the legacy Rust fixture as
      archived; remove the superseded fixture generator.
- [x] Add a shared radius-independent XYZ-to-appearance extraction path.
- [x] Fit `K` and `A` from deterministic Rec.709 SDR, P3 HDR, and Rec.2020 HDR
      endpoint pairs through Buck2.
- [x] Replace the Python and GLSL radius mappings and reject exact unit-circle
      edge decoding.
- [x] Replace old finite-radius Rust conformance assertions with round-trip,
      lightness-independence, and D65-center checks; preserve independent ACES
      transform references.
- [x] Run the Buck2 fit generation and picker regression tests.

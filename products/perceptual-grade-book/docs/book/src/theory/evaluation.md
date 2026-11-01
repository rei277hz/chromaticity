# Evaluation and interpolation

The equations define one grade. Producing the same result in an analytic DCTL, a native node graph and a sampled color table also requires a valid inverse domain and controlled numerical approximations. This chapter follows those requirements from the end of Color to the returned linear color.

The [bounded H–K guard](hk-guard.md) repairs combinations of lightness and chroma that would otherwise leave the real inverse domain. Its historical evaluation explains how the current guard was chosen, with recorded experiments kept distinct from regenerated comparisons.

[Direct and sampled evaluation](lut.md) then explains the extension's curve tables, signed HDR sampling grid and physical-linear-RGB interpolation. It also distinguishes agreement with a sampler from agreement with the analytic grade: matching interpolation implementations does not remove the color table's approximation error.

The same current parameters must reach both paths. A completed LUT is accepted only for the grade that produced it, while forward nodes use Direct during preparation and inverse/Stack nodes retain their previous completed LUT. The [runtime architecture](../development/architecture.md) explains how the extension maintains that agreement during interaction.

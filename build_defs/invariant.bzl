"""Source-bound shared Invariant proofs and external package evidence."""

InvariantProofInfo = provider(fields = {
    "proof": provider_field(Artifact),
    "inputs": provider_field(Artifact),
    "runtime_source": provider_field(str),
    "runtime_contracts": provider_field(str),
})

def _proof_impl(ctx):
    inventory = ctx.actions.write_json("inventory.json", {
        "version": 1,
        "properties": sorted(ctx.attrs.required_properties),
        "witnesses": sorted(ctx.attrs.required_witnesses),
        "mutations": sorted(ctx.attrs.required_mutations),
    })
    inputs = ctx.actions.copied_dir("inputs", {
        "source.py": ctx.attrs.source,
        "requirements.inv": ctx.attrs.requirements,
        "inventory.json": inventory,
        "verifier": ctx.attrs.verifier_sources[DefaultInfo].default_outputs[0],
        "solver/z3.whl": ctx.attrs.solver[DefaultInfo].default_outputs[0],
    })
    output = ctx.actions.declare_output("proof", dir = True)
    args = cmd_args(
        ctx.attrs.verifier[RunInfo],
        ctx.attrs.source,
        ctx.attrs.requirements,
        "--output",
        output.as_output(),
        "--input-closure",
        inputs,
        "--timeout-ms",
        str(ctx.attrs.timeout_ms),
    )
    for flag, names in [
        ("--require-property", ctx.attrs.required_properties),
        ("--require-witness", ctx.attrs.required_witnesses),
        ("--require-mutation", ctx.attrs.required_mutations),
    ]:
        for name in names:
            args.add(flag, name)
    ctx.actions.run(args, category = "invariant_proof", identifier = ctx.label.name)
    return [DefaultInfo(default_output = output, sub_targets = {
        "receipt": [DefaultInfo(default_output = output.project("receipt.json"))],
        "report": [DefaultInfo(default_output = output.project("report.json"))],
        "validators": [DefaultInfo(default_output = output.project("validators.py"))],
        "inputs": [DefaultInfo(default_output = inputs)],
    }), InvariantProofInfo(
        proof = output,
        inputs = inputs,
        runtime_source = ctx.attrs.runtime_source,
        runtime_contracts = ctx.attrs.runtime_contracts,
    )]

invariant_proof = rule(impl = _proof_impl, attrs = {
    "source": attrs.source(),
    "requirements": attrs.source(),
    "required_properties": attrs.list(attrs.string(), default = []),
    "required_witnesses": attrs.list(attrs.string(), default = []),
    "required_mutations": attrs.list(attrs.string(), default = []),
    "runtime_source": attrs.string(),
    "runtime_contracts": attrs.string(),
    "timeout_ms": attrs.int(default = 10000),
    "verifier": attrs.exec_dep(default = "//libraries/invariant:verifier", providers = [RunInfo]),
    "verifier_sources": attrs.dep(default = "//libraries/invariant:verifier_sources"),
    "solver": attrs.dep(default = "//third_party:z3-solver_wheel"),
})

def _bundle_impl(ctx):
    files, manifest = {}, {}
    validators, names = [], []
    for dependency in ctx.attrs.deps:
        info = dependency[InvariantProofInfo]
        name = str(dependency.label)
        if name in names:
            fail("Duplicate proof dependency: " + name)
        names.append(name)
        prefix = str(len(manifest))
        if info.runtime_contracts in validators:
            fail("Duplicate runtime contract destination: " + info.runtime_contracts)
        validators.append(info.runtime_contracts)

        # One production module can carry several independently checked
        # policies. Each still needs its own receipt and generated contracts.
        manifest[name] = {
            "path": prefix,
            "runtime_source": info.runtime_source,
            "runtime_contracts": info.runtime_contracts,
        }
        files[prefix + "/proof"] = info.proof
        files[prefix + "/inputs"] = info.inputs
    files["manifest.json"] = ctx.actions.write_json("manifest.json", {"version": 1, "machines": manifest})
    return [DefaultInfo(default_output = ctx.actions.copied_dir("evidence", files))]

invariant_bundle = rule(impl = _bundle_impl, attrs = {
    "deps": attrs.list(attrs.dep(providers = [InvariantProofInfo])),
})

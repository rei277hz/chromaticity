# Invariant

Invariant is a build-time verifier for small, pure Python state machines. It
checks the handwritten implementation against a separate `.inv` specification
and emits proof evidence. It does not provide a runtime machine, state store,
actor system, or generated runtime contract layer.

## Source and requirements

Each proof binds a Python source file to a versioned JSON `.inv` file. The source
defines frozen state, event, and effect records, initializer functions, and a
pure `step(state, event)` reducer. Requirements declare invariants, function
contracts, properties, witnesses, mutation controls, and loop annotations. The
verifier reads the Python AST, generates Z3 obligations, and reports whether each
obligation has its expected result.

`Event.kind` should use `Literal[...]` so preservation is checked separately for
each event kind. Absence uses `Optional[T]` and `None`. The source subset supports
immutable scalar values and records, fixed and variadic tuples, local
assignments, conditionals, constructors, `dataclasses.replace`, and acyclic pure
helpers. Annotated loops over immutable tuples or `range(n)` are checked with
inductive invariants and decreasing measures. Unsupported syntax and imports are
rejected rather than approximated.

Properties express safety claims over symbolic inputs. Witnesses demonstrate
that a useful behavior is reachable. Mutation controls alter a selected source
expression and require a named property to produce a concrete counterexample;
this checks that the property can detect the class of regression it claims to
cover.

## Build and evidence

The lifecycle example is [lifecycle.py](src/lifecycle.py), specified by
[lifecycle.inv](requirements/lifecycle.inv). From the repository root:

```sh
buck2 build //libraries/invariant:lifecycle_proof
buck2 test //libraries/invariant:tests
```

The verifier target can also be run directly:

```sh
buck2 run //libraries/invariant:verifier -- \
  libraries/invariant/src/lifecycle.py \
  libraries/invariant/requirements/lifecycle.inv \
  --require-property reclaim_waits_for_terminal \
  --output /tmp/invariant-lifecycle-proof
```

Proof output includes inspectable solver obligations, a report, and a receipt
binding the source, requirements, verifier, solver, and report identities. It
contains no generated runtime validator. Buck's `invariant_proof` target checks
the source and requirements during the build; consumers that execute the policy
remain responsible for runtime integration and host-boundary behavior.

Expressions in requirements are parsed as restricted Python ASTs; neither source
verification nor requirement evaluation uses `eval`. The proof covers the
modeled source behavior and declared claims. It does not prove host callbacks,
external effects, scheduler fairness, native resource behavior, or operating
system behavior.

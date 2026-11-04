# Invariant

Invariant is a build-time verifier for small, pure Python state machines. It
checks the handwritten implementation against a separate `.inv` specification
and emits proof evidence. It does not provide a runtime machine, state store,
actor system, or generated runtime contract layer.

## Source and requirements

Each proof binds a Python source file to a versioned JSON `.inv` file. The source
defines frozen state, event, and effect records, initializer functions, and a
pure `step(state, event)` reducer. Requirements declare invariants, function
contracts, properties, witnesses, and mutation controls. The
verifier reads the Python AST, generates Z3 obligations, and reports whether each
obligation has its expected result.

A policy may use named transition properties without declaring state invariants.
This avoids adding redundant state just to satisfy the proof format.

`Event.kind` should use `Literal[...]` so preservation is checked separately for
each event kind. Absence uses `Optional[T]` and `None`. The source subset supports
immutable scalar values and records, fixed and variadic tuples (including nested
records), scalar `Optional[str]`, `Optional[int]`, and `Optional[bool]`, local
assignments, conditionals, constructors, `dataclasses.replace`, and acyclic pure
helpers. Collection scans, filtering, slicing, indexing registries, and list
updates belong in ordinary runtime code and are covered by tests. Policies
receive the resulting observations and decide whether an operation is allowed.
Collection bookkeeping is a trusted premise, outside the formal proof boundary.
Bounded quantifier and aggregation operators and loop annotations are not
supported. Unsupported syntax and imports are rejected rather than approximated.

Properties express safety claims over symbolic inputs. Witnesses demonstrate
that a useful behavior is reachable. Mutation controls alter a selected source
expression and require a named property to produce a concrete counterexample;
this checks that the property can detect the class of regression it claims to
cover.

Established input assumptions guide symbolic expansion. The verifier skips a
branch only when contextual simplification proves its full path condition false;
inconclusive simplification keeps the branch. Surviving paths retain their
original guards. Each assumption is evaluated under earlier assumptions only,
and its safety and the satisfiability of the premises are still checked
separately. Assertions and unproved postconditions never become pruning facts.

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

Conjunctive claims can be checked as separate solver cases under the same
premises. Every case must be proved; a timeout remains a failed proof. Reports
record the case results and retain the complete original solver obligation.

Expressions in requirements are parsed as restricted Python ASTs; neither source
verification nor requirement evaluation uses `eval`. The proof covers the
modeled source behavior and declared claims. It does not prove host callbacks,
external effects, scheduler fairness, native resource behavior, or operating
system behavior.

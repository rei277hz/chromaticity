# Architecture

## Runtime Ownership

| Area | Owner | Responsibility |
|---|---|---|
| Add-on entry and composition | `src/__init__.py`, `src/application.py` | Public Blender registration API, callback-router construction, Grade feature startup, and image invalidation entry point |
| Blender callback ownership | `src/host/callbacks.py` | Register and remove handler callbacks by feature owner, and route timer operations through Blender's host APIs |
| Grade behavior | `src/features/grade/` | Grade settings, graph readiness, parameter-bank publication, color authoring, node conversion, preparation, and Grade-owned final-appearance endpoint resolution |
| Bake behavior | `src/features/bake/` | Bake eligibility and route discovery, input freshness, foreground job ownership, image publication, and Bake graph wrappers |
| Vectorscope behavior | `src/features/vectorscope/` | Scope capture requests, latest-demand freshness, analysis, presentation, editor interaction, and drawing |
| Gesture behavior | `src/features/interaction/` | Gesture admission and coordination used by Grade controls and the Gizmo |
| Shared Blender runtime | `src/runtime/` | Host-neutral lifecycle, publication, resource, worker, and capture primitives used across features |
| Numerical and graph preparation | `src/kernel/` | Grade settings and numerical preparation, runtime template binding, and generated kernel interfaces |

The public extension API is the package root. Internal callers import the
feature that owns the behavior. The removed `src/nodes.py` facade must not be
reintroduced as a second public entry point.

`application.py` creates one `HostCallbackRouter` and passes it into Grade
registration. Grade, Bake, and Vectorscope use that router for their Blender
handler and timer registrations. Handler registrations carry an owner key, so
one feature can release its callbacks without removing another feature's
registrations. Failed removals remain owned and can be retried during teardown.
The composition root orders shutdown across features. It closes Grade
publication admission, withdraws Bake and Vectorscope demand, retires the shared
capture helper, then finishes and unregisters each feature. Any shutdown error
keeps the runtime references needed by an application-owned timer retry.

The Grade host adapter remains the Blender-facing integration point for node
types and their lifecycle callbacks. Supporting responsibilities have owners
beside it. Parameter publication is in `features/grade/publisher.py`, resource
and preparation services are in their corresponding Grade modules, and pure
decision logic is in `features/grade/policy/`. A policy's returned effects
authorize external mutations, and runtime adapters apply those effects.
Grade exposes its admission boundary and registration operations. Bake and
Vectorscope shutdown remain owned by their feature packages and are composed by
`application.py`.

Bake and Vectorscope own their route decisions. `runtime/capture_graph.py`
contains reusable graph traversal and fingerprint primitives. Callers provide
feature-specific eligibility checks explicitly, so a shared observation does
not acquire one feature's policy by implication. Grade owns the final
appearance endpoint contract consumed by Vectorscope capture.

## Change Path

1. Draft behavior in the owning feature package and keep its Blender adapter
thin around the feature's state and policy.
2. Extract a primitive into `runtime/` only when multiple features need the
same contract and neither feature's eligibility rules need to become implicit.
3. Put Blender handler and timer ownership behind `HostCallbackRouter`, while
keeping callback behavior with the feature that responds to the event.
4. Keep formal policy requirements beside feature-owned policy modules. Build
the installed extension and exercise behavior through the existing product
test categories.

The extension ZIP is the runtime boundary. `tools/` contains template emitters,
packaging, and report code. Runtime feature modules belong under `src/` and
are discovered by the Buck extension target. Proof requirements are build
inputs and are not shipped as runtime modules.

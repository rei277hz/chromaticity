# Blender host runtime

This adapter owns common Blender application services used by Perceptual Grade
and HDR Color Picker: execution helpers, native ownership, registration, and
lifecycle coordination. It depends on the generic Invariant framework and contains
no Grade model, bake, scope, or picker UI implementation.

## Application and Store ownership

Each product constructs an explicit `App` and retains its own Session. Execution
helpers are created lazily; native ownership and registration stay in this
adapter. There is no module-global current/default App, runtime or arena registry.
Two Apps may share imported framework code and policies without sharing state.

Each App creates its own scheduler thread and shared-framework ActorSystem when
its first Store is constructed. Host Stores refer to task-owned framework Stores;
they hold ActorRefs and envelope identities, not a second mutable automaton state.
The shared Machine and Store remain the only transition and commit authority.
The adapter retains App/Store envelope identities and exposes synchronous
foreground admission, preview and queries. Foreground Blender mutations stay on
the main thread; isolated helpers execute their own native work. Type/precondition
rejection does not poison an actor. Invalid model results fence the actor and App;
native operation failures retain the owning protocol's repair obligations.
Timeout retains the original request and future, fencing admission and publication
until reconciliation determines its exact outcome. It cannot authorize retry or
rollback.

For a consumer policy defining `initial(owner)`, `current(state)` and its event
type, bind the policy and selected functions explicitly:

```python
from color_tools.blender_runtime import App, Machine

app = App(package=package_path, storage_name="example")
machine = Machine(policy_module, initializers=("initial",), queries=("current",))
store = app.store(machine=machine, initial={"owner": 1})
prospective = store.preview(event)  # Transition(state, effects), no commit
effects = store.dispatch(event)    # waits for the actor-owned commit
value = store.query("current")    # uses the current state
```

Machines capture the source functions. Input types and policy preconditions are
checked atomically in the owner task. See [Invariant](../invariant/README.md)
for source-bound proofs and unbounded loop verification.

Effects are immutable semantic data. Product adapters perform native work and
dispatch observations against the Store's current state, since callbacks or Undo
may re-enter between action and observation. `store.event(event)` binds an event
envelope to the exact App and Store before native work. Foreign envelopes and
owner-qualified product tickets are rejected even when integer IDs collide.
Product output reservations and graph receipts carry transient App, Store and
incarnation identities; adapters check them before native writes or conversion
to semantic events. Store identity is never saved in a blend payload record.
A replaced scheduler Store rejects its former effect lease while allowing
compensation.

## Policies and execution helpers

The handwritten policies own attempt, GPU health, retry, startup, ownership
admission, transaction edge effects and native evaluation leases. Execution and
lifecycle coordinators compose them. Their
[leaf requirements](requirements/inventory.bzl) and
[coordinator requirements](requirements/coordinators/inventory.bzl) enumerate
the mandatory source-bound properties, witnesses and mutation controls.
Tuple counting retains duplicate occurrences and empty-input behavior.

The `native_evaluation` policy owns an unbounded immutable ledger of exact native
reader leases. Ordered ingress revisions prevent a cached ready observation from
admitting work while callbacks remain unprocessed. Candidate append/removal edits
are checked by inductive source proofs; unmatched or foreign completion receipts
cannot release another reader. Only a validated native replacement advances the
generation and clears old debt. Callback pairing, native-job observations and the
replacement receipt remain adapter responsibilities. Native callbacks should
enqueue scalar observations without waiting on the actor; foreground code commits
them before publishing a revision-bound readiness observation.

The native adapter validates physical outcomes before admitting receipts.
Cancellation keeps execution occupancy and snapshot leases until a terminal acknowledgement or
confirmed process exit. An active CPU crash spends only that attempt's retry
budget; queued peers retain their own budgets.

Helpers load their explicit dependency tree under a session-specific namespace
without importing an extension initializer. Dispatch module paths are relative
to that tree, and the operational handshake fingerprints it to reject mismatched
helper code and data. Foreground adapters freeze native resource snapshots and
own native publication; host-free numerical helpers receive immutable values and
captured arrays. Host-free execution and storage may perform process or filesystem
I/O; policy modules and designated mathematical models remain pure.

## Closure and native ownership

`App.close()` fences admission, shuts down physical execution, runs registered
retirement callbacks while actors remain alive, closes ownership, removes native
registration, and finally closes actors. Product components register
retirement hooks with `on_retired` to consume physical receipts before actor exit.
An outstanding borrow or failed cleanup retains its debt and leaves the App
fenced for a later cleanup attempt; reopening requires a fresh App. Products
retain their recovery and rollback ordering before terminal closure. Framework cleanup does not replace
Grade's native reader/recovery protocol. Closing one App leaves peer Apps usable.

An ownership context retains its App identity, arena registry and counters,
default arena, discovery prerequisites and native-key projection. Weak finalizers
refer weakly to their original arena, and `OwnedField` retains its holder's
original context; neither resolves a replacement through a mutable global
registry. Borrow accounting, reader barriers, exact native handles and detach
ordering remain explicit runtime responsibilities.

Ownership and consumer-handle finalizers can run on the actor thread during
garbage collection. They enqueue weak references and scalar identities for
foreground cleanup. App closure and explicit foreground pumps drain this queue;
finalizers neither wait on their own actor scheduler nor release native objects
on that thread. Pending physical retirement keeps the actors available for
the eventual cleanup receipt.

`OwnershipContext.observation()` batches reference resolution within one
synchronous host pass. It reuses immutable actor snapshots and the source-bound
ownership resolution predicate; physical cell membership is still checked on
every lookup. Boundary, phase, and terminal transitions revoke outstanding
observations before dispatch. Observations never retain native values or confer
publication authority, and cannot be used after the pass, from another thread,
or across native replacement. Mutable accounting and all transitions continue
to use the live Store.

## Build and tests

Run from the repository root:

```sh
buck2 build //libraries/blender-runtime:verify
buck2 test //libraries/blender-runtime/tests:app //libraries/blender-runtime/tests:execution_runtime
buck2 test //libraries/blender-runtime/tests:physical_ownership //libraries/blender-runtime/tests:isolation
```

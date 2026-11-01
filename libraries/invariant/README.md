# Invariant

Write executable automata in Python and requirements in separate versioned JSON
`.inv` files. The verifier reads the actual Python AST, generates Z3 obligations,
and emits reports, receipts, and runtime contract validators. It does not generate
the automaton implementation.

The self-contained example is [lifecycle.py](src/invariant/lifecycle.py) with
[lifecycle.inv](requirements/lifecycle.inv). Product consumers supply their own
source files and independent requirements; the framework does not generate or
replace their transition implementations.

## Authoring and execution

Define frozen dataclasses for state, events, and effects; typed initializers
returning the state; and `step(state, event) -> tuple[State, Effects]`. Documentation
strings and empty records using `pass` are admitted. Keep formal requirements
in the `.inv` file. `Event.kind` should
use `Literal[...]` to produce a distinct preservation check for every event kind.

The source subset supports `int`, `bool`, `str`, the tagged `int | str` identity
union, finite homogeneous `Literal` values, nested frozen records, fixed and
variadic immutable tuples, literal module constants, local assignments,
tuple unpacking, `if`, conditional expressions, returns, constructors,
`dataclasses.replace`, and acyclic pure helpers in the same module. Arithmetic
includes `+`, `-`, `*`, `//`, and `%`; Boolean operators and chained comparisons
preserve Python short-circuit behavior. Division requires a provably nonzero
divisor. Dynamic indexing proves Python's tuple bounds before access. Explicit
`raise ValueError("literal message")` paths must be unreachable under the declared
preconditions; exceptions outside that domain remain part of the source behavior.
Use concrete annotations with the runtime `Machine` API.

Finite string labels use solver enumeration constructors. Arbitrary identity
strings use exact Unicode codepoint sequences, including lone surrogates;
integers and strings remain distinct, and Boolean arguments are not integers.

Imports are limited to `dataclasses.dataclass`, `dataclasses.replace`,
`typing.Literal`, and postponed annotations for verification-only consumers.
Annotated `for` loops over immutable tuples or `range(n)` are supported as
specified below. Nested source loops, `break`, `continue`, recursion, mutation,
methods, dynamic calls, external helper imports, and unsupported syntax are
rejected, including unsupported unreachable statements.

The Buck runtime target packages generated lifecycle contracts:

```python
from invariant import Machine, Store
from invariant import lifecycle, _lifecycle_contracts

machine = Machine(lifecycle, contracts=_lifecycle_contracts)
store = Store(machine)
effects = store.dispatch(lifecycle.Event('start', 1))
```

`Store` belongs to its creating thread. `preview(event)` checks a transition
without committing it; `dispatch(event)` checks and commits state before returning
effects. The application executes those effects and returns outcomes as events.
Rejected contracts raise `ContractError` before commit. Declared initializers and
queries are selected through `Machine(..., initializers=(...), queries=(...))`;
`Store.query(name, **arguments)` supplies the current state.

`ActorSystem` gives each automaton its own asyncio task, private `Store`, and
mailbox. Create the system on a running event loop and call
`system.spawn(name, machine, arguments={...})`. `await ref.dispatch(event)` returns
the effects after the owner task validates and commits the transition. Peer
messages, completion receipts, timers, and explicit continuation events enter the
same FIFO inbox. Each completed turn yields to other tasks. Mailboxes preserve
every event; they do not coalesce terminal receipts or impose an admission limit.

Supply a brief synchronous `on_effects(ref, effects, state)` router to `spawn`.
It can call another actor's `tell(event)`, `system.schedule(ref, event, delay)`, or
`system.run_effect(ref, awaitable, success=..., failure=...)`. Both completion
factories return the model's own event type. Blocking work belongs in an executor
or process; merely placing it in an async function does not make it nonblocking.
The physical adapter must distinguish a result from confirmed writer retirement.

Commit a conservative state before starting a physical effect. If routing throws,
`on_failure(ref, event, effects, error)` can return an explicit failure event for
the same mailbox. The framework never restores an earlier state. Invalid committed
transition candidates, missing failure adapters, or failures while handling a
failure receipt fence the actor and invoke the system's synchronous
`on_fault(ActorFault)` callback. A supervisor can notify another actor or the host;
it chooses the application-specific repair and resource policy.

Use `await ref.snapshot()`, `await ref.preview(event)`, and
`await ref.query(name, **arguments)` to request owner-task reads. Preview returns
the immutable candidate state and effects without committing or routing them.
Snapshots from separate actors are independent observations, not a joint atomic
snapshot. `ref.tell(event)`, `snapshot_threadsafe()`, `preview_threadsafe(event)`,
and `query_threadsafe(...)` return `concurrent.futures.Future` objects and can be
called by native or UI threads. Do not block the scheduler thread on their
`.result()` methods. Actor stores reject access by another task, while standalone
stores retain their existing thread ownership rule.

For actors that own physical work, supply `close_event=...` (or a state-to-event
factory) and `is_closed=lambda state: ...` together. `await system.close()` sends
that event, continues processing receipts, waits for closed model states and
registered effects, then stops the loops. Shutdown does not cancel physical work.
An actor without a close protocol simply drains its inbox and registered effects.
Ordinary timers are removed after draining; a shutdown that needs a timer must
keep its model open until that timer's event is handled. Effect adapters must
await physical retirement when their receipt represents resource release.

`await ref.close()` or `ref.close_threadsafe()` applies that same close protocol
to one actor and removes it from the system after draining. Use this when a job
or resource lifetime ends; dropping a Python reference alone does not retire a
generic actor. Keep its reference until external ownership has transferred or
retired, and keep any final immutable snapshot needed for result history. Closing
one actor does not close its peers.

`App(service_factory, capacity=256)` creates a background coordinator. The
factory receives an `emit(event)` callback and returns a service with asynchronous
`start()`, `handle(command)`, `tick()`, and `close()` methods. Call `post(command)`
to receive a request ID, `poll(max_events=64)` to drain notifications, and
`close_async()` to receive a shutdown `threading.Event`. Admission raises
`BackpressureError` when capacity is exhausted. Progress/snapshot notifications
are coalesced; callers must keep polling acknowledgements to release admission
capacity. Service processing and shutdown stay on the coordinator.

## Unbounded loop proofs

Every source loop needs a matching root `loops` declaration. For a function
`count(values: tuple[int, ...], selected: int) -> int` that initializes `total = 0`,
counts matching elements in `for item in values`, and returns `total`:

```json
{
  "name": "count_prefix",
  "function": "count",
  "target": "item",
  "iter": "values",
  "cursor": "processed",
  "invariants": [
    "total == sum_range(i,0,processed,1 if values[i] == selected else 0)"
  ],
  "decreases": "len(values)-processed"
}
```

Place this object in the root `loops` list. Selectors must match exactly one
actual loop. The cursor is a fresh proof-only name controlled by the verifier;
its structural bounds are generated automatically. The checker proves initial
establishment, preservation by the actual body, bounds and definedness, integer
decrease, normal exit, and early-return postconditions. Function contracts can
state the final sum through `len(values)`. There is no length cap or finite
unrolling.

`forall_range(i,lo,hi,predicate)`, `exists_range(...)`, and `sum_range(...)` are
capture-checked specification binders. Quantifiers cover the exact integer
interval; sums have a well-founded recursive definition. They are not executable
source calls. Loop annotations do not instrument production functions. If an
operator occurs in an executable pre/postcondition, the runtime binder evaluates
the actual finite interval without Z3.

Every function is checked, including helpers. A loop helper's contract becomes
available to callers only after its source proof succeeds. Mutation runs can
reuse that proof only for an identical transitive source/declaration/contract
fingerprint. Exact helper memoization includes the calling guard and does not
carry branch-local assumptions into another branch. Scalar residue definitions
and separately checked cursor facts keep cyclic arithmetic tractable without
restricting input lengths or integer magnitudes.

## Requirements

Expressions are parsed as restricted Python ASTs; neither source verification nor
requirement evaluation uses `eval`. Property calls such as `step(...)` execute
symbolically against the handwritten implementation.

This small, complete requirements file checks the existing lifecycle source:

```json
{
  "version": 1,
  "state": "State",
  "event": "Event",
  "initializers": ["new"],
  "step": "step",
  "invariants": {
    "execution_lease": "state.leases == (1 if state.busy else 0)"
  },
  "contracts": {
    "new": {"ensures": ["result.leases == 0 and not result.busy"]},
    "step": {"ensures": ["not result[1].reclaim or result[0].leases == 0"]}
  },
  "properties": [
    {
      "name": "reclaim_waits_for_terminal",
      "variables": {"state": "State", "event": "Event"},
      "assume": ["event.kind == 'quiescent'", "not state.terminal"],
      "lets": {"next": "step(state, event)"},
      "assert": "not next[1].reclaim"
    }
  ],
  "witnesses": [
    {"name": "admit", "assert": "step(new(), Event('start', 1))[1].start"}
  ],
  "mutations": [
    {
      "name": "early_reclaim",
      "function": "step",
      "target": "state.busy and state.terminal",
      "replacement": "state.busy",
      "detects": ["property.reclaim_waits_for_terminal"]
    }
  ]
}
```

Contracts accept `requires` and `ensures` expression lists. Preconditions use
function argument names; postconditions additionally bind `result`. Every
function is checked for return coverage, result types, and guarded helper
preconditions. Initializers must establish all invariants, and transitions must
preserve them from any valid state and well-typed event satisfying the transition
preconditions. State-dependent admission belongs in those preconditions.

Properties bind typed `variables`, then evaluate `assume` clauses in order,
sequential `lets`, and `assert`. A let can call `step` on an earlier let's result
for multistep properties. State variables in explicit properties do **not**
implicitly assume invariants; include the needed assumptions. Witnesses use the
same shape and require a satisfying execution. Contradictory premises,
undefined calls, impossible witnesses, timeout, and solver `unknown` fail checks.

Mutation targets must match exactly one expression AST inside the named function.
The altered implementation must produce a real SAT counterexample for every
listed `detects` property and reproduce it by executing the checked mutated
source against decoded concrete inputs. An induction failure or syntax error
alone is not a successful mutation control. Exceeding the diagnostic replay
resource limit fails the control; this never caps the proof domain.
The generated validator module exposes `bind(module, *, binder=None)`, returning
`validate_before(name, arguments)`, `validate_after(name, arguments, result)`, and
`validate_state(state)`. These checks use the same contracts without importing Z3.
`Machine` supplies its local binder, so a private, relocated runtime package needs
no global `invariant` import alias. Direct `bind(module)` remains supported for
the normal package name. Runtime bundles provide the runtime and generated
validators without Z3. Proof receipts, requirements, and reports serve build and
package acceptance; consumers choose whether to retain them alongside runtime
files. Blender extension packages keep these proof artifacts in external build
evidence, outside the installed runtime bundle.

## Build and evidence

From the repository root:

```sh
buck2 build //:verify --show-output
buck2 test //libraries/invariant:tests
buck2 run //libraries/invariant:verifier -- \
  libraries/invariant/src/invariant/lifecycle.py \
  libraries/invariant/requirements/lifecycle.inv \
  --require-property reclaim_waits_for_terminal \
  --output .tools/lifecycle-proof
```

Repeat `--require-property NAME`, `--require-witness NAME`, and
`--require-mutation NAME` to make missing declarations fail. The delivered Buck
targets enumerate their mandatory safety properties through
`invariant_proof(..., required_properties=[...])`. The rule accepts `source` and
`requirements` artifacts, invokes the verifier, and exposes `[validators]`,
`[receipt]`, and `[report]` subtargets. Runtime targets package the checked source
artifact and depend on their generated validators, so source edits rerun proofs.

The output contains:

- `obligations/*.smt2`: inspectable solver queries, labeled with expected results.
- `report.json`: each obligation's expected/actual result, success flag, and any
  counterexample; mutation results include the obligations that detected them.
- `receipt.json`: successful source/requirements hashes, required-property names,
  verifier-module hashes, Z3 version and wrapper/native-library hashes, Python
  identity, and report hash.
- `validators.py`: generated runtime requirements and schema checks.

Safety obligations expect UNSAT; nonvacuity and witnesses expect SAT. A failed
recheck removes the successful receipt and validators. `init.*`, `preserve.*`,
`defined.*`, `contract.*`, and `property.*` names identify the checked condition.
Names beginning `premise.*` check satisfiability rather than safety.

The proof covers extracted Python control decisions over modeled inputs. It does
not prove Rust memory safety, physical lease bookkeeping, native acknowledgements,
scheduler fairness, or operating-system behavior. Each consumer validates those
boundaries with its own runtime and native integration checks. Rust consumers may
also use Miri and AddressSanitizer; these are consumer-specific checks, not evidence
provided by the generic verifier or automatically supplied by Blender tests.
Receipts bind build/package inputs; generated contracts provide runtime
validation, not runtime attestation.
The Python interpreter, imports, build tools, and solver are trusted.

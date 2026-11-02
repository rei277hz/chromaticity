# Visual Output Consistency

- Treat authoritative Grade settings as the source of truth; generated kernels and displayed results are derived data.
- A last-good result may lag while a replacement is being built. Never present a partial or stale result as current.
- If a Grade kernel cannot be updated or recovered, never silently bypass the Grade or keep rendering its stale output as if it were current. Fail closed with a visible error and magenta output that preserves alpha; stop a render when the host provides a reliable way to do so.
- Reconcile derived Grade kernels after file load and before rendering.

# State Machine Design

- Store only independent facts needed to decide transitions or enforce safety. Derive readiness and other redundant values from authoritative state instead of storing duplicate flags.
- Include only events and effect fields that have a real caller or contract. Keep effects empty when a transition has no effect to request; for declarative policy effects, return the resulting policy on idempotent transitions when consumers must reconcile external drift.
- Represent absence with `Optional[T]` and `None`, not sentinel values such as an empty string. Keep annotations and formal requirements consistent with that choice.
- Preserve asynchronous safety with the smallest useful correlation data. Accept a completion only when its signature or generation still matches current demand; use a generation when equal signatures cannot make results interchangeable or request ordering is not guaranteed.
- Treat a machine's returned effects as the sole authorization for the external side effects they represent. Route every such mutation through an effect consumer; use composition so one decision applies all required operations, without class inheritance or direct side effects in callbacks and error handlers.

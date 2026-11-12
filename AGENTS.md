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

# Validation Scope

- Do not run tests, proofs, lint, formatting checks, or other validation for `libraries/perceptual-grade-core` or `products/perceptual-grade-blender`.
- CI checks only `products/perceptual-grade-next-blender`, including its policy proofs. Shared build and tool dependencies are permitted, but unrelated validation targets are not.
- Keep CI target selection and formatting scoped to that product; do not use repository-wide validation selectors.

# Development Execution

- Run builds, tests, proofs, and other executable validation only through Buck2 with remote execution (`--remote-only`). Do not run test modules, build scripts, proof scripts, or other validation directly from the local shell.
- A local formatter is permitted only when formatting a specifically identified code range is necessary; keep it scoped to `products/perceptual-grade-next-blender`.
- Non-Buck2 build and validation scripts are strictly forbidden. Configure or deploy a compatible remote execution environment as needed, then use Buck2 for the actual build and validation work.

# Contributing with Sapling

- Keep the working copy on the local `main` bookmark. To sync it, first ensure the working copy is clean, then run `sl pull -B main`, `sl bookmark -f -r remote/main main`, and `sl goto main`. `sl pull` fetches commits; it does not switch the working copy by itself.
- Start each change from `main` by creating and activating a topic bookmark before the first commit: `sl bookmark <topic>`. This keeps the local `main` bookmark at its base while the topic bookmark advances with commits.
- Make signed commits with `sl commit -m "..."`. Use `sl amend` or `sl amend -m "..."` to update the latest unpublished commit. Do not amend commits already pushed to a shared branch or PR; add a follow-up commit instead. When GPG pinentry is needed, do not attempt the command in the agent shell; give the user the exact commit or amend command to run in an interactive terminal.
- A change may contain several commits, but submit them together as one PR based on `main`. Confirm the GitHub repository's default branch is `main`. Sapling's default submit workflow can create one PR per unlinked commit, so run `sl pr follow -r <older-commit> ...` for every earlier commit that should be included under the topic-head PR, then run `sl pr submit` from the topic head. Sapling pushes the topic and creates or updates its PR; it derives the PR base from the repository's default branch. Later commits on the same topic update that PR.
- After a PR is merged, sync and return to `main` with `sl pull -B main`, `sl bookmark -f -r remote/main main`, and `sl goto main` before starting the next change.
- Check `sl status` before committing. Do not commit local build outputs or tool state such as `buck-out/` or `.sl/`.

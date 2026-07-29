# Repository-Level RTL Repair

The `repo-rtl` suite extends ordinary VeriGym agent runs to frozen, multi-file
RTL repositories. It is benchmark-neutral: suite adapters provide strict task
manifests, while `ExperimentPlanner`, `BatchRunner`, `VeriGym.run`,
`ReportService`, integrity sealing, and replay remain the normal execution path.

## Task bundle

A task contains `task.yaml`, `issue.md`, a visible `repository/`, separately
mounted `public/` tests, verifier-only `hidden/` tests, a conformance-only
`reference/` patch, and an Apache-2.0 `LICENSE`. Manifests bind the base tree,
bundle, issue, path classes, public contract, hidden verifier, reference patch,
budgets, and license identities. External task corpora are local paths supplied
explicitly; the suite never clones or downloads them.

Only `TASK.md`, `PUBLIC_TESTS.md`, and the frozen repository enter the agent
workspace. Editable, read-only, runtime-generated, and forbidden path globs are
fail-closed. Symlinks, hardlinks, special files, `.git`, case collisions,
binary patches, undeclared changes, and limit violations are rejected.

## Public tests and verification

The repository-agent image exposes:

```text
verigym-public-test list
verigym-public-test run <test-id>
```

The trusted launcher accepts only a declared ID and executes hash-bound argv
with `shell=False`. Public assets use a separate read-only mount and an
ephemeral bounded build directory. The agent container has no network or
credentials. After candidate freeze, hidden tests run in a distinct
network-none Icarus Verilog 12 verifier session.

LocalRuntime is used only for deterministic zero-model functional acceptance
and is reported as `host_local_trusted`; it does not claim Docker network or
read-only-mount enforcement. Model-bearing repository runs require the
credential-free Docker repository-agent identity.

## Candidate and replay contract

VeriGym freezes `candidate/repository/`, a canonical `repository.patch`, before
and after snapshots, and patch metrics. It applies the patch to a fresh copy of
the base and requires the resulting repository hash to equal the frozen
candidate exactly. Replay repeats these identity and patch checks without
Codex, the broker, credentials, proxies, or the public-test launcher; hidden
verification is optional.

Candidate compile failures, hidden-test failures, and safely contained policy
violations are evaluable unsuccessful outcomes, not infrastructure failures.
PPA is not part of this environment.

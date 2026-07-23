# MVP security regression audit

This audit covers only the Milestones 0–9 evaluator. The ordinary security suite and opt-in
Docker paths are executable evidence; source inspection alone is not counted as verification.

## Verified controls

The test suite exercises parent traversal, symlink escape, unsafe hard links, devices/FIFOs/
sockets, hidden lookup, separate agent/verifier namespaces, candidate freeze against TOCTOU,
disallowed tools, strict request/config/profile/plugin descriptors, argument-array subprocesses,
secret redaction, bounded output/JSON/YAML/traces/workspaces/reports/plans, timeout and structured
resource failures, artifact-loader non-execution, CSV formula/control-character defenses,
Markdown escaping, corrupt artifact rejection, exact-identity replay, and offline reporting.

New artifact manifests accept only bounded normalized ordinary files with required roles,
visibility, size, and SHA-256 metadata. Tampering is an integrity error; older artifacts are
explicitly `legacy_unverified`. Entry-point failures are isolated, and plugin-origin diagnostics
do not include arbitrary exception detail. Supported plugin interfaces remain subject to task
tool/path policy, budgets, hidden separation, candidate freezing, and runtime controls.

## Docker/host-dependent controls

The opt-in Docker suite inspects effective non-root identity, `network=none`, read-only root,
bounded `noexec,nosuid,nodev` tmpfs, dropped capabilities, no added devices, no-new-privileges,
memory/swap/CPU/PID/output/time limits, fixed environment, canonical private mount, and labeled
cleanup. It checks that home, Docker socket, SSH/cloud credentials, external source roots, and
hidden assets are not agent mounts. Timeout, OOM, output-limit, missing-image, replay, success,
and failure paths are checked for leaked managed resources.

These results depend on the audited Docker client/daemon/image/host identities in the release
evidence. Docker shares the host kernel and daemon; a compromised daemon or kernel can defeat the
controls.

## Residual risks and unsupported threat models

- `LocalRuntime` is `local_trusted` and must not execute adversarial RTL or repositories.
- Installed plugin Python code is trusted host code; discovery isolation is not a plugin sandbox.
- Docker is not a VM, formal isolation proof, or defense against a hostile administrator.
- Remote model providers are mutable services; observed IDs/fingerprints do not prove weights.
- Educational Liberty-mapped area is neither timing/power nor signoff PPA.
- Commercial execution, PDKs, formal tools, OpenROAD, repository-level adapters, external agent
  frameworks, trajectory export, RL, and distributed execution are unsupported.

## Audit disposition

The final `release_audit/security_summary.json` maps these controls to test evidence. Any missing
required runtime or external-data check keeps the overall release-candidate gate failed even when
the implemented controls pass their available regressions.

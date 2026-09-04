# DeepSeek Harness v132 bounded-scan scaffold authorization

Date: 2026-09-04

## Decision

This change authorizes exactly one zero-provider execution of
`deepseek-harness-hwe-v132-bounded-scan-scaffold-v1`, and only after the implementation is merged
to `origin/main` and that exact merge commit passes all eight Actions classes. The execution may
materialize and qualify the five frozen primary tasks in one fresh `/data2` VFS DinD. It may
publish one atomic scaffold contract only if every task passes all offline qualification gates.
It cannot start Harness, construct a provider client, make a model/provider request, collect a
trajectory, or authorize SFT.

The manifest canonical hash is
`4cb189e20714729dd61af77b7c860a320eefa1027fa3597ae1dc45a799ae7317`. Its invocation requires
the exact positive post-merge `main` Actions run ID and the one-use opt-in
`VERIGYM_RUN_DEEPSEEK_HARNESS_V132_BOUNDED_SCAN_SCAFFOLD=1`. Provider variables,
`DOCKER_HOST`, and `DOCKER_CONTEXT` must be absent at the host boundary. The authorized runner
file SHA-256 is
`9f4f1caaffcb87ea030f28ac1d67e6122a8f2575b2acc46d5a1e4ffdb2f7602c`.

## Frozen inputs and schedule

V132 binds the audited v127 scaffold inputs and terminal evidence, the v128 result audit, all 15
files in the immutable v130 evidence tree, and the v131 result audit. It independently validates
their file hashes, canonical hashes, identities, merge gates, closed collection/training flags,
and the passed 29-check v130 scan. The frozen predecessor Docker volumes are never opened,
inspected, or mutated.

The exact order is:

1. `hwe-bench/repo-repair-v1/lowRISC__ibex__pr-465`
2. `hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1135`
3. `hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1780`
4. `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2017`
5. `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2711`

Every image is loaded only from its completed archive under
`/data2/jiadongzhu/Agent/hwe-bench-public-images`. The runner revalidates the archive SHA-256 and
sidecar, OCI manifest and config digests, repository base, source commit, official verifier image
ID, and frozen task lock before use. Registry access, fallback tasks, task substitution, archive
repair, and `.partial` files are forbidden. The fixed future provider identity would use
seed/sample `502/18`, but v132 itself has no provider credentials or provider-consumption marker.

## Fresh runtime and task qualification

The runner creates only these fresh bind-backed Docker volumes:

- `verigym-deepseek-harness-v132-dind-data`, backed by
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v132/data`;
- `verigym-deepseek-harness-v132-dind-socket`, backed by
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v132/socket`.

It starts the immutable local `docker:23.0.6-dind` image once with outer `network=none`, VFS,
bridge/iptables disabled, and exact `23.0.6`, `vfs`, `runc` readiness. Inner Docker access is
explicitly bound to the v132 Unix socket. Each task image is imported offline, its public tests
must establish base-FAIL/reference-PASS, and its task-specific credential-free, Codex-free command
image is built with network `none`. Command-image and official-verifier identities remain
separate; a command-image result cannot be represented as an official verifier result.

Every security-scan container has an exact deterministic PR-specific name and v132 owner/role
labels. Docker create, each inspect, diagnostic start, removal, and total scan have bounds of 300,
60, 180, 120, and 720 seconds. A timeout fails closed and triggers deterministic name-based
cleanup. Receipts persist no raw Docker output or exceptions and do not hash nonempty output.
The scanner retains `network=none`, non-root execution, read-only root, dropped capabilities,
no-new-privileges, resource limits, exact environment, and one writable workspace mount.

Success additionally requires the explicitly bound all-container/all-volume inner inventory to
be empty and every task/source/image/toolchain lock to be complete. All five task receipts must
pass before the runner can atomically publish a scaffold contract; no partial contract is allowed.

## Failure, cleanup, and successor boundary

Cleanup addresses only exact v132 owner-labelled resources. The fresh socket volume and its
backing path are restored with a networkless least-capability helper. On a failure after material
has entered the data volume, that exact v132 data volume is frozen for independent analysis rather
than broadly deleted; no predecessor or unrelated resource may be touched. Cleanup ambiguity is a
terminal fail-closed result.

The runner does not prune Docker, restart its daemon, alter VPN/proxy state, use the host Docker
data root, access the user-owned downloader, or inspect a `.partial` archive. It must not read or
mutate resources belonging to another checkout or campaign.

Both a passed and a failed execution consume v132. The result must be independently audited as
v133, merged, and pass its own eight-class post-merge `main` gate. This authorization does not
authorize v134 or any provider request. A successful v133 audit may support a separate immutable
v134 official-matrix authorization; a failed or partial scaffold may not. Formal collection and
training remain closed: `formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and `production_training_ready=false`.

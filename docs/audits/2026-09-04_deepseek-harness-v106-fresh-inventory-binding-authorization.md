# DeepSeek Harness v106 fresh-inventory-binding scaffold authorization

Date: 2026-09-04

## Decision

Authorize implementation of
`deepseek-harness-hwe-v106-fresh-inventory-binding-scaffold-v1`. Authorize exactly one
credential-free execution only after this change is merged and the resulting `main` commit
passes all eight ordinary Actions classes.

V106 repairs only the final inner-image inventory binding rejected by v103. It remains a
zero-provider infrastructure qualification, not a model episode. Formal collection, SFT
training, and production readiness remain closed.

## Audited predecessor

V103 successfully transferred the controller and workspace runtime and rematerialized all five
scheduled tasks from completed local archives. Every task reproduced base-FAIL without an
infrastructure failure and reference-PASS, built a fresh task-specific command image, and passed
all 29 v2 security checks. It then stopped before contract publication because the inherited
inventory predicate required historical schedule command-image IDs instead of the five freshly
locked IDs actually present in its new DinD daemon.

The v104 audit at merge `95b9a11dbb3833fd57fc5b0a43bcd8708bc25865` froze v103, retired the
unused v105 provider identity, and required a fresh zero-provider successor. Post-merge `main`
run `33795946043` passed all eight check classes.

V103 and every earlier campaign identity and data volume must not be retried, reopened, edited,
imported, or promoted. V103 task results remain immutable audit evidence and cannot substitute
for v106 materialization.

## Authorized repair

V106 uses new bind-backed Docker volumes rooted at:

- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v106/data`
- `/data2/jiadongzhu/docker/deepseek-harness-hwe-v106/socket`

It may read immutable historical evidence and completed local task archives. It must not access
a registry, use a partial archive, modify or prune the host Docker root, modify VPN/proxy
settings, touch the user-owned downloader, or read or write `/data/docker` for task layers. The
outer DinD daemon remains on network `none`.

V106 must rematerialize, in fixed order, exactly Ibex PR-465, PR-1135, PR-1780, CVA6 PR-2017,
and PR-2711. Each task retains the v103 patch, archive, OCI, source, verifier, semantic,
base-FAIL/reference-PASS, and complete v2 scan gates. Provider credentials must be absent;
provider requests, provider calls, and model process count must remain zero.

For each task, the materializer must cross-check the fresh `HweCommandImageLock` against the
corresponding task receipt, official verifier ID, and historical semantic binding. Only after all
five fresh IDs are distinct and all receipts agree may it publish the in-memory inventory map and
resealed task-materialization set.

Both the initial and final inventory checks must derive their required command-image IDs from
that fresh lock-and-receipt map. They must additionally require the fixed controller, workspace
runtime, and five official verifier images, yielding exactly 12 distinct required images. The
five historical schedule command-image IDs are recorded for audit context but are not required.
Inventory remains bounded to 1 MiB and rejects a missing map, duplicate fresh ID, nonzero exit,
stderr, empty or oversized output, non-UTF-8 data, malformed image IDs, or an incomplete set.

The contract may publish only if the task-materialization set, both inventories, and all five
task receipts expose the same fresh mapping. It must also complete all runtime preparation and
synthetic Harness initialization checks, remove the internal network, DinD sidecar, and socket
volume, and preserve the fresh data volume as immutable evidence.

## Failure and successor boundary

V106 is one-use. Any infrastructure, security, capacity, or cleanup failure freezes the identity
and its evidence immediately; it must not be retried. No partial contract authorizes provider
access.

A successful v106 contract still authorizes no provider execution. It must first receive an
independent v107 result audit, that audit must be merged, and the resulting `main` commit must
pass all eight Actions classes. Only then may a separate change consider the unused identity
`deepseek-harness-hwe-v108-official-matrix-v1`. If v106 fails, v108 is retired unused.

The following remain false throughout v106:

- `formal_collection_allowed`
- `formal_collection_started`
- `collection_started`
- `training_started`
- `production_training_ready`

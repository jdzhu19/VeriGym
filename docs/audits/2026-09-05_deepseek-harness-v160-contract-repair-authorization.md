# DeepSeek Harness v160 contract-repair authorization

Date: 2026-09-05

Status: implementation authorization; execution is forbidden until this change is merged and the
post-merge `main` workflow passes all eight required job classes.

## Decision

Authorize exactly one provider-free contract repair under the immutable identity
`deepseek-harness-hwe-v160-contract-repair-v1`. This operation may validate the frozen v158
evidence and read the retained v158 Docker volume's metadata and usage state. It may not mount,
inspect, mutate, remove, or reopen that volume. It is not a provider run, task attempt, trajectory
collection, benchmark score, candidate import, or SFT authorization.

V158 completed all five offline task qualifications and both explicit-endpoint preflights, then
failed closed because its Harness receipt omitted one legacy aggregate while recording the two
stronger split false facts. The independent v159 audit is merged at
`78fc7e785866072ca3db5d9e277910e2d52c4925`, and post-merge `main` run `33963391618`, attempt two,
passed all eight required job classes. V158 is consumed and must not be rerun.

## Frozen implementation and inputs

- V160 manifest canonical hash:
  `b89dee2c3b6068cd228cc0a395eb354f7c189dd855df02e8edf5a29b026ecd9f`.
- V160 manifest file SHA-256:
  `4bd0a1402c2ebd7e5f734412e4081e1bbafbb2ff59ba1228aa5ca21b111d1498`.
- V160 runner SHA-256:
  `d8e770a1be2da8e7138f402701bb4e6a3593f3c4737e64a799cfb6f404e5c393`.
- V160 launcher SHA-256:
  `913b90cf940785d2665945f6e124043591e0814c6469a75c4c71e198c074bfe2`.
- Campaign manifest implementation SHA-256:
  `e0e58c87a0463a292a55fa6fbb12c72f2753e2d75bf90fb08ecb3635bd7686ca`.
- V159 audit file SHA-256:
  `a3d1492b655184a1fec9ad2bdc5f72d47f447030bab7296877460293065c7777`.
- V158 evidence-tree hash:
  `b1c844b0827ed68621aba75ad0aa8db81cfc9ff5aab84dc28f8361cef935e130`.
- V158 report canonical hash:
  `19612d63e3fe0ce8f331f9101c3130c672ffaeb11dbcfa8ad7e90b594f2c4901`.

The manifest freezes the complete v158 implementation and evidence hashes, 1,786-directory and
10,492-file inventory, zero symlinks, PR-465/1135/1780/2017/2711 order, seed/sample `502/18`, the
retained data-volume identity and bind backing, and a one-reopen budget for the distinct future
identity `deepseek-harness-hwe-v162-official-matrix-v1`.

## Repair and publication rules

V160 must revalidate the entire v158 evidence tree, every recognized canonical JSON self-hash,
the terminal report/progress identity, all five base-FAIL/reference-PASS receipts, the exact
12-image inventory, five independent explicit-runtime preparations, the Harness initialization,
and the separate successful cleanup receipt. It must verify that the retained data volume still
has the frozen bind, owner and role labels, has no container users, and has no remaining v158
socket volume. These are Docker metadata queries only.

The compatibility repair is permitted only when the original canonical Harness receipt has an
empty synthetic-value scan, `values_persisted=false`, `values_hashed=false`, no provider request,
and zero provider calls. V160 adds `provider_values_persisted_or_hashed=false` only to an in-memory
copy and reseals it. Because persisted JSON object keys are canonicalized rather than ordered,
v160 also recreates the three task-to-image maps in the frozen manifest order before invoking the
unchanged v158 pure contract-builder chain. No predecessor file or Docker content is modified.

All v160 output is written to a private staging directory and atomically renamed only after the
complete inherited contract succeeds. The new contract propagates the separate cleanup receipt
hash, records the current merged source and green `main` run, and remains non-authorizing pending
an independent v161 audit.

## Boundaries

- The launcher removes all twelve provider configuration names plus `DOCKER_HOST` and
  `DOCKER_CONTEXT` by name before reading allowed environment values or starting the child.
- V160 must not start Docker containers, create or remove volumes, mount the retained volume,
  execute a task or Harness process, access a registry, read a `.partial` archive, or contact a
  provider.
- Any implementation, audit, evidence-tree, receipt, volume-metadata, task-order, security, or
  post-merge gate drift prevents publication and leaves the v160 output identity absent.
- V160 does not authorize v162. A successful result requires an independent v161 result audit,
  merge, and eight green post-merge `main` check classes before any provider identity is enabled.

Execution command after merge and the v160 post-merge gate:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V160_CONTRACT_REPAIR=1 \
  python scripts/launch_hwe_deepseek_harness_v160_contract_repair.py \
  --post-merge-main-run-id <v160-post-merge-main-run-id>
```

The following values remain false throughout v160:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.

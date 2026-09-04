# DeepSeek Harness v148 cleanup-identity scaffold authorization

Date: 2026-09-05

Status: **one provider-free execution authorized only after merge and green post-merge `main`**.

## Decision

Authorize exactly one execution of
`deepseek-harness-hwe-v148-cleanup-identity-scaffold-v1` after this implementation is merged to
`main` and that exact merge commit passes all eight ordinary Actions job classes. V148 repeats the
audited v146 five-task provider-free scaffold in fresh `/data2` resources. Its only behavioral
change is to bind final socket cleanup to the exact current manifest volume, owner, and backing
instead of delegating to the predecessor function containing a v142 volume literal.

This does not authorize DeepSeek provider access, candidate task execution, formal collection,
SFT, or production training. The v146 resources and evidence remain frozen. A possible official
successor is the distinct v150 identity, which remains unreachable unless v148 completes and a
separate v149 result audit is merged with green post-merge `main` checks.

## Frozen implementation

- Manifest:
  `configs/training/qwen35_hwe_deepseek_harness_v148_cleanup_identity_scaffold_v1.json`
- Manifest file SHA-256:
  `6b2a33aa3ecebb4756e6fb2d6b60adef8b0b25e216016326a82f4b9993ba0f67`
- Manifest canonical hash:
  `4a44c1547289caea2de14e5743621e83ea72669964458dcaab9e0254dae9cef1`
- Launcher:
  `scripts/launch_hwe_deepseek_harness_v148_cleanup_identity_scaffold.py`
- Launcher SHA-256:
  `caba03bcf127883b4306921ae73d6d1946fe4aa12c1015956bc8dcc6c26ee1ca`
- Runner:
  `scripts/materialize_hwe_deepseek_harness_v148_cleanup_identity_scaffold.py`
- Runner SHA-256:
  `722a3891df425de60d7eb9a581f452540f43c5eebb20a54c42674ff77d806428`
- v147 audit SHA-256:
  `d8e4fe20b96d69e514fa55573e458c6090f5bba20fbf902c2f602e4cb4836f53`
- v147 audit merge: `9d6c6cc149772c9e5f2608030e5726df257fdd2e`
- v147 post-merge `main` run: `33919008896`, eight of eight jobs passed

The manifest locks the v146 implementation and its terminal report, five-task materialization set,
execution inventory, runtime-preparation receipt, command-probe diagnostic, Harness initialization
receipt, and independent v147 audit by both file and canonical hashes where applicable. Static
validation reads those immutable evidence files only; it does not inspect or mount either v146
Docker volume.

## Exact cleanup identity

Before any cleanup Docker operation, the runner requires all of the following from the current
v148 manifest:

- socket volume `verigym-deepseek-harness-v148-dind-socket`;
- owner `deepseek-harness-hwe-v148-cleanup-identity-scaffold-v1`;
- backing `/data2/jiadongzhu/docker/deepseek-harness-hwe-v148/socket`;
- `cleanup_identity_binding_source=exact-current-manifest-v1`;
- exact-volume, exact-owner, and exact-backing requirements enabled;
- predecessor literals and v146 volume inspection or mutation disabled.

The helper has `network=none`, a read-only root, dropped capabilities except the minimum needed to
restore ownership and mode, fixed resource limits, and only the current v148 socket-volume mount.
The volume-removal command uses the same manifest value. Publication requires the backing to be
empty, mode 0700, and owned by the invoking user. A changed identity or any cleanup failure is
fail-closed. Diagnostics retain only allowlisted stage metadata and byte counts; raw output, raw
exceptions, and nonempty output hashes remain forbidden.

## Fresh resource and execution boundary

V148 uses only these new resources:

- data volume: `verigym-deepseek-harness-v148-dind-data`
- socket volume: `verigym-deepseek-harness-v148-dind-socket`
- data backing: `/data2/jiadongzhu/docker/deepseek-harness-hwe-v148/data`
- socket backing: `/data2/jiadongzhu/docker/deepseek-harness-hwe-v148/socket`
- control root: `/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v148-control`
- runtime scratch: `/data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v148-runtime`
- evidence root:
  `/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v148-cleanup-identity-scaffold-v1`

The launcher retains the audited v146 exact 12-name provider boundary plus the two Docker endpoint
names. It selects allowed environment entries by name before reading values; blocked values are
not read, printed, persisted, or hashed. The runner validates the same set and marker before
output or resource creation. V148 reads task images only from the five completed local archives,
rejects `.partial` files, never accesses a registry, and keeps official verification on
`network=none`.

All five base-FAIL/reference-PASS controls, credential-free and Codex-free command-image v2 scans,
300-second content-free identity probes, empty inner inventories, synthetic network-isolated
Harness initialization, and exact v148 cleanup must pass before one atomic provider-free scaffold
contract can be published. Any failure prevents partial authorization and consumes v148.

## One-shot execution

After the implementation merge and green post-merge `main` run, invoke the launcher exactly once:

```text
VERIGYM_RUN_DEEPSEEK_HARNESS_V148_CLEANUP_IDENTITY_SCAFFOLD=1 \
python scripts/launch_hwe_deepseek_harness_v148_cleanup_identity_scaffold.py \
  --post-merge-main-run-id <green-main-run-id>
```

Do not wrap this command in a hand-maintained `env -u` list. V148 is consumed after its first child
start whether it passes or fails. Success publishes only a provider-free scaffold pending v149
audit.

Formal collection and training remain closed:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.

## Credential-free verification

Before authorization merge, run core, HWE Bench, DeepSeek Harness, and Synopsys integration
credential-free suites, their required mypy checks, and
`ruff check . && ruff format --check . && mypy src`. Focused regressions must prove immutable v146
evidence binding without volume access, deterministic task order, current-manifest-only cleanup,
rejection before Docker of any changed cleanup identity, exact provider-boundary inheritance, fresh
resource identities, bounded command probes, raw-detail exclusion, and v149 success mapping.

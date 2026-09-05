# DeepSeek Harness v159 audit of the v158 explicit-endpoint scaffold

Date: 2026-09-05

## Decision

The single authorized execution of
`deepseek-harness-hwe-v158-explicit-endpoint-scaffold-v1` is consumed and must not be rerun. It
successfully materialized and qualified all five frozen tasks, proved the repaired explicit Docker
endpoint through the actual service runtime and Harness controller paths, and then stopped before
publishing the atomic provider scaffold. The terminal status is
`stopped_without_execution_scaffold`; the report canonical hash is
`19612d63e3fe0ce8f331f9101c3130c672ffaeb11dbcfa8ad7e90b594f2c4901`.

The final failure is a zero-provider receipt-compatibility defect. The v158 Harness initialization
receipt records the split facts `synthetic_value_scan.values_persisted=false` and
`synthetic_value_scan.values_hashed=false`, but it omitted the older aggregate field
`provider_values_persisted_or_hashed=false` that the inherited v97 scaffold-contract constructor
still requires. Every other v97 predicate is satisfied. No provider request, model process,
candidate execution, modification, trajectory, collection, or training started. No task is
provider-consumed, no provider scaffold was published, and no provider execution is authorized.

## Implementation and execution gates

- v158 implementation commit: `1789ebe1f87949be568dbd9cde79397706fe2dd2`
- v158 authorization merge/source commit: `c2e24fdfa7a3a8ea4e48e7a2e2a429071713afcc`
- v158 pull request: [#184](https://github.com/jdzhu19/VeriGym/pull/184)
- v158 branch-push run: `33961173472`, attempt two passed all eight jobs after rerunning one
  transient Docker external-agent test failure
- v158 pull-request run: `33961174993`, eight of eight jobs passed
- v158 post-merge `main` run: `33961573936`, eight of eight jobs passed
- v158 manifest file SHA-256:
  `3173df38fb75d2d45159a66760611834721423522046b1fcc7c8ef2e1dca87f4`
- v158 manifest canonical hash:
  `045c2d1f875438c8237602ece254ad6e3483b8739585efa004363e7a72084228`
- v158 runner SHA-256:
  `fc6a565dd465e9616a6041485bde1b87541fc138b10f86362cd1ad141fb8e489`
- v158 launcher SHA-256:
  `fd3eafe632a63ada4225b901e5f6262e7dbb90f96f74037338493df9e750ff1c`
- v158 authorization SHA-256:
  `4c44857ead7c3e176724c82a236012ade485a7b8bb362f8a0764323e9c87eefa`

The launcher was invoked exactly once from the clean merged `main` commit with post-merge run ID
`33961573936`. It removed all twelve provider configuration names and both ambient Docker endpoint
names before starting the child. The child recorded zero provider calls and zero provider request
markers.

## Immutable execution evidence

The frozen evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v158-explicit-endpoint-scaffold-v1`

It contains 1,786 directories including the root, 10,492 regular files, zero symlinks, and no
other filesystem objects. Directory modes are 20 entries at `0700` and 1,766 prepared-source
entries at `0755`; file modes are 65 evidence files at `0600` and 10,427 prepared public-source
files at `0644`. All 45 schema-defined top-level canonical self-hashes validate. The 20 other
mode-`0600` JSON receipts intentionally have no top-level self-hash; their semantic bindings are
covered by the sealed task-materialization set. The terminal progress and report are
byte-identical.

An in-memory scan compared the three available distinct nonempty provider values with all 10,492
files without printing, persisting, or hashing those values and found zero matches. The complete
evidence-tree hash is
`b1c844b0827ed68621aba75ad0aa8db81cfc9ff5aab84dc28f8361cef935e130`.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| report/progress | `14a7e98d432b150f7f37440bfeb098314313004f804b5b020e32d68e3c9b176b` | `19612d63e3fe0ce8f331f9101c3130c672ffaeb11dbcfa8ad7e90b594f2c4901` |
| headroom preflight | `2a9b4374f4bf173c613a764aea7c28e5f3df70088e4fa667985d1739a69094f9` | `8348482c724991ce9d9d871bf0e78c63f88819950a06952081eee26dfaa12ca2` |
| DinD runtime | `aef982bd32e2041b1cd1566f75e3ebfa23a365b8f374df6166f4542acff215a1` | `7bbb7e660b27413cd578c158f941fb1061f175319da6e4a8668979b9d5bff9ef` |
| image-transfer set | `d76b24d49c563e853779d1755478fbf33931f0bb0a36b3e957b9774ed9dfc04e` | `324ec1e53026be6a5b9766d7136b910794e938875d0c4065a7bfe47ace22aafb` |
| task-materialization set | `0a1a0ea06d5ae6f638b3ad40c719cedf97c65dc8076a9ab332f443de22905e4e` | `393d0607232582769c2c9685cad6c0d40ecb50d34f7187021b4728fec8d5328c` |
| execution/final inventory | `c23232459f2ac315ca721af4aaaa72f01c45caee1b642c298b6de0ad5c9dba94` | `e7139e893f8820e5446b7aa0bbd090d9c43fae0895ac2627060ae0bbeafc25f6` |
| runtime preparation | `3bc5acb575fa5769c0004292f2b8e83226db83fbe6b7152fb85927dff5bef35e` | `aab4a9edbfa66ed767653dc7ed60005131b05b4d87e8fc7fdb5fb246efdd03ad` |
| command-image probe | `7d23f1ffb74a7614e207ff1f8df5c87762ef37e4d3f3646840c836ac44dbc0b6` | `d66491be3a111abfd6b8cd2aa2fa20991da3da763b875d4e5f88790249f2b9c2` |
| Harness initialization | `c1b9d45221719e6d4ce94356ffa01b6b96029ff48cf4ab1e0ac2658a25f1316e` | `b121a1a7376da56552ba09f5d197eeac506c4129e7ffb6e82832f92840e8f9c8` |
| socket-cleanup diagnostic | `2a33081d26671bb9cf3ba74f5bbab0d4c7ed27452307e54ad74bad05f687ba04` | `c74fe420b4609a2171dde7ca8e2d9c40c1e3ebb53b4cfbff71cdab7a40847230` |
| DinD cleanup receipt | `7198200e3d85ed18bd58f46fded6aaa81c56104cb2868113f896b0eb51f0736f` | `2ed3de870e6f03608b975649aa8149a911dbbc8b5a7f5318f21feea1ec689083` |

The terminal report correctly records all four completed zero-provider stages, all five task IDs,
the source commit and post-merge gate, zero provider calls, no request marker, and no published
contract. It records `dind_cleanup_confirmed=true`, but its
`dind_cleanup_receipt_hash` is `null` because the inherited exception path did not propagate the
successful cleanup receipt hash. The separate canonical cleanup receipt above is present and
valid. This secondary reporting defect did not cause the contract rejection, but a successor must
fix both compatibility fields before publication.

## Five-task qualification and endpoint result

All five completed local archives passed SHA-256 sidecar, OCI manifest/config, registry-digest,
immutable image-ID, repository-base, and source-commit checks. No registry or `.partial` archive
was used. Each official verifier ran with `network=none`; every base produced an ordinary test
failure rather than an infrastructure error and every reference passed.

| Task | Base | Reference | Fresh command image | Verifier-control diagnostic hash |
| --- | --- | --- | --- | --- |
| Ibex PR-465 | FAIL | PASS | `sha256:7ca012874dc4ae58680051afdc328141c57e3d0df753603f8cc4894e1d1a34b0` | `6da32d7626e0860c46fdb695b1fe7bcd0a44cf8290737ccc496f016d0488bc5a` |
| Ibex PR-1135 | FAIL | PASS | `sha256:f5fc6ab365c62b61b12516ca5ae97945b226f7b582ab9bc9eb58083ca39c9549` | `aea96f2a4a1d4e8fdd5c6c0301f9700eb93a0ab0fb1ceee9918e6a0293e04cda` |
| Ibex PR-1780 | FAIL | PASS | `sha256:baccac20fee1b7457aedb4925c25c4761b2c3ea6e90cdd5e8807001c424c24f6` | `863ae350349d5b06fa93996fa8a7148f4440f56a122263f405962b452b4b02b0` |
| CVA6 PR-2017 | FAIL | PASS | `sha256:81a658d4839dcfa4fa1ce1f89912db5fb4648bf7f86d997c0f2cea5d31505a93` | `186168cc9e96ff949e2c0ca4c2433c5d10d4bb95dbf4a927c1509c2af4b91173` |
| CVA6 PR-2711 | FAIL | PASS | `sha256:b1cb198a745e98f85ecc0141ccef621f38c7e7795bad769381df7ce3dbcf836e` | `5af72bb9f580ac988c92517dc74e10ca63e7eb6f7df02f7e50f568e7f3a46863` |

The exact inner inventory contained the controller, workspace runtime, five official verifier
images, and five fresh task-specific command images. Every command image passed the v2 scan with
locked tool hashes, no credential or Codex content, a non-root identity, read-only root, dropped
capabilities, `no-new-privileges`, bounded resources, one workspace mount, and `network=none`.

Most importantly, the actual service registry configured five independent `DockerRuntime`
instances. All five prepared against the explicitly bound v158 nested Unix socket, each owned a
distinct `DockerCliEngine`, and closed with empty inner container and volume inventories. The
Harness controller configuration also bound that socket explicitly and initialized on the inner
daemon using synthetic non-routable provider values. Its scan covered 10,487 then-existing files
and 164,105,823 bytes with zero matches. This closes the v154/v156 Docker endpoint defect.

## Exact root cause

The failure occurred after the runtime and Harness preflights, while composing the inherited v97
contract. V97 requires all of the following:

- the exact 12 required images and workspace runtime;
- five ordered task receipts with base-FAIL/reference-PASS and v2 scan semantics;
- all five runtime prepares;
- no provider request and zero provider calls; and
- `harness_preflight.provider_values_persisted_or_hashed is False`.

The frozen v158 evidence satisfies the first four groups. Its Harness receipt omits only the last
legacy aggregate key while carrying the two stronger split false values. Because missing is not
identical to false, v97 failed closed before v158 could reseal and publish its contract. This is a
schema-compatibility omission, not evidence that a provider value was persisted or hashed.

## Cleanup and successor boundary

The v158 outer DinD sidecar and exact socket volume were removed. The socket backing, control
root, and runtime root are empty, mode `0700`, and owned by UID 1004/GID 100. No v158-labelled
container remains. Exactly one v158 volume remains:
`verigym-deepseek-harness-v158-dind-data`, labelled for owner
`deepseek-harness-hwe-v158-explicit-endpoint-scaffold-v1` and role `data`, bind-backed by
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v158/data`. No container uses it. Its content was
not mounted or inspected during this audit.

V158 and its evidence/data volume are frozen. The absent scaffold means the previously planned
v160 provider matrix is not authorized and must not run. After this v159 audit is merged and its
post-merge `main` workflow passes all eight required job classes, a new zero-provider successor may
bind the exact v158 evidence, restore the omitted legacy aggregate field from the already sealed
split facts, propagate the cleanup receipt hash, validate the full inherited contract in memory,
and publish a new atomic contract. It should not rematerialize tasks or contact a provider or
registry. A later, separately versioned official matrix requires its own independent audit,
authorization merge, and green post-merge gate.

The following values remain false throughout this audit:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.

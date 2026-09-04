# DeepSeek Harness v133 audit of the v132 bounded-scan scaffold

Date: 2026-09-04

## Decision

The single authorized execution of
`deepseek-harness-hwe-v132-bounded-scan-scaffold-v1` is consumed and passed. All five primary tasks
qualified from completed local archives: every base failed for the expected test reason without an
infrastructure error, every reference patch passed, every task-specific command image passed all
29 v2 security checks under the bounded v132 scanner, and the final explicitly bound inner
inventory was empty of containers and volumes. The runner therefore published one atomic scaffold
contract with canonical hash
`86761f3aaf887658c5ba5ae12406624f2dac7e65238997a9d0da09a0cdb70b49`.

The terminal status is `completed_pending_independent_v133_audit`; its report canonical hash is
`1bc557a7791b0cb7c30ed8ef31565c64f20f2560d319619bc73bb648d796ef10`.
No provider request, model process, Harness episode, candidate task execution, trajectory
collection, or training ran. V132 explicitly records `provider_execution_authorized=false`, so
this audit does not retroactively turn the zero-provider scaffold into a provider campaign.

## Implementation and merge gates

- v132 implementation commit: `1f4b8e3496c60cda3d93ba1457cae19586a8268c`
- v132 authorization merge/source commit: `3667a5eda00876e93b96610edbfb774e19d1d967`
- v132 pull request: [#158](https://github.com/jdzhu19/VeriGym/pull/158)
- v132 branch-push run: `33848450742`, eight of eight jobs passed
- v132 pull-request run: `33848472055`, eight of eight jobs passed
- v132 post-merge `main` run: `33848806588`, eight of eight jobs passed
- v132 manifest file SHA-256:
  `6a3fac73f83dff726ea4734c00b783f15ba8538970e8f41e89572ca5e92c9dc3`
- v132 manifest canonical hash:
  `4cb189e20714729dd61af77b7c860a320eefa1027fa3597ae1dc45a799ae7317`
- v132 runner SHA-256:
  `9f4f1caaffcb87ea030f28ac1d67e6122a8f2575b2acc46d5a1e4ffdb2f7602c`
- v132 authorization SHA-256:
  `b39ad45483f72ce3193df67106bee21442b71f7f4257a9ff43637c9c7aceab7f`

The invocation used only the merged `main` source after the exact post-merge gate. The one-use
opt-in was present. All twelve frozen provider variable names plus `DOCKER_HOST` and
`DOCKER_CONTEXT` were removed from the child environment before execution.

## Immutable execution evidence

The immutable evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v132-bounded-scan-scaffold-v1`

It contains 1,782 directories including the root, 10,481 regular files, and zero symlinks. The
root is mode `0700`; 54 receipt JSON files are mode `0600`; the 10,427 materialized public-source
and verifier-result files are mode `0644`. Sixteen directories are mode `0700` and 1,766 public
source directories are mode `0755`.

All 54 mode-`0600` receipt files parse as JSON. Thirty-nine formats define a top-level canonical
self-hash, and all 39 validate. The remaining 15 files are the five reference-patch compatibility
receipts, five command-image build receipts, and five smoke reports, whose schemas do not define a
top-level self-hash. The atomic progress and terminal report are byte-for-byte equal.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| report/progress | `df83808e1f1707d7d9fc299104f3579ea33bb50e22bff46b5acef33b9ddacbf9` | `1bc557a7791b0cb7c30ed8ef31565c64f20f2560d319619bc73bb648d796ef10` |
| scaffold contract | `f1b6b1bff7638f1d463650a4d747118e231ce1b86e086c9ae77797d48010cfb7` | `86761f3aaf887658c5ba5ae12406624f2dac7e65238997a9d0da09a0cdb70b49` |
| task materialization set | `aa80c5c914d91b447fc649c27d6f0a13d5a389b2b992656cb99ac7aa12900fa7` | `5807c0f57a87fd85a5bad11c1d06a65dd8bb98e45b9ca4479bdf6dc5f2bf9e1e` |
| DinD runtime | `47245402e73892f685587521017db0262f44d42938ba9ec861bfea3a60cc5eb3` | `a30574cf151f3565dd4688d025e96874cfd4ad669b583939919c3e87032c787d` |
| execution/final inventory | `3f6a008a788b228363d5d645772c0cc7725abb93de7a4a85b1b066760d0c1a0a` | `a6da4d5b95792a94f42c1cd9747a53de877373174dbf861d04b5c02d9b1eac5e` |
| runtime-prepare preflight | `cb91cc6e0ead119ca6ac90d734393b017d018790e0018f4a14c27f2a954bff0e` | `751c4c7904aa14ba715cde7da001369caa6b918447c1d2ed049a427e95c67d09` |
| Harness-initialize preflight | `1f293133b771af1a28c4ff53ad2e2463ac3c1e052b40930db222fdbe7b3d955b` | `7cce77ec54e6da6b5e989f121f7d23d83f128545d555a833b205a810a68840f2` |
| socket cleanup | `46f3579dab274876eca2cc9cf8e0f5eafba381c22bbd1433c35be0b82e8224b6` | `9d85284e21fe3ab6155ab4e3a15a4a29c73bd941e51b003b41db94fe871e4ea9` |

An independent scan compared every nonempty provider secret value available to the audit process
with all 10,481 regular evidence files without printing or hashing those values. Four values were
available for comparison, and the scan found zero matches.

## Five-task qualification and scanner result

The exact task order and immutable results are:

| Task | Base/reference | Fresh command image | Command lock | Security scan |
| --- | --- | --- | --- | --- |
| Ibex PR-465 | expected FAIL / PASS | `sha256:7de54938ca619ac008a2f1dbcaedb243d2beb08aecf44125889d0c06a5783d2c` | `45054a863ca9c736441206fcf973fe2522071b8fda3beddb9e32158dc9a2c9fa` | `19da6e02194d1f22046e249b7582232be0c430d1ccd415556d92976849358f3e` |
| Ibex PR-1135 | expected FAIL / PASS | `sha256:c394eb7d76242341b942b3279ccfc12c98febf016e7e9de210e961dffd3b3187` | `82d842a36b0d3b79fe3f0ad4cf48a61e24cc2760ad34e2d582116a247e746612` | `7cea53dea1643371fe75dafbf53f029c37e3d377af4feb5c792106c5993afbd1` |
| Ibex PR-1780 | expected FAIL / PASS | `sha256:be94795f104eca6a63854ae4f4e925760cad22f2c3d9320178a4776e95cd65ce` | `04c80945b654dad6dc63a0388e6f7788d9ec79ee2dca0eae747325b5d4f8ea7f` | `4c5f6825dbc96607fc88d976786d42993e36302f65de23c1c98da02d1f551b2c` |
| CVA6 PR-2017 | expected FAIL / PASS | `sha256:08d74acb66b3345384028dc7ace4c60e2af3824f0f8ef41a1bf23dd2a482f81f` | `5aeba847ea6dddf79855e725deb3848d67298b55ab07a0fa4681e759826881d7` | `d5f0ea0412ec3ccab16c4e8a22eb2d6ea297435b9b5b0dd31648f750b26b7499` |
| CVA6 PR-2711 | expected FAIL / PASS | `sha256:b7dbcd25ec59d2b33efdf78ecc89d129e3937b74968870773d44162fdff7df83` | `9eb0d10cf15ae88ad8d1d82ec270f9c936ee6bfc9feb3652141ddb41bafae374` | `d8e2f861c7fd0d0a2944915b460de9bdadbc2eb26f032d4661d38da760e74edd` |

Each base smoke result contains one failed public regression with category `test_failed`, zero of
one test passed, and `base_infrastructure_error=false`. Each reference result contains one of one
test passed with category `success`. Task and official verifier containers used `network=none`.
All archive, OCI manifest/config, repository base, source commit, task, official image, source
toolchain, and command-image locks validated before the task receipt was admitted.

Every command-image scan used its exact deterministic `verigym-hwe-v132-command-scan-pr-*` name,
v132 owner label, and bounds of 300 seconds for create, 60 seconds for each inspect, 180 seconds
for diagnostic start, 120 seconds for removal, and 720 seconds overall. Scan elapsed times were
26,278 ms for PR-465, 13,712 ms for PR-1135, 14,430 ms for PR-1780, 18,684 ms for PR-2017, and
20,145 ms for PR-2711. Every create, diagnostic, and cleanup exited zero without a timeout; every
temporary container and workspace was removed. The scan receipts persisted no raw output and did
not hash nonempty output.

All five bounded command-image builds exited zero without timeout and persisted no raw stdout or
stderr. Their stdout was empty; stderr byte counts were 1,755, 1,755, 1,518, 1,397, and 1,454 in
task order. The content-free build diagnostics do record output digests under the inherited build
policy; these are not scanner diagnostic hashes and no provider environment was present.

## Runtime, cleanup, and frozen scaffold

The fresh DinD reached explicit readiness on poll 15 and matched server `23.0.6`, storage driver
`vfs`, and runtime `runc`. Its outer network was `none`, task layers remained under the declared
bind-backed `/data2` data root, and every inner operation used the canonical v132 Unix socket.
No inherited or remote Docker endpoint, host-sidecar inventory, or host-sidecar network control
was used.

Both the execution and final inventories are byte-identical. They contain all 12 required images,
including five fresh command images, and record zero inner containers and zero inner volumes after
preflight cleanup. Seventeen images were visible in total because intermediate build images are
not provider resources. Runtime-prepare and network-isolated Harness-initialize preflights both
passed, but Harness itself and a provider client were not started.

No v132-labelled container remains. The socket volume was removed; its backing directory, runtime
scratch, and control headroom are empty, owned by UID 1004/GID 100, and mode `0700`. The exact
success data volume `verigym-deepseek-harness-v132-dind-data` remains registered with owner
`deepseek-harness-hwe-v132-bounded-scan-scaffold-v1`, role `data`, local bind driver, and only
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v132/data` as its device. Its backing is root-owned
mode `0710`, as expected after daemon use. It is an immutable provider-successor scaffold and may
be reopened at most once only by its separately merged successor contract. It must not be pruned,
repaired, inspected internally, removed, or reused by any other identity.

The run did not access a registry or `.partial` archive, touch the user-owned image downloader,
change VPN/proxy configuration, restart Docker, use the host Docker data root for task layers, or
inspect/mutate a predecessor volume.

## Successor boundary

V132 must never be rerun. This audit establishes zero-provider qualification only; the two
trajectory migration conclusions remain unevaluated because no trajectory exists.

After this v133 audit is merged and that exact `main` commit passes all eight Actions classes, a
fresh v134 implementation may bind the byte-exact v132 evidence and authorize the official
five-task DeepSeek Harness v4 matrix with seed/sample `502/18`. V134 must retain the frozen model,
prompt, six-tool protocol, limits, exact tokenizer admission, strict task order, per-task provider
consumption, bounded continuation, security stop rules, and single reopen budget. It must never
reinterpret the zero-provider smoke results as model-task outcomes or publish SFT candidates
without all six admission planes.

Formal collection and training remain closed:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.

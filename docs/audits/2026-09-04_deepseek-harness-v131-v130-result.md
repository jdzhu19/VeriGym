# DeepSeek Harness v131 audit of the v130 bounded command-scan create probe

Date: 2026-09-04

## Decision

The single authorized execution of
`deepseek-harness-hwe-v130-bounded-command-scan-create-probe-v1` is consumed. Its PR-465
task-specific command image passed the complete v2 runtime security scan in a fresh `/data2`
VFS DinD. This resolves the v127 scanner-create blocker: a create operation that did not return
within the old 60-second limit completed under the v130 300-second bound, and the complete scan
finished in 72,460 milliseconds without a timeout, security failure, or leaked inner resource.

The v130 identity nevertheless stopped fail-closed with
`status=stopped_cleanup_unconfirmed` and `stop_reason=cleanup_unconfirmed`. The controller's
300-second wait for the outer cleanup helper expired before it observed completion. The exact
helper subsequently exited zero, and a cleanup-only continuation removed it and both exact
v130-owned volumes. The original terminal report and cleanup receipt were not rewritten; the
later fact is recorded in the additive `late-cleanup-receipt.json`.

This result does not publish or authorize a provider scaffold. No benchmark task, base/reference
verifier, Harness controller, model, provider request, registry access, or formal collection ran.
Both migration conclusions remain false because no trajectory was attempted.

## Implementation and merge gates

- v130 implementation commit: `817d9602d82d4ecac7f82e9e1f45fd8deb6146ca`
- v130 authorization merge/source commit: `f0b94f4d27cccc00b49e6ffcf156f0eddfac0983`
- v130 pull request: [#156](https://github.com/jdzhu19/VeriGym/pull/156)
- v130 branch-push run: `33843726593`, eight of eight jobs passed
- v130 pull-request run: `33843746004`, eight of eight jobs passed
- v130 post-merge `main` run: `33844057740`, eight of eight jobs passed
- v130 manifest canonical hash:
  `c25bd9762befe8a282d9b73be54c4349398f6777dc3a5e5875d8117a09226df2`
- v130 terminal report canonical hash:
  `3855fe26ffdf94da985d72ad62fcc260c9a2fb56b438f4026be5da20ed69dd31`
- additive late-cleanup canonical hash:
  `000f95a051fb25230403a6b522c0ac5a2675cad24f67d6c29af38951c248d598`

The invocation used only the merged `main` source after that exact post-merge gate. Its sole
one-use opt-in was present, while provider configuration variables, `DOCKER_HOST`, and
`DOCKER_CONTEXT` were removed from the child environment.

## Immutable execution evidence

The immutable evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v130-bounded-command-scan-create-probe-v1`

It contains five directories including the root, 15 regular files, and zero symlinks. The root is
mode `0700`, and every JSON file is mode `0600`. Every receipt, report, diagnostic, image lock,
inventory, and security-scan self-hash validates. The atomic progress and terminal report are
byte-for-byte equal. The original report remains the authoritative terminal state; the late
cleanup receipt is additive recovery evidence and does not turn v130 into a successful campaign.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| report/progress | `1dc9ab7ddab4cbd24508e88912e7d84314230eca1c7214895baa7bef7e332afe` | `3855fe26ffdf94da985d72ad62fcc260c9a2fb56b438f4026be5da20ed69dd31` |
| predecessor preflight | `f048c4ccb2aaf0fccbdab773ff97015b5194b53e3003de322afb843ecfa6cbe4` | `08186411492e3815afb17190f50ed0ff10636e441889a8213be3e128fca4a8cc` |
| PR-465 archive | `21d5ae1c122d933237f3d5d1e27b18a5656509eeb6873f820dba60845d5d4516` | `fc1af152a1ba03044119cf9ce230294498303591f65302299502c679be7c9d63` |
| host DinD image | `6cce8107e09161813c9bc29a99628faf4392d5c29752e903e627f71e92049d18` | `34bc43a2588600566158421d7880e8b10a8137bc2598a10e662f670340524d93` |
| volume setup | `96a73146fe2e361455c16fc089524d8d2a5f37ff5fa19226385a0ad50efdbbb5` | `f28e3afd7024acb3eb98652d8b12b0e9097eeb737267c8a781df5c25f22ddfbb` |
| DinD runtime | `70fa898323beec7b5ca5b5a8bd71b4f2d4f569b645d4f3c902a0c86f1266f477` | `46adee492f5dbee7d9e4c899b2bb7d95998aac4d26c7c3c62f1fa8bd2c7f705a` |
| task-image import | `9d9e252ff6f135f311cfb1339bd2602c3124d5933d6fe436ae49097d197dc2e6` | `f679d6abc45c162072ca37b3de893f5ef547252a376e91e7c2d1aa879d651d56` |
| command build | `514082eab57bc4f8e9f83febd286b4baf8cd821c6c79d2dad4836c42acecf238` | `c56e24a54e6b691ecc3a7ddaa978661797a79e8bac1af33a671b8a5a10c34f20` |
| security scan | `c850fc774c18ac18a7b4c27b2536f7e5a262f3b379d967adc03edb860c9af0fb` | `7e68ef3987f081e8e28af0b5d55f7e1aaeb6aa0336cff4547b62f8304e58d517` |
| command-image lock | `19415af2bf4ae6490bb322efb63140ea0da7c049dc9ec11b6b973aa9214d6f03` | `8fff0f84401d52a137e3bca04c2458f66a8341af8a45246e4a8c4408205600a5` |
| inner inventory | `f182f6bab177b22f7b0d517ce34c3fe96dd03cea110c8bfdad1ed4047c744c62` | `6d967688ad43cefcb123f3f45ff7b449f452e068b317f73462e99c3d2a62e60c` |
| original cleanup | `f7e1696663483a42bd9208a37e66b34b36d8126f44ae92267e3b4c375b12ccd5` | `30fdd276b1f0a79b856b9d50ec31ecce3029b6b68a09cbd865099853d73047e5` |
| late cleanup | `5499cf67d855c04352fbea0d86840dabed8f7f1097119cfbd78b9bcf753fe571` | `000f95a051fb25230403a6b522c0ac5a2675cad24f67d6c29af38951c248d598` |

The image-receipt file SHA-256 is
`621a9466d9f003f9c95300a42228c7a6ab2f2d99a278493fec7e932fec8e30ea`;
that receipt format has no self-hash field. An independent scan compared every nonempty provider
secret value available to the audit process with all 15 regular evidence files without printing
or hashing those values and found zero matches.

## Bounded scan result

The fresh DinD reached readiness on poll 21 and bound server `23.0.6`, storage driver `vfs`,
runtime `runc`, Docker root `/var/lib/docker`, and the exact nested Unix socket. Its outer network
was `none`, and all outer controls passed. The immutable, already-local PR-465 archive was imported
without registry access or a `.partial` file. The task-specific image was rebuilt with build
network `none`; the bounded build exited zero and persisted only byte counts for 0 stdout bytes
and 1,743 stderr bytes, not raw output or a nonempty-output hash.

The rebuilt command image is
`sha256:526b594b6b025f2412ba48d2156e4cb25a5d217131de42c1a20d528ba4997b5c`.
Its lock binds source hash
`e17ffb4c332928a043d6e9457458d01373e59c837f5511e11edadeff44b46ec1`,
task hash `5c55ec935c0d24c0533292b1f6a694485acd99884f0312a5813172568d21d7f8`,
the exact ripgrep 15.2.0 binary and release archive hashes, and official verifier base image
`sha256:d0d2c8a6391c3c35a2fc2e6e310786d65d0f0c4c9f08f6fcec5098d0be34c410`.
The fresh image ID differs from the v127 rebuild ID, but all semantic source, task, tool, and base
image locks remain exact; Docker-derived image IDs are not assumed reproducible across fresh VFS
builds.

The scanner used bounds of 300 seconds for create, 60 seconds for each inspect, 180 seconds for
diagnostic start, 120 seconds for removal, and 720 seconds overall. Its diagnostic records create
exit zero, no create timeout, diagnostic exit zero, cleanup exit zero, and successful removal of
both the temporary container and workspace. All 29 security checks passed. The post-scan inner
inventory contained zero containers and zero volumes.

This establishes that the v127 failure was caused by an insufficient operation bound rather than
an unsafe command image or a persistent Docker create deadlock. The 72,460-millisecond value is
the complete scan duration; it is not represented as an exact create duration.

## Cleanup and frozen boundaries

The original cleanup controller reached its 300-second helper wait and recorded only
`cleanup_unconfirmed`. After the runner returned, the exact owner/role-labelled helper was observed
exited with code zero. The cleanup-only continuation validated its identity, removed it, removed
the exact v130 data and socket volumes, and verified the data backing, socket backing, and runtime
scratch were empty. All three paths are owned by UID 1004/GID 100 and mode `0700`. No v130
container or volume remains.

The continuation did not inspect or mutate any predecessor volume. It did not touch the user-owned
image downloader, its `.partial` files, the host Docker data root, VPN/proxy configuration, or any
unrelated checkout. It issued no prune or daemon restart operation.

During preparation of this independent audit, a generic read-only disk-usage command was
mistakenly given the exact v127 data-backing directory. It returned only the aggregate `4.0K`
directory usage: it did not enumerate names, open an image layer, address the Docker volume through
the daemon, or mutate the directory. This is an audit-process policy deviation and is disclosed
here rather than being represented by the v130 runner's
`predecessor_volumes_inspected=false` field. No v127 evidence is used by this audit as newly
qualified data, and every successor remains forbidden from inspecting or mutating the frozen v127
volume.

The terminal report records `provider_credentials_available=false`,
`provider_request_started=false`, `provider_calls=0`, `model_process_count=0`,
`task_execution_started=false`, `base_reference_verification_started=false`,
`harness_controller_started=false`, and `registry_accessed=false`. All collection and training
flags remain false.

## Successor boundary

V129 remains reserved and unauthorized. V130 must never be rerun. This audit does not itself
authorize a provider request or the use of any trajectory identity.

After this v131 audit is merged and that exact `main` commit passes all eight Actions classes, a
fresh successor may be implemented under the next unused identity to re-materialize the atomic
five-task zero-provider scaffold. It may adopt the validated 300-second scanner create bound, but
must also provide a separately frozen outer cleanup-helper bound with ample margin for VFS layer
deletion and preserve the original terminal result if later cleanup completes. It must retain the
local-archive-only, no-registry, fresh bind-backed `/data2` DinD, explicit readiness, exact image
and source locks, `network=none` verification, deterministic owner-labelled cleanup, bounded
sanitized diagnostics, one startup attempt, and zero-partial-contract rules.

That successor must have its own implementation merge and post-merge gate before execution, then
an independent result audit. Provider authorization remains contingent on all five primary tasks
qualifying and one atomic contract being published. Formal collection, SFT training, and
production readiness remain closed: `formal_collection_allowed=false`,
`formal_collection_started=false`, `collection_started=false`, `training_started=false`, and
`production_training_ready=false`.

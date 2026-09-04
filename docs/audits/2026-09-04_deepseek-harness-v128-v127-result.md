# DeepSeek Harness v128 audit of the v127 readiness-gated scaffold

Date: 2026-09-04

## Decision

The single authorized execution of
`deepseek-harness-hwe-v127-readiness-gated-scaffold-v1` is consumed and failed closed before any
provider boundary. Exact DinD readiness passed, the controller and workspace-runtime images were
transferred, and Ibex PR-465 demonstrated base-FAIL without infrastructure failure and
reference-PASS. Its task-specific command image was built, but the v2 runtime security scan could
not create its temporary container within the fixed 60-second command limit.

This is a pre-provider infrastructure timeout, not a verifier rejection or a failed security
assertion. No provider-execution contract was published, no model or provider process started, and
the remaining four tasks were not consumed. V129 is not authorized because the required atomic
five-task contract does not exist. Both migration conclusions remain false because no trajectory
was attempted.

## Implementation and merge gates

- v127 implementation commit: `7d3bdb00565514ccf2fd666533b64e2e08df0c0b`
- v127 authorization merge/source commit: `def5d9d086203c83e39842534c999c5004dc27f1`
- v127 branch-push run: `33832114141`, eight of eight jobs passed
- v127 pull-request run: `33832130705`, eight of eight jobs passed
- v127 post-merge `main` run: `33832410957`, attempt 2 passed all eight jobs
- v127 manifest canonical hash:
  `cfa04d557d68e3d03efdfc15fdd579eb439b38e31876f186ab7270ed90e5bfcb`
- v125 report canonical hash:
  `6da2ba5dcff5aa424aea2bc1af02157c703fedd12fa6ae11897b3fad0ba9b7de`
- v125 readiness receipt canonical hash:
  `23fc06716d775e4f132e30b8cc0fdf79e3c246f39f632b78f77703cd414160fc`
- v126 audit commit: `084afb7c6e690f222d8274871c4fcc51ecf1a56a`

The first post-merge Docker job hit the known unrelated repository-agent fake-provider flake. The
same exact source commit had passed that job in both pull-request and branch-push runs. Only the
failed job was rerun, without a source change; attempt 2 passed all eight classes before v127 was
invoked.

## Immutable execution evidence

The immutable evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v127-readiness-gated-scaffold-v1`

It contains 81 directories including the root, 281 regular files, and zero symlinks. The root is
mode `0700`. All 22 JSON files parse; 19 are mode `0600`, while the three verifier-generated JSON
results are mode `0644`. Every top-level receipt/report/diagnostic self-hash and the nested security
diagnostic hash validate. The atomic progress and final report are byte-for-byte equal.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| report/progress | `050ce34e66bf431106d1e2a863c2a11d696fc828833ae9596d93d2d3621ed3a3` | `08d21363eb1202b08ed61160b05ec73fa1a5bb65536b1b59c3fe801e3e744cbd` |
| DinD runtime | `3236cd61b39f514faa222fa33d24b9ed2746b4f31b60cb5e4bba53b5ac6d0352` | `d797a58fc4eb480cba055a149953216eaa0f796d20c02d95c54c1832a8d7773f` |
| image transfer set | `8a4e9c6a853bc1558193ff9243af0b3b875b6e98a99b67f9119c06570e9e4094` | `8d31932a480e9bde882a369b8f0469353e6a11d6f3d5d7a1c84318cac8aeda81` |
| PR-465 archive | `21d5ae1c122d933237f3d5d1e27b18a5656509eeb6873f820dba60845d5d4516` | `fc1af152a1ba03044119cf9ce230294498303591f65302299502c679be7c9d63` |
| PR-465 build diagnostic | `cbe4a11860550dcd438d5095fd4e7a38ed1f12d851863bf02646d146805b4d0a` | `8f8f6a9258f8e86873016be5f5e68ff3daede8027cf0f87468dff0a0e5c60deb` |
| PR-465 source lock | `9f2b2f43e3577f418f0e5bcf24cdaac0960e40d324a0330611c92fbfda66d87a` | `f32616351ff822c6417fc566d34077f30570f73acc8b25d877cf8c6c765f2de7` |
| PR-465 security scan | `d9277c2caeccc3c25fe7003adb23d193aea0ea171ffc7e5103245d57f06fbfdf` | `852c4c34a7c7455264a5a1bfb13e7201579dbe9521b2d75a86c09b9b85a3970a` |
| nested scan diagnostic | contained above | `c1a3edda3ba3760420dbccdecdefdc4d8b0939cfc951803b5aa51b3f2999c6ae` |
| socket cleanup | `c97f95f58b5304eeb43ec1a21142d5e340517f1a1fadf984cb37b16f2db51d4b` | `1fcd4f0af3f98d7a12238d510e003e6422484e4691282e95fb5d4081ff8a4442` |

The report records `status=stopped_without_execution_scaffold`, `stop_reason=RuntimeError`, only
`controller_and_workspace_runtime_transferred` as a completed stage, and
`dind_cleanup_confirmed=true`. It records `provider_execution_scaffold_published=false`,
`provider_execution_authorized=false`, `provider_request_started=false`, `provider_calls=0`, and
`model_process_count=0`. All collection and training flags remain false.

## Readiness, task qualification, and failure

The DinD runtime qualified after 18 explicit readiness polls. The receipt binds server `23.0.6`,
driver `vfs`, runtime `runc`, Docker root `/var/lib/docker`, the v127 `/data2` backing inode, and the
canonical nested Unix socket. JSON-formatted info and a fixed poll cap were not used.

PR-465's public regression produced base-FAIL with `base_infrastructure_error=false` and
reference-PASS. The credential-free command-image build completed within its 1800-second limit and
produced derived image ID
`sha256:f049fcfb10d15999bdb39aeab1c7e96496b5910d9f26fb4f38dea91819187b2c`.
The image exists only inside the v127 DinD data volume; the similarly named host image/tag is
absent, confirming that task layers were written to `/data2`, not the host daemon data root.

The v2 scanner then issued its policy-bound `docker create` against the explicitly bound inner
daemon. The call exceeded its fixed 60-second timeout before returning a container ID. The sealed
diagnostic therefore records `failure_stage=docker_create`,
`error_category=docker_create_failed`, `temporary_container_created=false`, no exit code, no
captured output, `secrets_detected=false`, and successful temporary-workspace cleanup. No security
assertion was reached, so this evidence cannot be reported as either a passed scan or an unsafe
image.

## Cleanup and frozen resources

No container carrying either v127 owner-label spelling remains. The v127 socket volume was removed;
its backing, control, and runtime directories are empty, mode `0700`, and owned by UID 1004/GID
100. No execution-scaffold contract exists.

The data volume `verigym-deepseek-harness-v127-dind-data` remains registered with exact owner and
role labels and a bind option targeting `/data2/jiadongzhu/docker/deepseek-harness-hwe-v127/data`.
Its backing is root-owned mode `0710`, as expected after daemon use. It is frozen failure evidence:
future work must not reopen, inspect, repair, remove, or mutate it without a separately merged
authorization. The shared `/data/docker` contains only the host daemon's volume metadata; task
image layers did not land there. The user-owned downloader, VPN/proxy state, `.partial` files, and
unrelated checkout were unchanged.

A scan compared all four nonempty provider values present in the parent environment against every
regular evidence file without printing or hashing the values and found zero matches.

## Successor boundary

After this v128 audit is merged and its exact `main` commit passes all eight Actions classes, a
fresh provider-free diagnostic may be implemented as
`deepseek-harness-hwe-v130-bounded-command-scan-create-probe-v1`. V129 remains reserved but
unauthorized as a provider identity.

V130 may validate the exact v127 evidence files and the already-local derived command-image ID, then
use a fresh workspace and fresh v130 container identity to repeat only the scanner's `docker
create`, control inspection, inert diagnostic start, and deterministic removal against a fresh
bind-backed `/data2` DinD identity. It must not mount or inspect the frozen v127 data volume. It may
raise the create/inspect/remove bounds to a separately frozen value sufficient to distinguish slow
`vfs` materialization from a deadlock, but must keep `network=none`, the exact non-root/read-only
controls, a monotonic overall deadline, bounded sanitized diagnostics, one startup attempt, and zero
provider/registry/task/verifier activity. Execution requires its own implementation merge and
post-merge gate, followed by an independent result audit.

V127 must never be retried. Formal collection, SFT training, and production readiness remain
closed: `formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.

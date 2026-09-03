# DeepSeek Harness v86 audit of the v85 pre-provider stop

Date: 2026-09-03

Status: **safe pre-provider infrastructure stop; v85 and the v83 data volume are frozen**.
V85 ran exactly once and may not be retried, resumed, reconstructed, or relabelled. The outer
DinD sidecar opened the retained v83 data volume, but controller readiness did not complete and
the provider boundary was never crossed. No model response, task modification, official verifier
run, trajectory, SFT candidate, formal collection, training, or production-readiness work started.

## Authorization and execution boundary

The v85 implementation and authorization were merged through PR #122 at exact clean tracked
`main` commit `d10513d4eb7a42e7a9a0cf9f1e9deba11f756822`. Post-merge `main` Actions run
`33751636696` passed all eight required job classes before the single invocation.

Immediately before invocation, the fixed v85 output identity and socket volume were absent, the
socket backing and runtime scratch were empty, no campaign-owned sidecar existed, and
`DOCKER_HOST` and `DOCKER_CONTEXT` were absent. The data volume was an exact local-driver bind of
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v83/data`. `/data2` had about 38 TiB available;
the full task-layer store therefore did not use the 98%-full host root under `/data`.

Provider credentials were present only in the process environment for the authorized window.
Their values were not printed, persisted, or hashed. A post-stop scan of all four persisted files
found zero concrete credential-value hits. The invocation did not change the host Docker daemon,
VPN, or proxy configuration; access a registry; use a `.partial` archive; start or stop the
user-owned downloader; prune Docker; or delete shared `/data/docker` content.

The v85 manifest file SHA-256 is
`4fa017a14e413603a607dc90c43d0cd3b90a449b75a49d05493f5e4719354726`; its canonical
manifest hash is `d6a38242a4c18dae5443fe5aa75d119d18771ea5c556d679a96cf5e6bc0b9af6`.
The authorization document file SHA-256 is
`d9958e9535495a541573e7755b30b5b2dc4b3f90e2bd6a5f1f982df4dde4c21e`, and the runner file
SHA-256 is `42f3f2e27efa5c26573dc7b9c5bd09810c58d4bb59e504afd7140dcdcea04707`.

## Stop cause and provider disposition

The output timestamps and Docker event stream independently place the failure inside
`_start_provider_dind`, before its runtime receipt and before creation of the inner provider
network. The sidecar started and repeatedly executed `docker info` while the retained VFS daemon
initialized. Ordinary nonzero probes were retried, but the final probe exceeded its 15-second
subprocess timeout. `subprocess.TimeoutExpired` escaped the readiness loop because that loop
handled only nonzero return codes. The outer exception handler then sealed a fail-closed result.

This is a runner-readiness infrastructure defect, not a task, verifier, security, model, or
capacity result. The exact persisted disposition is:

- `provider_marker=not_started`, `provider_call_count=0`, and `provider_total_tokens=0`;
- `outcome=infrastructure_failure` and `stop_reason=pre_provider_infrastructure_failure`;
- one synthetic audit attempt for Ibex PR-465, with no task run or workspace file;
- zero attempts of PR-1135, PR-1780, PR-2017, and PR-2711;
- no runtime receipt, provider-network receipt, zero-provider preflight receipt, security scan,
  trajectory record, or candidate dataset; and
- both migration conclusions false solely because no real trajectory exists.

The PR-465 attempt file SHA-256 is
`aeb85f1b77ee69885ee13fa16280bbc02f4fa7f30518173dd111df38faaa5d4d`; its reproduced
canonical attempt hash is
`987cda1520237663b17430f9c9cfc436cc8f650df0a38edd6820385f4e774835`.

Under the frozen provider-boundary policy, none of the five tasks is provider-consumed. That fact
does not authorize a v85 retry. A new execution identity and a separately merged authorization
are required.

## Physical reopen accounting

The sealed report records `v83_data_volume_reopen_count=0` because v85 incremented its in-memory
counter only after `_start_provider_dind` returned. Docker lifecycle events and the changed v83
backing timestamp prove that the sidecar had already mounted and used the data volume before the
readiness timeout. The audit therefore conservatively records one physical reopen and treats the
v83 reopen budget as exhausted. The report field is retained unchanged as historical evidence;
it must not be used to justify another v83 reopen.

Any successor must use a fresh identity, fresh local volume, and fresh `/data2` backing. It must
materialize only from the already completed and digest-locked local archives, without reading or
copying the v83 Docker data root. Its readiness loop must bound the total deadline while treating
an individual probe timeout as a retryable not-ready result, and it must record physical volume
opening immediately after successful sidecar creation rather than after daemon readiness.

## Atomic report and cleanup

`matrix-report.json` and `matrix-progress.json` are byte-identical. Each has file SHA-256
`50739ac60876177a4e55cc8559c49f0b0b76933e24feb48886421c2dc39fedea` and reproduced
canonical report hash `68a5ee595cc474546451eb0561f008cab1886713688a7bc683986bbec534fa80`.
The final status is `stopped_pending_independent_v86_audit`, with no candidate or research task
IDs and PR-465 retained only as audit context.

Cleanup succeeded after the stop. The outer sidecar and transient socket volume are absent. The
socket backing is empty, mode `0700`, and UID:GID `1004:100`; the retained data volume still maps
only to the v83 `/data2` backing. The networkless, read-only cleanup container returned zero with
empty bounded stdout and stderr, dropped all capabilities except `CHOWN`, `DAC_OVERRIDE`, and
`FOWNER`, and persisted no raw output. The cleanup receipt file SHA-256 is
`39064d6a25de9fc91e2788ced51976648f2d5567a4d99f8e527ac202268f6d53`; its reproduced
canonical hash is `c2bbebe48275e1b97b68506743ca2cad49c7cf72aa35edf3ab4217de25668093`.

The external evidence root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v85-official-matrix-v1`. V85 and the v83
volume are immutable audit evidence. V86 grants no provider execution, rematerialization, SFT
import, formal collection, training, or production authority.

Terminal flags remain:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`; and
- `production_training_ready=false`.

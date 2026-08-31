# OpenHands v35 provider canary stopped before provider execution

## Result

The one authorized execution of `openhands-hwe-v35-provider-canary-v1` passed its control-plane
and two-command-image zero-call preflight, then stopped fail closed while starting the first
PR-2330 training episode. No provider episode or request started, no task attempt completed, and
PR-3204 was not reached.

The authorization merged as PR #48 at source commit
`313c2638c049d2315b317aacf79ead54f99ec6d6`. Its pull-request checks and all eight required
post-merge `main` Actions classes passed before opt-in. The final report records:

- `status=stopped_infrastructure_or_security_invalid` and
  `failure_reason=training-pr2330-s489-v35:ValueError`;
- zero provider episodes, calls, retries and completed task attempts;
- `canary_passed=false` and `formal_collection_allowed=false`;
- an empty held-out task list; and
- `formal_collection_started=false`, `collection_started=false`, `training_started=false`,
  `production_training_ready=false` and `benchmark_score_claimed=false`.

This is an implementation-boundary infrastructure failure, not a benchmark, protocol,
trajectory, model or security rejection. The v35 identity and output are sealed and must not be
retried or relabelled.

## Artifact chain and security scan

The immutable output is
`/data/jzhu484/Agent/experiments/openhands-hwe-v35-provider-canary-v1`. Its complete 13-file tree
hash is `5070d15deb17650bb368290a3757b0f2d7f3c2b31dc7ebff108a7ab547849f8f`.
Primary evidence is:

- `canary-report.json` and `canary-progress.json`: byte-identical, 3,485 bytes each, file SHA-256
  `54f3cf2f3b4982276c6db3b3f1b45db2da82803ade2f5382c4182fa542b67ede`, embedded report hash
  `e95d52b2bc1ab570aa792449405ca893992fb54e14808656821858cd1d421690`;
- `agent-version.json`: 2,121 bytes, file SHA-256
  `1d1ac61d85584a26865db76853decf23220d407e922d5c36e163347c9c9fbb43`, validated version hash
  `98ab778bb6a8dfb156433fe2650d7f10eae62255290b221b99461134ef70382a`;
- `contract-receipt.json`: 2,633 bytes, file SHA-256
  `21ebff1967519b29884364e81b5851d17d2c20b677642a61bf7415d1700ac8aa`, canonical receipt hash
  `4340a378bb0bba913f256e4272612c99433ec7e863cfccb40301485f613929cf`; and
- `zero-call-preflight.json`: 558 bytes, file SHA-256
  `341024c1701602b3cc91cd4c9ae2b0952a811bcfc8893e59d9cfb74caf14e9f9`, canonical receipt hash
  `e2b148488caaf7bc9505541f737ffc0ac03953e168ebe9a1499d092db4c671b1`.

The preflight receipt is `passed`, with completed stages `control_plane`,
`command_image_pr_2330` and `command_image_pr_3204`; it contains no exception text and records zero
provider episodes and calls. The partial run manifest SHA-256 is
`60d4a894a3a3cd6160e7eef4ab1538fca53c2233b462e0214e213e647dd961ae`; the two-event trace
SHA-256 is `ccea9a90306a6564c684cc83be391e7ae77ab9e482668049a5eef2da70c9f9f2`.
No v35-managed container or temporary broker object remains.

An independent in-memory context-aware scan covered all 13 files and 40,479 bytes. It included
the live provider endpoint, provider credential and active proxy values without printing,
persisting or hashing them. The scan passed with zero hard secret findings and zero scanner
errors; its content-free report hash is
`f29af71505ffe315264d0f5fbf0d9e4ae11c61caa33ebdef9a0fddb59d5f29fd`.

## Offline root-cause classification

The frozen evidence stops after `episode_started` and the initial public observation. It has no
agent action, provider event, accounting artifact, command invocation or verifier invocation.
The run manifest binds the command image to `episode_container_exec_v1`, while its external
process backend is `runtime_external_process_unavailable` and the external-agent image is absent,
as required by the Codex-free design.

At that exact boundary, `OpenHandsHweAgentAdapter.start()` accepts only a bridge whose
`execution_backend` is `docker_outer_runtime_delegated`. `RuntimeExternalAgentBridge` currently
derives that property solely from `RuntimeSession.external_process_backend`; the Docker session
returns `runtime_external_process_unavailable` whenever no external-agent image is configured.
The adapter therefore deterministically raises `ValueError` before `act()`, broker creation, LLM
construction or a provider call. The empty agent log and two-event trace corroborate this order.

The command runtime itself is present: the Docker session exposes
`execute_external_agent_command()` and dispatches the frozen command image through its persistent
episode executor. The missing piece is an explicit, bridge-visible command-backend capability;
accepting every unavailable external-process backend would be too broad.

## Successor requirement

Any successor must use v36 and bind this stopped evidence. The runtime session and bridge should
expose a stable command execution backend label. The OpenHands HWE adapter may accept the existing
outer-process backend or the exact `episode_container_exec_v1` command backend, while retaining
Docker-standard isolation. Tests must reject local/unavailable sessions, reject unsupported
command backends, and exercise a zero-provider adapter-start smoke with the Codex-free command
configuration before authorization.

The v33 image locks, v34 and v35 stop chains, controller paths, two-task order, budgets, six planes,
exact-64K gate and zero-retry policy remain unchanged. Formal materialization and collection
readiness shift to v37 and v38. This audit authorizes no successor, provider call, formal
collection, SFT, GPU work or held-out loading.

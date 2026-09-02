# DeepSeek Harness v63 Ibex PR-974 pre-provider result audit

Date: 2026-09-02

## Disposition

The v62 authorization was merged as
`f57269262d0df582467c7436eaa3d6eda02c3f65`, and post-merge main run
`33629976791` passed all eight required job classes. The single authorized PR-974
attempt then stopped before the Harness controller or model client was launched.

No usable trajectory was collected. The result is not an HWE-Bench score and is not
SFT-admitted evidence. PR-974 remains administratively frozen because the v62 runner's
conservative receipt marked the task consumed; it must not be retried under v62 or silently
relabelled under another identity.

## Bound execution

- identity: `deepseek-harness-hwe-v62-ibex-pr974-provider-canary-v1`
- task: `hwe-bench/repo-repair-v1/lowRISC__ibex__pr-974`
- model: `deepseek-v4-flash`
- seed/sample: `499/15`
- provider retries / episode retries: `0/0`
- report status: `stopped_post_provider_infrastructure_or_security_invalid`
- report failure family: `provider_episode:ValueError`
- admitted provider calls/tokens: none
- trajectory collected: `false`
- exact-64K eligible: `false`

The zero-call runtime and Harness-initialize preflight passed before the attempt. The command
image, verifier image, source, tokenizer, and authorization locks remained exact. Provider values
were neither printed nor included in this audit.

## Pre-provider evidence

The v62 receipt sets `provider_episode_started=true` immediately before entering the ordinary
VeriGym episode. That field does not prove that a provider request was dispatched. The lower-level
evidence proves that execution stopped in `agent.start()` before `agent.act()` could launch the
Harness helper:

- the trace contains only `episode_started` and the initial `observation_emitted` event;
- those events are 23 milliseconds apart;
- `model_observations=[]` and `external_agent_observations=[]` in the run manifest;
- there is no `deepseek_harness_process_started` event, assistant message, broker tool call,
  candidate modification, verifier execution, collection evidence, or teacher transcript;
- the agent and verifier logs are empty; the runtime log contains only `runtime_created`.

Accordingly, this is a provider-pre infrastructure/scaffold failure, not a model behavior failure.
The v62 `task_consumed=true` and post-provider status label are conservative but too coarse. This
audit preserves them as emitted while separately recording the more precise causal classification.

## Root cause

The real run manifest records the intended runtime split:

- external process backend: `runtime_external_process_unavailable`
- external command backend: `episode_container_exec_v1`

This is the v62 design: the Harness helper/controller is a host control-plane process, while all
model-visible repository tools are brokered into the digest-locked command image with task-tool
networking disabled. However, `DeepSeekHarnessHweAgentV4Adapter` inherited the older startup check
that requires `bridge.execution_backend == "docker_outer_runtime_delegated"`. The check raises
`ValueError` before the helper launch even though the command backend and isolation level are the
frozen v62 values.

The prior zero-call conformance initialized the pinned Harness SDK/controller but did not instantiate
the real `RuntimeExternalAgentBridge` backend combination. It therefore could not detect this
integration-boundary mismatch.

## Admission and readiness

- verifier: not run
- protocol: not evaluated
- trajectory: `false`
- infrastructure: `false`
- security: no violation observed, but no six-plane admission was attempted
- SFT admission: `false`
- formal collection allowed: `false`
- formal collection started: `false`
- collection started: `false`
- training started: `false`
- production training ready: `false`

## Frozen evidence hashes

- canary report/progress file:
  `1ebd79359e9229de188d95b6c0cc06bcbdebef29ea0dce64f9551ffb4b29f6f7`
- embedded report hash:
  `af205f7c22ea0270cf98d4a3b1c7583d08bd7d0d8b9a5668ea4c0c67426d2461`
- zero-call preflight:
  `f99b81cecedfee848953e2b00001533b1c4d41dc8aa56b28a5ec80b830ca6e45`
- run manifest:
  `2db59d45f65eb31ac69d226d1713d3b5c80ec34340d5b46b58bf68b2e5f95f84`
- trace:
  `bf37d6df2c74af7add7c1c763aa688746d54d1c4f2d32a089ec3bca1d9a7ea1f`
- runtime log:
  `62c23fb8085f0a32b12bdb143d3d5e1f0b822c09b5e1c2a26d88ffae742348bc`

The private run root, candidate workspace, Docker layers, and any provider environment remain
outside the repository.

## Next route

After this audit is merged and its post-merge main run is green, a successor may remove the stale
external-process-backend requirement only for the frozen host-control-plane plus
`episode_container_exec_v1` combination. It must add a credential-free regression that exercises
the real bridge startup path and a fake-provider end-to-end episode. Any subsequent provider canary
must use a new identity and a fresh task. It must not rerun PR-974, change the model or budget, relax
the verifier, start formal collection, or start SFT.

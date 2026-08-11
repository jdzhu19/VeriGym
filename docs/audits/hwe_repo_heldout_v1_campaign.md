# HWE repo-level held-out v1 campaign

- Date: 2026-08-11
- Status: infrastructure-invalid early stop; not a benchmark score
- Code commit: `7764ba7b1707d506bc2c2558b7d65e3b5ae9232c`
- Agent: `codex-luna-max-hwe-heldout-v1`, `gpt-5.6-luna`, reasoning `max`
- Split: `hwe-repo-heldout-v1`
- Sampling: one sample per task, base seed 3, no retry, no best-of-K

## Freeze

The frozen agent-version hash is
`1b01f7385eb242a9ac94bf7621738e0e24d788f67dc523a16ed189574a724ea7`. It binds
the committed core, Codex bridge, HWE integration, and training-reference wheel hashes; the
common repository-agent and outer-runtime images; and each selected task's suite-managed official
image ID. The content-free repository freeze has manifest hash
`51f1e086ae08b655aa0a00621ed1baa0707f9c804eebc8b380650db2638d1705` and split
manifest hash `b8fea2ea5cac55c5f30f6e0db4948e336e71b57286df98c590e3eef33468e7af`.
It contains exactly Ibex PR222, CVA6 PR2945, and Rocket Chip PR3065, with an empty training and
validation split. No repository contents, hidden assets, or reference solutions are in the freeze.

Zero-call Codex capability and authentication preflights passed. They observed Codex CLI 0.146.0,
the inherited ChatGPT-session semantic, zero diagnostic model calls, no copied credential files,
and no credential contents accessed by VeriGym.

## Campaign outcome

The frozen plan hash is `871c462b53f16a4d1e7e9bf7c74c7b5a40710844805073a6f11cf4b03e016efe`.
The first Ibex sample started and the upstream model service terminated the turn with the typed
`serverOverloaded` condition, reporting that the selected model was at capacity. The external
process was not timed out and its terminal event and cleanup were observed. It produced no patch.

The official Ibex verifier still ran in the locked image with network disabled and returned the
ordinary `test_failed` result for the unchanged base candidate. That verifier result was not an
infrastructure failure. The overall scorecard is infrastructure-invalid because the model episode
did not complete, so the campaign atomically recorded one attempted sample and stopped before any
CVA6 or Rocket model call, as required by the frozen no-retry policy.

| Planned task order | Attempted | Outcome |
| --- | --- | --- |
| Ibex PR222 | yes | infrastructure-invalid: upstream model capacity |
| CVA6 PR2945 | no | not started after early stop |
| Rocket PR3065 | no | not started after early stop |

The sampling summary hash is
`f8107ae788cb9250984656f8a83b650eda2dbb7dfefdcec1f0fd949e129571cc`; its file
SHA-256 is `bc26df062e6dd2824a0a719ce8bdfcfc1a205db9d9b1b86d138658452def0407`.
The scorecard file SHA-256 is
`02b15847fd6d22b369de56b75a1b05b887e270f08007e542bc35fe141860886c`.

## Offline post-processing and safety

Visible-episode replay passed. Observable trajectory export, dataset validation, and source replay
then completed with zero additional model, network, runtime, verifier, or public-launcher calls.
The dataset hash is `3697e5c1402b1252771f289e119ebc8ff2123b504108abcbef1cc14b106738f2`.
It contains one held-out record, zero eligible records, and explicitly excludes the run as
`infrastructure_invalid`.

A training-reference preparation check rejected the dataset with no eligible training records and
created no training bundle. Its report hash is
`547e6354b9f90de7fa418f122adf6abf2625c0f2f4f16ece8e023b178308cd2e`.
The context-aware artifact scan covered 240 files and 2,580,883 bytes. It passed with zero hard
secret leaks and zero scanner errors; its report hash is
`347716a8f2b4692496c84a81c88d93d353a3804982dfde104d907cb62f04b824`.
No suite verifier container or labeled ephemeral cache volume remained after the run.

This result validates the freeze, early-stop, replay, exclusion, and artifact-safety paths. It does
not provide a completed three-task held-out result or a model-quality claim. A future attempt would
be a new explicitly authorized campaign, not a retry within this frozen no-retry run.

## Explicitly authorized attempt 2

On 2026-08-11, the user explicitly authorized one new campaign attempt with the same frozen agent,
split, task order, base seed, one-sample policy, 1,800-second per-task ceiling, and no-retry or
best-of-K policy. The new output root was kept separate from the first attempt. Its plan hash is
again `871c462b53f16a4d1e7e9bf7c74c7b5a40710844805073a6f11cf4b03e016efe`, confirming that the
frozen sampling inputs did not change.

The Ibex external-agent process started successfully in the frozen image and remained alive until
the host control plane terminated it after `1803.0779150230228` seconds. Unlike the first attempt,
the CLI emitted no canonical events and reported no token accounting before the timeout. The
structured failure is `timeout`, origin `host_control_plane`; cleanup completed, the process group
and authentication broker stopped, and the workspace had no changed paths. The container used
network mode `none`, mounted neither the host home nor Docker socket, and received no credential or
proxy environment variables. The startup warnings were identical to the first attempt that did
reach the model service, so they do not explain the timeout.

The unchanged base candidate was still checked by the official digest-locked Ibex verifier, which
returned the ordinary failing result with exit code 134. The campaign recorded one
infrastructure-invalid sample and stopped before CVA6 or Rocket, as required. This second attempt
therefore also supplies no benchmark score or model-quality result.

Zero-call visible replay passed. Observable trajectory export, validation, and source replay also
passed with zero model, network, runtime, verifier, or public-launcher calls. The resulting dataset
hash is `37afe7b6085738f892cc3b3822bb7d3c9030a096a1daa288e1bf9eb40f08c23b`; its sole held-out
record is excluded as `infrastructure_invalid`, with zero eligible training records. The external
training-reference preparation rejected it and created no training bundle. The exclusion report
hash is `b47207863a54cce37a592b97e4f7e1497759cba87abf7f7be1c501937743e09c`.

The final context-aware scan covered 233 files and 2,432,584 bytes. It passed with zero hard secret
leaks and zero scanner errors under report hash
`e639cf3c455076921e6d9132fc1ae359f3d5e164a3728adec8eac70b1b9f1e2c`. No suite verifier
container or labeled ephemeral cache volume remained after the attempt.

## Luna xhigh differential diagnosis

The original `max` evidence above remains immutable. A separate, non-held-out diagnostic used
`gpt-5.6-luna` with reasoning `xhigh` and the same inherited ChatGPT-session semantic, Codex
capability fingerprint, outer verifier image, repository-agent image, and network-none Docker
boundary. It selected Ibex PR167, which the historical Luna `max` pilot had resolved through the
same bridge in 171.49 seconds.

The xhigh PR167 process instead ran for 604.38 seconds and was terminated by the host control
plane at its fixed 600-second ceiling. It emitted zero canonical CLI events, reported no token
usage, ran no external commands, applied no patch, and left the repository hash unchanged. The
process group, authentication broker, agent container, and verifier resources were cleaned. The
official verifier subsequently rejected the unchanged base candidate as an ordinary failure.
Visible replay passed. This reproduces the silent-wait symptom on a smaller, non-held-out task, so
held-out task secrecy and verifier execution are not its cause.

Two further non-held-out controls separated the remaining failure domains:

| Control | Boundary | Result |
| --- | --- | --- |
| Fixed `OK` prompt, Luna xhigh | host Codex CLI, no VeriGym Docker bridge | completed in 8.76 s |
| Synthetic protocol-valid repository task, Luna xhigh | full VeriGym Docker remote bridge | resolved in 63.58 s with 16 CLI events |
| Real Ibex PR167, Luna xhigh | full VeriGym Docker remote bridge | timed out in 604.38 s with 0 CLI events |

The direct control shows that Luna and the session authentication were available. The synthetic
repository control shows that the network-none remote exec-server bridge and verifier Docker path
were functional. Combined with the first held-out attempt's explicit upstream `serverOverloaded`
event and the historical PR167 success, the most likely failure domain is intermittent Luna or
host app-server control-plane waiting on repo-scale requests. The evidence does not distinguish a
silent upstream queue from host app-server handling of a large initial repository context, so this
is a medium-confidence localization rather than a definitive provider root cause.

The sanitized six-case diagnosis hash is
`5073337e544867071e14c8f7318cae077e8694116b6546a256f202ec593f973f`. The new diagnostic
artifact scan covered 250 files and 2,274,205 bytes and passed with zero hard secret leaks and zero
scanner errors under report hash
`3652bd46abb592cdd6426cc873f73d6c0f5facdc5f1383daf24538800cc2f0b6`.
No xhigh held-out score was attempted or claimed.

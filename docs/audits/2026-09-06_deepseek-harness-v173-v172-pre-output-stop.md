# DeepSeek Harness v173 audit of the v172 pre-output stop

Date: 2026-09-06

Status: v172 is infrastructure-invalid and permanently sealed; no task or provider was consumed.

## Authorized boundary

PR #198 merged the v172 authorization as
`3ef1957c65fd5f3e38e2d0248726b4a074d566dc` after all 16 PR checks passed. Its post-merge
`main` Actions run `33980145199` completed all eight required job classes successfully. The
implementation commit was `2e4f72c655f95fea4bbe0af06535fbab4a44a138`, the manifest hash was
`1b5675fbf6022728779be8b158c752dc0128197e8a14e44ebca8e369fea4a5ee`, and the manifest file
SHA-256 was `5a59db25c0d5de9e54b9cf375d925a3167d8629f70e4dd4b60a9749bfcc2a157`.

The documented launcher was invoked once with that post-merge run ID. It removed every provider
alias and ambient Docker endpoint name before entering the child. The child loaded and validated
the manifest, exact clean merged source, completed local archive root, and frozen local tool
inputs, then stopped in `_preflight_inputs` at the DinD repository-digest comparison.

This occurred before authorized output creation, scratch creation, a Docker build, a volume or
container creation, an image load, PR-1816 source preparation, an open-tool test, an official
verifier run, or a provider/model surface. The expected v172 output, scratch, data volume, socket
volume, and campaign-container inventory were all confirmed absent after the stop. The seven
pre-existing user-untracked files remained the only untracked repository files.

## Root cause

The DinD image itself did not drift. Docker returned:

- tag `docker:23.0.6-dind`;
- image ID
  `sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497`;
- repository digest
  `docker@sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca`;
- platform `linux/amd64`.

All components equal the authorization. The v172 manifest correctly stored the digest component
as `sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca`, but the runner
compared that bare digest directly against Docker's list of complete `repository@digest` strings.
The equality therefore failed solely because the repository prefix was present.

This is a deterministic preflight representation bug. It is not an image-integrity failure,
capacity failure, task/verifier rejection, open-tool build result, Harness result, or model result.
Changing the comparison and invoking v172 again would nevertheless violate its one-use
authorization.

## Frozen stop evidence

The sanitized external receipt is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v172-open-toolchain-qualification-pre-output-stop-v1`

It contains one owner-only ordinary JSON file and no link or special file. Its identities are:

- receipt hash:
  `ce78e74389439bb75b7abbc8fcce687b573da2673c5214f639e0a47a2a540a03`;
- receipt file SHA-256:
  `0af45d6c2d67c4de1f86d1bbf3ef694f7961ee9e6598f89a20f649250e123945`;
- evidence tree hash:
  `2b8962a93e2849ae142611967006a2cddac6de14263c746bdad9078b250c1846`;
- directory/file modes: `0700`/`0600`, owner UID/GID `1004:100`.

The receipt contains only public image/source identities, boolean/count state, the closed failure
category, and the exact merged authorization chain. It contains no provider/proxy value, raw
traceback, prompt, model output, task patch contents, hidden verifier material, or Docker daemon
output.

## Consumption and state

V172 consumed its single authorized command invocation but did not cross a provider or task
boundary:

- zero Docker builds, task-image loads, task attempts, open-tool tests, and official verifier
  runs;
- zero model processes, provider episodes, calls, tokens, or retries;
- no candidate, trajectory, verifier decision, image lock, or qualification contract;
- `qualification_contract_published=false`;
- `formal_collection_allowed=false`;
- `formal_collection_started=false` and `collection_started=false`;
- `training_started=false` and `production_training_ready=false`.

PR-1816 remains provider-unconsumed and its reference patch has not been submitted to either
route by v172. The v172 identity itself may not be reused.

## Successor requirements

This audit authorizes no successor execution. A separately reviewed v174 qualification repair
may preserve the v172 task, tool, archive, Dockerfile, isolation, dual-route, scan, cleanup, and
closed-state contracts while changing only the affected provenance comparison and all campaign
identities/paths.

The repaired gate must parse every Docker `RepoDigests` entry as exactly one
`repository@sha256-digest` pair, require repository name `docker`, require the frozen digest
component, reject duplicates and malformed entries, and still require the immutable image ID and
`linux/amd64` platform. It must regression-test the valid prefixed representation plus wrong
repository, wrong digest, missing delimiter, duplicate, and bare-digest cases.

V174 must use fresh output, scratch, data-volume, socket-volume, and image-tag identities under
`/data2`; it may not open, reconstruct, or relabel any v172 resource. It must bind this receipt,
this audit's eventual merge commit, and a new green post-merge `main` run. A successful
qualification would still require an independent v175 result audit. The PR-1816 research canary
moves to version 176 or later and remains unauthorized. Collection, SFT mixing, training, and
production readiness remain closed.

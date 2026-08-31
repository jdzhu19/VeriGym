# OpenHands v33 Codex-free materialization passed audit

## Result

The single authorized execution of
`openhands-hwe-v33-codex-free-canary-materialization-v1` completed successfully from clean merged
`main` commit `800c551a4ac089489b772c9a42bfd4a14801fe82`. It built, independently scanned,
and locked all six task-distinct command images and sealed the successor static canary contract.
It made zero provider calls and did not execute the canary.

Authorization PR [#43](https://github.com/jdzhu19/VeriGym/pull/43) merged before execution. Its
main-branch Actions run
[33408484145](https://github.com/jdzhu19/VeriGym/actions/runs/33408484145) passed all eight required
job classes: ordinary Python 3.11, 3.12, and 3.13; quality; package; reproducible build; OpenHands
Python 3.12; and Docker external-agent zero-model security. The local v33 regression suite passed
`10` tests before the one authorized invocation.

Full evidence remains outside Git at
`/data/jzhu484/Agent/experiments/openhands-hwe-v33-codex-free-canary-materialization-v1`.
It contains exactly 22 regular files. The complete evidence-directory hash is
`62963cb8d23d48ae31b328d27648fb693d263b698be526f4b7aa4e6df4aa02e6`.

## Headroom and terminal state

The execution-time absolute headroom gate passed before the first image build. Its canonical
preflight hash is `8528772c5054aeefd2aa6a600842ab019cdbebff1a3cabc4683f0f40d5344d4f`
and its file SHA-256 is
`ceed473a536a1950d48d8ae82f7d09281c2d6447c218d1b47a4e7440294476e4`.
It checked the frozen byte and inode minima for the control root, Docker root, scratch root, and
output parent without persisting resolved host paths or raw Docker output.

The final `materialization-progress.json` has file SHA-256
`267c8340e98b81a092216afccc5dadd0834960613920499c392f34522dd78839` and canonical progress hash
`463aa8016d62e947421379cd925009c131a589d754e0c17e7c7f83c72fef26df`; independent recomputation
matched both. Its status is `completed_codex_free_canary_contract_materialized` and its six lock
bindings are complete.

## Six task-keyed command-image locks

Every image was derived with Dockerfile `RUN` networking set to `none`, then scanned under the v2
scanner profile in a distinct runtime container with `network=none`, read-only root, non-root
UID/GID, cap-drop `ALL`, no-new-privileges, bounded resources, and only the visible workspace
mount. All six scans report no Codex command, executable, library, auth material, hidden verifier,
reference patch, public payload, or provider credential. Temporary scan containers and workspaces
were removed, and no scanner-owned container remained after the run.

- PR-2330: command image
  `sha256:3ba2d622fbec6891484c8529892be39db33e02127ec9aaec80381b7d87e64540`, lock
  `c0954bdec2d6f3a1db3cc89aa4045eefd3260eee7ccd82d9bb1b6fb0dfd2e3f8`, security scan
  `fe2b861d0c30c41b70cc62859de54cd1b99d45998c742ae37a21dd080f79afd4`.
- PR-3226: command image
  `sha256:8b693c06696f4afa6c731e2c4cd98b48de8c67b50431c1fd33d5a700b555f6bb`, lock
  `ee9ea16b67e910adb591c473d53fc6dfd73fe3935126e8a372d00be9d6159a3e`, security scan
  `e3b1ce79576cba909f0eb42d22db4a95a057754f49aabe63ee16a8008f97d9c0`.
- PR-3231: command image
  `sha256:eb297f624b2cacc2bcd89c9592a313ceba53f8fa06dc7dfa6c040052f42a2e8f`, lock
  `bfa5d99faf7f9c5e69dea173da717fd744f6db46d16c4a655f026e23fb2a6406`, security scan
  `ef76407bb2565de32a241e67e06111f824edca11b1db06ff21a704dbd18e8941`.
- PR-2989: command image
  `sha256:541812498a101f75e15f8d33adab60d40c7ba6cc4304ae0d134d8110ccb0f4e8`, lock
  `09427214b0092564922f479cc843710729f277642f830c1d75b98dc9b2be653b`, security scan
  `3757b50ae30063eb11fde6349142eb2af924e83ab38f2db15d93f94ca2e11c47`.
- PR-3059: command image
  `sha256:f4d8673aff7dc8e0a77926e9af6384e129b7bca136d1ed7e5c1eaeaf5a3d5122`, lock
  `a203b5622fdbf8b84ec53e92bf286b389bf873fd8f4ab9d0ec560275e650815b`, security scan
  `ae4e44455afb31073e1aec055a8538b59c7a1a0f949a85e7dc61c28452f77941`.
- PR-3204: command image
  `sha256:ed935e093a8f5df4f081ee94d7fb3696335350053dd74fbbd5178b23c2fd1784`, lock
  `4e6bcb561d1c631955dcf9b4a2475a0b09d5bb6bb6b98441cd20101f893400d7`, security scan
  `55e94ec5fd12482534238867e109f920779685d0ef9f18b0db03e99f88be62cf`.

All six command-image IDs are distinct, exist in the local Docker content store, differ from their
verifier base images, and bind the frozen task/source/verifier identities. The v32 failed image IDs
were not imported or reused.

## Catalog, contract, and artifact scan

The command-image catalog has canonical hash
`05be424d40014e7ef69106f85e5ea161db2bb8e70103c8d1279e4a7c118f8e05` and file SHA-256
`08c31fb7ad13d96fda850f114b34688ec22c0d96a865eb21e5d19fe03df5a423`. It binds the six locks,
the five reserve roles, PR-3204 canary validation role, `episode_container_exec_v1`, build and
runtime network `none`, no Codex, and no provider credentials.

The successor canary contract has canonical hash
`6acc93394bbfd0023063d218033316750cfc92b02a173e1ad5771ca563453687` and file SHA-256
`aefeada906fe1e694842a1319a2718110ed83aa4306f69e731de0a9898d4f139`. It selects exactly PR-2330
training followed by PR-3204 validation, seed 489, sample index 5, DeepSeek v4 Flash, OpenHands
1.42.1, LiteLLM 1.93.0, tiktoken 0.7.0, temperature zero, 64 provider calls, 1,000,000 provider
tokens, a 65,536-token context, 2,048 output tokens, zero provider retries, zero whole-episode
retries, and no truncation.

An independent context-aware artifact scan covered all 22 files and 67,206 bytes. It checked active
proxy values and the repository, result, and predecessor roots without persisting or hashing those
values. It found zero hard secret leaks and zero scanner errors under report hash
`a4ca79ae31739417efde47e084534b34a868ac989318c6fc5f150ee1c6fa1a2d`.

## Negative claims and next gate

Provider calls and model processes remained zero. No canary episode, verifier run, trajectory,
decision row, collection, SFT, inference evaluation, GPU job, or held-out load occurred.
`canary_executed=false`, `collection_started=false`, `training_started=false`,
`production_training_ready=false`, and `benchmark_score_claimed=false` remain fixed.

This audit authorizes no provider call by itself. A separately reviewed v34 runner and
authorization must hash-bind this exact result, both canary command locks, the frozen Qwen
tokenizer, runtime identity, and all six result planes. Only after that authorization merges and
its main-branch eight-class Actions run passes may the two zero-retry canary episodes execute.

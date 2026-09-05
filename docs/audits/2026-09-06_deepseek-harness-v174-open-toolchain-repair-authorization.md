# DeepSeek Harness v174 open-toolchain qualification repair authorization

Date: 2026-09-06

## Decision

Authorize exactly one zero-provider invocation of
`deepseek-harness-hwe-v174-open-toolchain-qualification-repair-v1` after this implementation is
merged to `main` and all eight post-merge workflow classes pass. V174 is a fresh successor to the
sealed v172 pre-output stop. It is not an in-place retry and may not create a model process, call a
provider, collect a trajectory, authorize the v176 research canary, admit SFT data, start training,
or establish a benchmark score or production-ready state.

The successor manifest hash is
`c37283cdeacd5aca01696cbfb4e99e82c1e8c415c922a442dd63e5d5e819b759`. It binds the frozen v172
manifest and has file SHA-256
`3017882852b3bc59e1d75f628798d1b978338f3f91cdd1d3282abb6bea38b2f5`. The frozen v172 manifest
file SHA-256 is
`5a59db25c0d5de9e54b9cf375d925a3167d8629f70e4dd4b60a9749bfcc2a157` and manifest hash
`1b5675fbf6022728779be8b158c752dc0128197e8a14e44ebca8e369fea4a5ee`.

## Frozen stop and audit

The sole v172 invocation stopped before output, scratch, Docker mutation, task access, verifier
execution, or provider access because it compared a bare digest component with Docker's complete
`repository@digest` value. V173 froze that invocation as infrastructure-invalid with no task or
provider consumption. V174 requires all of the following predecessor identities:

- v172 stop receipt hash:
  `ce78e74389439bb75b7abbc8fcce687b573da2673c5214f639e0a47a2a540a03`;
- stop receipt file SHA-256:
  `0af45d6c2d67c4de1f86d1bbf3ef694f7961ee9e6598f89a20f649250e123945`;
- stop evidence tree hash:
  `2b8962a93e2849ae142611967006a2cddac6de14263c746bdad9078b250c1846`;
- v173 audit SHA-256:
  `4401a476718a9e33462573e9c34d143c6e14a782532ca13dc03c92f5b68ad17e`;
- v173 audit commit `43b56b6fc001ba55ed77055b40220f336565513e`;
- v173 merge commit `c63c656362e12b96e19064a296cf0b46c12143c6`;
- v173 post-merge `main` run `33980858187`, with all eight workflow classes passed.

The owner-only receipt directory must still contain exactly one ordinary file with modes
`0700/0600`, owner UID/GID matching the invoking user, and the bound content and tree hashes.

## Narrow repair and immutable inputs

V174 changes only the affected representation gate and campaign-scoped resource identities. The
gate requires exactly one canonical `repository@sha256-digest` entry, repository name `docker`,
the frozen digest component
`sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca`, exact image ID
`sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497`, and platform
`linux/amd64`. Missing delimiters, bare digests, wrong repositories, wrong digests, malformed
values, and duplicate entries fail before output creation.

All PR-1816 task, source, archive, reference patch, public test, official image, open-tool source,
executable, and base-image identities remain those frozen by v172. The v174 final Dockerfile is
byte-identical to the frozen v172 file except that its stage reference uses the required fresh
`v174-builder` tag; its SHA-256 is
`3ceb9e32f5f710cc968ddb4e82bc1080b5f524eec721894e8541ff8ca4d28717`. This prevents the fresh
DinD build from depending on or recreating the retired `v172-builder` tag. The v172 runner,
manifest, Dockerfile, result, and evidence are never modified, opened as a runtime, relabeled, or
reused as qualification output.

## Fresh resources and publication gate

V174 uses only fresh resource names:

- output and scratch roots under `/data2/jiadongzhu/Agent/` containing `v174`;
- bind-backed DinD data and socket paths under
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v174/`;
- `verigym-deepseek-harness-v174-dind-data` and
  `verigym-deepseek-harness-v174-dind-socket` volumes;
- builder tag `verigym/open-rtl-tools:v174-builder` and final image tag
  `verigym/open-rtl-tools:hwe-v174-pr1816`.

The frozen v172 implementation supplies the already reviewed offline build, security scan,
read-only non-root command runtime, `network=none` routes, PR-1816 public-test comparison, official
HWE verifier, toolchain/verifier role binding, and cleanup. The v174 wrapper temporarily applies
only the reviewed fresh identities and restores the imported module state afterward. After the
offline open-image build, it loads the official image from the completed local tar before the
security scan so the required image/layer separation check has both immutable inputs. It cannot
publish `qualification-contract.json` until both the open diagnostic and official authoritative
route reproduce base-FAIL/reference-PASS, the image scan passes, and cleanup succeeds. Any failure
publishes only a non-authorizing stop report and removes v174-owned resources.

A successful v174 result retains only its `/data2` DinD data volume with one reopen budget and
remains pending an independent v175 audit. PR-1816 canary seed/sample `503/19` is deferred to v176
or later and is not authorized by this document. Registry access, `.partial` files, provider
clients and credentials, Codex, `LocalRuntime`, collection, candidate mixing, SFT, GPU work,
training, and production readiness remain forbidden.

## Reviewed v174 implementation identities

- `docker/open-rtl-tools-hwe/Dockerfile.v174`:
  `3ceb9e32f5f710cc968ddb4e82bc1080b5f524eec721894e8541ff8ca4d28717`
- `src/verigym/hwe/open_toolchain_successor.py`:
  `909d8491e8b2c401fae16a4412ec1201b0b2fba845c6097a07c6759fe6bdadc8`
- `scripts/materialize_hwe_deepseek_harness_v174_open_toolchain_repair.py`:
  `7020f9f4cf84a22b2ca76faa5ee5b0ffed1b576d6c36b6cd459d94ac4cecdb44`
- `scripts/launch_hwe_deepseek_harness_v174_open_toolchain_repair.py`:
  `4a78ea3a99116fe54bbeb83ef97b42c392c17daaf59d3d08fb415c31cada471d`
- `tests/unit/test_hwe_open_toolchain_successor.py`:
  `7ea41b609e0c4e9125ecce3852ed8562b2b4f1107a9878f636be5418c8ef18d2`
- `integrations/verigym-deepseek-harness/tests/test_v174_open_toolchain_repair.py`:
  `63f99b7ee8a4a3ea343e261f2daad6cbca79329869844a8ebd01cc220ac72c52`

## Execution sequence

1. Merge this authorization to `main` and require all eight post-merge workflow classes to pass.
2. Confirm the seven pre-existing user-untracked files remain unchanged and no additional
   untracked file exists.
3. Invoke the v174 launcher exactly once with that new successful post-merge run ID. The launcher
   removes provider and ambient Docker endpoint names without reading or emitting their values.
4. Independently audit the complete result as v175, merge that audit, and again require all eight
   post-merge workflow classes before considering any v176 canary.

Run only after the first two gates:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V174_OPEN_TOOLCHAIN_REPAIR=1 \
  python scripts/launch_hwe_deepseek_harness_v174_open_toolchain_repair.py \
  --post-merge-main-run-id <successful-v174-main-run-id>
```

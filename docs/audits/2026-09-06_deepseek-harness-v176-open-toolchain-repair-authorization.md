# DeepSeek Harness v176 offline open-toolchain repair authorization

Date: 2026-09-06

## Decision

Authorize exactly one zero-provider invocation of
`deepseek-harness-hwe-v176-open-toolchain-qualification-repair-v1` after this implementation is
merged to `main` and all eight post-merge workflow classes pass. V176 is a fresh successor to the
sealed v174 builder stop. It is not an in-place retry and may not create a model process, call a
provider, collect a trajectory, authorize the v178 research canary, admit or mix SFT data, start
training, or establish a benchmark score or production-ready state.

The successor manifest hash is
`df3b74b1fd353e45d4a69c5458d5e242d42658662cc0961c02494be76a037b14`; its file SHA-256 is
`c676fdfcb7be5b3db1716d1fbfa73f836f3cb05505d5458680c804bde4fa3404`. It reuses the v172
immutable task/tool manifest with file SHA-256
`5a59db25c0d5de9e54b9cf375d925a3167d8629f70e4dd4b60a9749bfcc2a157` and manifest hash
`1b5675fbf6022728779be8b158c752dc0128197e8a14e44ebca8e369fea4a5ee`.

## Frozen v174 result and v175 audit

The sole v174 invocation passed the corrected repository-digest, local image, archive, patch, and
capacity gates. It then received a nonzero result from the generic offline Icarus builder command.
Because the frozen helper discarded stdout and stderr, the available evidence does not prove a
unique low-level cause. The stop occurred before DinD start, image transfer, HWE image load, source
preparation, a task or verifier attempt, and every model/provider boundary.

V176 binds the owner-only result root
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v174-open-toolchain-qualification-repair-v1`
with tree hash
`afdc5db0dacdc6e50e59de73e107c014aa02893eaa15d2e4d7b8951db34884f5`. It requires mode `0700`,
UID/GID `1004:100`, and exactly these ordinary mode-`0600` files:

- `archive-receipt.json`:
  `a74732ebd3a3751b4463fad864fbb0fb0903f5c93f789313856de554146d508c`;
- `headroom.json`:
  `819feef8fbe6481a96507dc72fbd927f016435a7667ebb35959791f2ca264808`;
- `materialization-progress.json`:
  `45ab28c7b5182a122bcf07143ade4b2426a3c644fb7fd4e1b75d6be5fad658a5`;
- `reference-patch-compatibility.json`:
  `e5e8aa3a47f0716b019dac51882db009573ba98ed1941fdbaca703c4e81696b7`;
- `zero-provider-report.json`:
  `45ab28c7b5182a122bcf07143ade4b2426a3c644fb7fd4e1b75d6be5fad658a5`.

The sealed report hash is
`b7128918f2c5c4b1e8e34dc3dd8464e84360a1e19f1582d492bb5169b42e1780`. It records the v174
implementation merge `1a228923cb696e1a2e41c6fb728dc43bf383af8e`, successful post-merge run
`33983004262`, zero provider calls and model processes, complete cleanup, no contract, and every
collection/training flag false. The exact v174 manifest file SHA-256 is
`3017882852b3bc59e1d75f628798d1b978338f3f91cdd1d3282abb6bea38b2f5`, with manifest hash
`c37283cdeacd5aca01696cbfb4e99e82c1e8c415c922a442dd63e5d5e819b759`.

The v175 audit file SHA-256 is
`0eeeedc26c3327e85e18b4a835a82f240e3367f26dcb19a7f97149a1772e6a32`, audit commit
`dffa1cbce672c29559e51bf44456749ea5469d6a`, merge commit
`0a277dde3dd9de38d1b1a27877750898ee0c69f5`, and post-merge `main` run `33983817261`. All eight
workflow classes passed. PR-1816 remains task- and provider-unconsumed.

## Narrow builder repair

The frozen generic builder Dockerfile contained `# syntax=docker/dockerfile:1`. The v176 builder
file is byte-identical after deleting only that directive and its following blank line. It is
hash-bound as
`30563566a5b697d8ff69f32dcd42796bbcdbdcb9a0f317abc9294855b30189e3`. Docker uses its built-in
frontend and still receives `--network none --pull=false`, target `iverilog-builder`, and the fresh
tag `verigym/open-rtl-tools:v176-builder`. Network-bearing Dockerfile steps can succeed only from
the already-local cache; a cache miss stops without a pull, download, or fallback.

The final image Dockerfile is byte-identical to v174 except for changing the retired
`v174-builder` stage tag to `v176-builder`. Its SHA-256 is
`d517e768a8e5f56764124e5f3d3531db5e42ca702aa2377787d71d97f85e4343`. It still combines only
the independently accepted VeriGym open-tools image, the generic builder, completed local
Verilator and ripgrep archives, and no tool copied from an HWE task image.

Builder control output is read through bounded pipes with a one-MiB aggregate limit and an
1,800-second timeout. Overflow and timeout kill the client process group. Before a safe output
hash is retained, the controller scans for active secret/proxy values and secret-like markers. A
match stores only the `sensitive_output_detected` category and empty-stream hash sentinels. Every
receipt excludes raw output, command arguments, and environment names and values. Other failures
retain only fixed categories, byte counts, return code, and stdout/stderr SHA-256 values.

## Fresh resources and publication gate

V176 uses only fresh resource names:

- output and scratch roots under `/data2/jiadongzhu/Agent/` containing `v176`;
- bind-backed DinD data and socket paths under
  `/data2/jiadongzhu/docker/deepseek-harness-hwe-v176/`;
- `verigym-deepseek-harness-v176-dind-data` and
  `verigym-deepseek-harness-v176-dind-socket` volumes;
- builder tag `verigym/open-rtl-tools:v176-builder` and final image tag
  `verigym/open-rtl-tools:hwe-v176-pr1816`.

Before output creation the runner validates the complete v174 tree, v175 audit, v172 inputs,
completed non-partial archives, exact accepted open-tools and DinD identities, canonical
`docker@sha256:...` repository digest, platform, fresh resources, and clean merged source. It loads
the completed local official HWE tar only inside the fresh network-none DinD daemon and before the
agent/official image-separation scan. It never contacts a registry.

The same public PR-1816 test must independently produce base-FAIL/reference-PASS in the VeriGym
open image and the official digest-locked HWE verifier. The open result remains
`agent_only_non_authoritative`; only the official result is `benchmark_authoritative`. The atomic
qualification contract is last and requires both routes, the image scan, role binding, inner and
outer cleanup, and no partial result. Success retains only the v176 DinD data volume with one
reopen budget and remains pending an independent v177 audit. Any DeepSeek research canary is v178
or later and is not authorized here.

## Reviewed implementation identities

- `src/verigym/hwe/open_toolchain_repair.py`:
  `065c5d1c56327efb4e589952ab46f2a89b7125a95e68b3ef6f60904f6cca9f47`
- `scripts/materialize_hwe_deepseek_harness_v176_open_toolchain_repair.py`:
  `e87ae2bee6fdd5a856ad6d28b9f1f46e1705da59e5184ba4691ef7ec5a08b085`
- `scripts/launch_hwe_deepseek_harness_v176_open_toolchain_repair.py`:
  `77137acbff5f7439ed9b59abaa2499e41682d8d5c9c80838812ef894e72d092f`
- `tests/unit/test_hwe_open_toolchain_repair.py`:
  `5cdb9292caa10d72d481ad945fd5b2e20fab3b84f948c05195d9afb333cbfc55`
- `integrations/verigym-deepseek-harness/tests/test_v176_open_toolchain_repair.py`:
  `b3ee5316fb04907daa27725570a9b9b9b9a4d669334cd17e41ee6f76836311e4`

## Execution sequence

1. Merge this authorization to `main` and require all eight post-merge workflow classes to pass.
2. Confirm the seven pre-existing user-untracked files remain unchanged and no additional
   untracked file exists.
3. Invoke the v176 launcher exactly once with that new successful post-merge run ID. The launcher
   removes provider and ambient Docker endpoint names without reading or emitting their values.
4. Independently audit the complete result as v177, merge that audit, and again require all eight
   post-merge workflow classes before considering a v178 research canary.

Run only after the first two gates:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V176_OPEN_TOOLCHAIN_REPAIR=1 \
  python scripts/launch_hwe_deepseek_harness_v176_open_toolchain_repair.py \
  --post-merge-main-run-id <successful-v176-main-run-id>
```

# DeepSeek Harness v172 open-toolchain qualification authorization

Date: 2026-09-06

## Decision

Authorize exactly one zero-provider invocation of
`deepseek-harness-hwe-v172-open-toolchain-qualification-v1` after this implementation is merged to
`main` and all eight post-merge workflow classes pass. The invocation is limited to the reserved
Ibex PR-1816 offline comparison. It does not retry v170, consume any provider task, call a model,
authorize the v174 canary, collect a trajectory, admit SFT data, start training, or establish a
benchmark score or production-ready state.

The checked-in manifest hash is
`1b5675fbf6022728779be8b158c752dc0128197e8a14e44ebca8e369fea4a5ee`; its file SHA-256 is
`5a59db25c0d5de9e54b9cf375d925a3167d8629f70e4dd4b60a9749bfcc2a157`.

## Frozen predecessor and task

- V171 audit commit: `36ce67072a0eb8cba63e5733d65ebdeee594ef9e`.
- V171 merge commit: `ca90ee8a968507845c1a1639068434b24046104c`.
- V171 post-merge run: `33977853144`, all eight workflow classes passed.
- V171 audit SHA-256:
  `5c97f38da7760201df69d5241e30e4cd2a6830adf5f3a4d4ef0eb205c8c631d6`.
- Task: `hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1816`, reserved and unconsumed in
  v69.
- Dataset SHA-256:
  `1b2d2875f105c07c75b787ce563aee35d9e457f29b75befec3bc25cf3a18f445`.
- Selected row SHA-256:
  `9c2f2709263f7570aa7633405c44028eefdb05694bbf682f45fd200f561b021a`.
- Public source commit: `7b1be3354d650bc5b23dff6f439459c353288e4f`.
- Completed image archive SHA-256:
  `91395d522a65b0ae35f9c4504d74aa5a460242ab6629bcdfb1155c6cbc6821ed`.
- Registry manifest lock:
  `sha256:76354a052a27a2fde5bb2b2d389600008b9c115f45d219265051ea325d3a32dd`.
- Official verifier image:
  `sha256:7ad60e4cd099379b038d99def95f3a310d2f636116d8790f778b1f93ee2f20f7`.
- Reference patch and public test script SHA-256 values are respectively
  `747b30bc2b8de5d588bbffd3364e6b1a27b66df791ccf60cd474d6cc9c6ec184` and
  `0eba51fc1c255a184caa1705f9aa97f97a9c1c2092d7e3e42627e5bc17533d17`.

Only the completed local archive under
`/data2/jiadongzhu/Agent/hwe-bench-public-images` is eligible. Registry access and `.partial`
inputs are forbidden.

## Frozen open toolchain

The agent-only identity is `verigym-open-rtl-tools-v1`; it is different from the official
verifier identity. The accepted open parent image is
`sha256:77aa99d8afc4143f6168f749075a20f387f46d38080f228b7e7ff8e85fcbeaa6`.
The final image must contain these exact source identities:

- Verilator v5.008 archive
  `1d19f4cd186eec3dfb363571e3fe2e6d3377386ead6febc6ad45402f0634d2a6`, annotated tag object
  `80d8136c28413c549523e7761999c6eaeffe7a14`, peeled commit
  `21093fd1bd36fed8943f67868ddc8f75f41e4488`;
- Icarus v12 commit `4fd5291632232fbe1ba49b2c26bb6b2bf1c6c9cf`;
- Yosys v0.67 peeled commit `2d1509d1bcb8df0723f6790057e3b1d21c876683`;
- ripgrep 15.2.0 archive
  `33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c` and executable
  `e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849`.

The builder comes only from the cached `iverilog-builder` target in VeriGym's open-tools
Dockerfile. The runner must materialize it with `--network none --pull=false`, transfer it and the
accepted open image to a fresh DinD daemon, and build the final image with the same network and
pull restrictions. Neither open image may inherit or copy from the HWE task image.

## Isolation, evidence, and publication gate

The DinD image and repository digest are fixed to
`sha256:c4bd0ed11d7938604a08f2b67a73107757b1c88ece26ec6a8ef0214c2afd4497`
and `sha256:afa5d51349001a4293bab02d2988290db5eae393a83405b1f458c0dd44e2f3ca`.
Fresh bind-backed data and socket volumes live only under
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v172/`; the host Docker root may cache the generic
builder but may not store PR-1816 task layers. The outer daemon, build, agent command, and official
verifier networks are all `none`.

Every command probe must use a mapped non-root user, read-only root, cap-drop `ALL`,
no-new-privileges, bounded resources, and no mount or exactly one workspace mount. The scan must
lock all eight executables, reject provider/proxy environment names and Codex, verify that the HWE
task image is not an ancestor, and persist only bounded hashes and counts. The runner may retain
the successful `/data2` DinD data volume with exactly one later reopen; it must remove the socket,
temporary transfers, host builder tag, and all containers.

The open public-test result is `agent_only_non_authoritative`; the official HWE result is
`benchmark_authoritative`. Both must independently reproduce base-FAIL/reference-PASS and bind
different receipt hashes through `require_toolchain_verifier_binding`. The qualification contract
is the last authority-bearing file and must not exist after any build, security, infrastructure,
test, binding, or cleanup failure.

## Reviewed implementation identities

- `docker/open-rtl-tools/Dockerfile`:
  `662811f2d31a68870a9c39ca887e842ec50c19869f31ac995811edde8ae9b6c4`
- `docker/open-rtl-tools-hwe/Dockerfile`:
  `31e7cade980a0e7a1f73a9e0d4efc5a816a506a791099bf0b557e71d00d1c417`
- `docker/open-rtl-tools-hwe/README.md`:
  `347e6d9555490c49cf2752bff19f976b00f5202a5876121aabbf487e2d9ee4c4`
- `src/verigym/hwe/open_toolchain.py`:
  `9808b9bb498dea55a3557079cbae91ab981c1ab38583cd0b904b15978bddc36b`
- `scripts/materialize_hwe_deepseek_harness_v172_open_toolchain.py`:
  `4c542ac687798d9893a7a7243b9467d60a8b24d0a5aadf8b771aa28c4a912758`
- `scripts/launch_hwe_deepseek_harness_v172_open_toolchain.py`:
  `15a99cfcc3ed5329c9beffc0476aaff68e6d1cf17fa506cf1fe18553e24f6095`
- `tests/unit/test_hwe_open_toolchain.py`:
  `29ffc3ff1d331ae6e2c00ddcf235ce708654c972e0412119897f26ca570bd743`
- `integrations/verigym-deepseek-harness/tests/test_v172_open_toolchain.py`:
  `287f112612edb9abdf8b344d3730e98abf830a8fecc7c5dce0c71c0a0679af7b`
- `SECURITY.md`:
  `30e8dc6a1d6d5a915e33a11711b042fc6c033bb990677e4ff72d240ba0c8b179`
- `docs/hwe_deepseek_harness_collection.md`:
  `6e8becdbfce07a65ebf04abef40a6c1078486be5c64eb5c9d145d4446ea3e836`

## Execution sequence

1. Merge this authorization to `main` and require all eight post-merge workflow classes to pass.
2. Confirm the seven pre-existing user-untracked files are unchanged and no additional file is
   present.
3. Invoke the launcher exactly once with the successful post-merge run ID. Provider values must
   not be printed, persisted, or hashed.
4. Independently audit the complete result as v173, merge that audit, and again require all eight
   post-merge classes before considering a separately registered v174 research canary.

All formal collection and training flags remain false.

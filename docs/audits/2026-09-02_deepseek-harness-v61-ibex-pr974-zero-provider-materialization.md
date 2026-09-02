# DeepSeek Harness v61 Ibex PR-974 zero-provider materialization

## Decision

Ibex PR-974 is the fresh task selected for the DeepSeek Harness fallback after the OpenHands v58
canary failed closed. Selection excluded historical and consumed Ibex tasks and then ordered the
remaining public tasks by changed lines, modified-file count, and PR number.

This audit qualifies the task and its credential-free command image with zero model calls. It does
not authorize a provider call, rerun OpenHands, start formal collection, produce SFT rows, or start
training. A real-model canary requires a distinct authorization after this change merges and all
post-merge `main` checks pass.

## Public task qualification

- task: `hwe-bench/repo-repair-v1/lowRISC__ibex__pr-974`;
- official dataset revision: `1403afb57ce056c659c82b35e39c38c6a21ee635`;
- official source commit: `10c78a87e1f92695d78d15b1464a6107dcac8837`;
- archive SHA-256: `d21157cbf4fe870430a49d364c45b666b57823c5d9329537592f2906d0a95a4d`;
- OCI manifest digest:
  `sha256:7fd72a7f02106ae81969561724e08eedb1e3b3c9c532a6c1a27981646331c0bd`;
- verifier image ID:
  `sha256:ac668cbaf8b16e2804adf222834a06965282841bc30927fe5f98e3a2239b431b`;
- base candidate: FAIL with no infrastructure error;
- official reference candidate: PASS;
- verifier runtime network: `none`;
- provider calls and model processes: zero.

The external smoke report SHA-256 is
`8cd06c4774e0d046cdf04eb3c5cffbda367c5f8ba6dc2e00db5f252dee945f9f`.

## v60 infrastructure finding and v61 repair

The v60 command-image build stopped before provider authorization because PR-974's official image
does not contain the Icarus tools assumed by the earlier PR-54 image. PR-974 instead contains the
system Verilator 4.038 toolchain. The task remains provider-unconsumed.

v61 makes the Ibex command image toolchain explicit. The existing `iverilog` profile remains the
default and unchanged for prior callers; a separate `verilator` profile requires both the wrapper
and native binary, binds their hashes in the source and command locks, and verifies the chosen
profile in the image label and build receipt. The scanner now also applies each repository
profile's exact environment during its isolated runtime test.

- toolchain profile: `ibex-verilator-system-container-native-v1`;
- command image ID:
  `sha256:d888a3faa8fe5d6cf3717f8488a96e5a8ce5d3122d0da321dcb3fbafe8ae6bab`;
- command-image lock hash:
  `ce72dd5277f44407a2c2b64bc2b3989e30625cd2727c2d87b7b8829dc9e4fd22`;
- security scan ID:
  `7b0bccf29d490b1b22a104c0ba29a2df34486484644ce6d17e15635db86690dc`;
- source whiteout: `/home/ibex`;
- runtime controls: non-root, `network=none`, read-only root filesystem, cap-drop `ALL`,
  no-new-privileges, bounded resources, and one writable repository mount;
- Codex, provider credentials, hidden assets, reference patch, verifier payload, and task source:
  absent from the command image.

The external zero-provider result hash is
`81a41375faa6a1fce41b9fd3b5f0e2d98ead2ff961b96a1d8b4330115437574a`.

## Credential-free verification

- PR-974 base/reference verifier qualification: passed;
- real v61 command-image security scan: passed;
- DeepSeek Harness fake-provider and contract tests plus HWE preparation/verifier regressions:
  62 passed, 2 deselected;
- command-image unit and scanner tests: included in the 62 passed result;
- scoped Ruff, formatting, and Mypy: passed.

All collection and training flags remain false. PR-974 may be considered only by the next distinct
provider authorization after merge and post-merge `main` success.

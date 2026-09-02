# OpenHands Ibex PR-54 zero-provider materialization

## Decision

Ibex PR-54 is a fresh public training candidate for an independent OpenHands successor. It was
selected as the smallest completed, unconsumed Ibex archive by changed lines, modified files, and
PR number. Historical Ibex PR-167, PR-222, and PR-1735 remain excluded and unchanged.

This result qualifies and materializes PR-54 without making a provider call. It does not authorize
a provider canary, formal collection, SFT, training, or held-out access. A future provider canary
requires a distinct frozen identity after these changes merge and post-merge `main` checks pass.

## Public task and verifier qualification

- task: `hwe-bench/repo-repair-v1/lowRISC__ibex__pr-54`;
- official dataset revision: `1403afb57ce056c659c82b35e39c38c6a21ee635`;
- official source commit: `10c78a87e1f92695d78d15b1464a6107dcac8837`;
- archive SHA-256: `b33b1d7e5c1ff4d0f7c8182aaa2c2a31dd8616df631365b5912ecec1616a8f94`;
- manifest digest: `sha256:9ba521df2c63b467815288dadd5cee9ca413594cc39afa1c724b25fc2642f798`;
- verifier image ID: `sha256:a35075b506d4d8b4e9434e31f38ee0699afdb18f7119e324d49bee60565f5bfa`;
- base candidate: FAIL, with no infrastructure error;
- official reference candidate: PASS, one of one verifier node passed;
- verifier network: `none`;
- model processes and provider calls: zero.

## Credential-free Ibex command image

The historical CVA6 command-image path was generalized without changing existing CVA6 defaults.
The Ibex profile removes `/home/ibex` and `/home/ibex_base_commit.txt`, retains only hash-bound
public build/simulation tools, adds the independently acquired ripgrep 15.2.0 release, and uses
repository-specific runtime labels.

- command image ID: `sha256:6f88fdae127f75326407b4ebff529fea5f87aeb64997970d4408678fab942c3b`;
- command-image lock hash: `3f7e090239e1230054620a7a51330a16bef54e084a395dcd294e60de003bb798`;
- security scan ID: `1bd004e75bdf245596bd1bcd3021d184123203711c30fda24969d040656ed281`;
- scanner profile: `ibex-hwe-command-container-native-offline-v1`;
- all 29 image and runtime checks passed;
- runtime uses non-root execution, `network=none`, a read-only root filesystem, cap-drop `ALL`,
  no-new-privileges, bounded resources, and one writable repository mount;
- Codex, provider credentials, hidden assets, reference patch, verifier payload, and task source
  are absent from the command image.

The external zero-provider result receipt hash is
`6632d5741204a396c6723db495ba1d22ac13178d5328acfd4314fa623b88e5d8`.

## Credential-free verification

- OpenHands SDK: 1.42.1 on Python 3.12;
- v23 protocol plus trajectory regressions: 40 passed;
- command-image and scanner unit tests: 12 passed;
- OpenHands command-runtime tests: 3 passed;
- scoped Ruff and formatting: passed;
- scoped Mypy: passed;
- real PR-54 base/reference smoke and real command-image v2 security scan: passed.

These checks validate the zero-provider infrastructure and scaffold only. PR-54 remains
provider-unconsumed, and all collection/training flags remain false.

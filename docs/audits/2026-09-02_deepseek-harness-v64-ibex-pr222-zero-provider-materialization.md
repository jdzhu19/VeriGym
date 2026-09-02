# DeepSeek Harness v64 Ibex PR-222 zero-provider materialization

## Decision

The v62 PR-974 attempt failed before a provider request because the v4 adapter retained the v3
outer-runtime startup check while the intended v4 architecture uses a host Harness control plane
and a separately isolated episode command image. The v63 result audit froze PR-974 and authorized
only an offline scaffold repair on a fresh task.

v64 fixes that exact mismatch without changing the historical v2 or v3 execution contract. The v4
adapter now accepts only the pair `runtime_external_process_unavailable` and
`episode_container_exec_v1`, together with Docker standard isolation. Every other pair fails
closed. The integration version is advanced from 0.3.0 to 0.4.0.

This audit does not authorize a provider call, start collection, produce an SFT row, or start
training. A real-model PR-222 canary requires a distinct successor authorization after this change
merges and all eight post-merge `main` job classes pass.

## Fresh task qualification

The deterministic local Ibex selection excluded the historical or consumed PR-54 and PR-974
tasks, then ordered the available tasks by changed lines, modified files, and PR number. PR-222
was selected ahead of PR-1735 because both change 10 lines in one file and 222 is the lower PR
number.

- task: `hwe-bench/repo-repair-v1/lowRISC__ibex__pr-222`;
- official dataset revision: `1403afb57ce056c659c82b35e39c38c6a21ee635`;
- official source commit: `10c78a87e1f92695d78d15b1464a6107dcac8837`;
- task hash: `7e62a998631bf29c57260dbeefbdb9fb442b6828a9f6f548aa92ea2751a4a682`;
- source hash: `196991d6eebeb73106594898bd4e6068d8f5d6ee02417bb7b90eab19386e5c8e`;
- OCI manifest digest:
  `sha256:7c8b3368a6bb5f12b19f52e2e34271233c70bccffb6c734c2bb8a9a54e95a572`;
- verifier image ID:
  `sha256:cde141cb0f4c8458dc1f0339c2834090126e70101adfca7b4910d23b54046c58`;
- base candidate: FAIL with no infrastructure error;
- official reference candidate: PASS;
- verifier runtime network: `none`;
- provider calls and model processes: zero.

The prepared-source image-lock file SHA-256 is
`9ebafcdf634de7929ca22679084760f3d2814315b2aa5588b0d06d9adadc8135`; the external smoke
report SHA-256 is `c378eaab2edeb510b889f8a169821840c4f2b6fdde9521258d044c0133a780a0`.

## Command image and dispatch evidence

The PR-222 verifier supplies the same bounded system Verilator profile previously qualified for
PR-974. The v64 materializer rebinds every public tool hash to PR-222 and runs the real isolated
scanner.

- toolchain profile: `ibex-verilator-system-container-native-v1`;
- command image ID:
  `sha256:6502d4239228942b702724c596c54938352c90a69f65891291761e3d18ceff04`;
- command-image lock hash:
  `ccd1570f4614f57e1c4df6d4a26510081ca9486a6409e7474a0e52a134cbd5ed`;
- security scan ID:
  `c8dc75f9b69b82f1327e16da3359b9ef49583b410bad50167e4da4113fa4d14b`;
- security scan passed with no detected secrets;
- build and command-image runtime networks: `none`;
- source whiteout: `/home/ibex`;
- command-image lock file SHA-256:
  `f807bc499314faafdde64aa40f8da132ca6ace25effa18c774b36d236e6620ab`;
- security-scan file SHA-256:
  `1ef6363357588737f4ceaecfc67ca50809a2d9a03af08d13efb10ccaef0b71f2`;
- zero-provider result hash:
  `c44009dc5d2a3f6b09922bae3b8f5d8be9d5048d921d1b13c34a24af768de06f`;
- zero-provider result file SHA-256:
  `d88ca03c85a940928fd0aaf1c1d64af5ab6052d14ad9e8cb951d33c95b1cb83f`.

v64 also creates a private, fixed-content marker exactly at the Harness `agent/request` boundary.
It contains only a format identifier and the ordinal `1`; it contains no endpoint, credential,
prompt, response, timestamp, or credential hash. The core validates the file type, size, path, and
exact payload, emits a bounded trace event, and records a lower-bound provider-request count in the
collection evidence. Initialization creates no marker. This prevents a future pre-provider startup
failure from being mislabeled as a consumed model task.

## Credential-free verification

- exact v4 bridge startup regression: passed;
- v4 backend-drift rejection and frozen v3 execution requirement: passed;
- official Harness controller with one-action fake provider: passed;
- same-session content-only recovery with fake provider: passed;
- private first-request marker validation in both fake-provider paths: passed;
- real PR-222 command-image security scan: passed;
- scoped Ruff, formatting, Mypy, and DeepSeek Harness contract tests: passed.

All formal collection and training flags remain false. PR-222 is provider-unconsumed at this stage.

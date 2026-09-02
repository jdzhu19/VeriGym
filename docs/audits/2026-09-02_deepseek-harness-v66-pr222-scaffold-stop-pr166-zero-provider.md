# DeepSeek Harness v66 PR-222 scaffold stop and PR-166 zero-provider successor

Date: 2026-09-02

## PR-222 disposition

The authorized v65 PR-222 canary crossed the first real provider-request boundary. The private
fixed-content marker and its bounded public trace event both establish a lower bound of one provider
request. PR-222 is therefore consumed and permanently frozen; no retry is authorized.

The episode stopped after the Harness process returned and before VeriGym could admit an agent
identity, submit the candidate to the benchmark verifier, or materialize a normalized trajectory.
There is no `attempt.json`, canary report, scorecard, supervised decision row, or SFT-admissible
trajectory. Forty private tool observations remain private and are not reconstructed or exported.
This outcome is not a benchmark result and makes no model-quality claim.

The atomic administrative result is stored outside Git under the v65 experiment root.

- administrative result hash:
  `f3428b3b7d11b1ad996811ac1e946d0339d8d84fc7d1fb21291f3f5b08857dae`;
- administrative result file SHA-256:
  `5b7135a715ed7575de9fc6b6566d6a4b4dff8ca4c70793a58bc65a386fc9894f`;
- public trace SHA-256:
  `fdbc74823773b18c7aec9ccb991ffd7ec5989116334cc181951920682063d2ec`;
- private provider-marker SHA-256:
  `58193428d89d0d331770067ae4f59d18c89333fee2e1071a7a5ba77a78faf81b`;
- task consumed: true;
- trajectory collected: false;
- benchmark verifier ran: false;
- formal collection and training: false.

## Offline scaffold reproduction and repair

Two deterministic local defects explain the stop.

1. `DeepSeekHarnessHweAgentV4Adapter` emitted the new
   `deepseek_harness_hwe_native_shell_v4` integration track, but
   `ExternalAgentCallIdentity` allowed only the historical v2 and v3 literals. Pydantic rejected the
   identity after the Harness process returned.
2. `RuntimeExternalAgentBridge.emit_event` always adds the bounded
   `content_truncated` field to public trace payloads. The v65 runner compared the provider marker
   against the adapter's three pre-bounding fields and rejected the valid fourth field.

v66 adds the v4 identity literal without changing v2 or v3 and advances the integration package to
0.5.0. Credential-free regressions construct the exact v4 identity and verify the four-field public
marker produced through the real core bridge. A future runner must validate the core-bounded marker
shape. The historical v65 runner and result are not rewritten.

## Fresh PR-166 qualification

After excluding provider-consumed or historical PR-222, PR-1735, PR-54, and PR-167, plus the frozen
pre-provider PR-974 identity, PR-166 is the next public Ibex candidate under the deterministic
`changed_line_count`, `modified_file_count`, and PR-number ordering. Its already downloaded archive
was verified and loaded locally without a registry request. No VPN, proxy, downloader, or global
network setting was changed.

- task: `hwe-bench/repo-repair-v1/lowRISC__ibex__pr-166`;
- official dataset revision: `1403afb57ce056c659c82b35e39c38c6a21ee635`;
- official source commit: `10c78a87e1f92695d78d15b1464a6107dcac8837`;
- archive SHA-256:
  `572fe2a2ed101e9e9805c5d24764affafa60dbfd107800b730586fae1745a7cf`;
- OCI manifest digest:
  `sha256:2016bdac103fdfad09a4337c54bd479a270674b38241523bfd9af83130a3b87d`;
- verifier image ID:
  `sha256:b7894597216546304802a6470aab76b0db297854704854b21fa32de3fd80a240`;
- task hash: `d3c05fdf9be2c8c9dae301f702de207c0986dc222625a0c573e1745b14b45d24`;
- source hash: `205b4e61416e4bca5bd7ef8a52167637845b1817e09e960e746b572c7814f18a`;
- source image-lock file SHA-256:
  `aabe5a6bb353f4836e4a69e4a6bf6e922ae0a4a49f8eef40a950b79409b1971b`;
- smoke report SHA-256:
  `8082b21ef140411f573737e4a7f28a0807f4346de4339d01b2bf670f2ba465c2`;
- base candidate: FAIL without infrastructure error;
- official reference candidate: PASS;
- verifier network: `none`;
- model processes and provider calls: zero.

## PR-166 command image

The v66 materializer binds the public Verilator toolchain to PR-166, removes the task workspace and
base-commit marker from the derived command image, and runs the existing credential/hidden-asset
scanner with build and task-tool network disabled.

- command image:
  `sha256:1b5c838add1f3f969ce7e6887fe68c5c84078b2b2920535856751c7bff632809`;
- command-image lock hash:
  `d174aa1ce310c672cafa5820197351250b2b9b7b9fecdc61b1b0f01845a4864f`;
- security scan ID:
  `60277eaa6168466c9b4789374c3a5fab56e049c516360b4efa992dd2a377563e`;
- command-image lock file SHA-256:
  `43c0a0c44da6acdb0b762df9751a5586dec547cb06b00322fd6ef9f9fed04d2b`;
- security-scan file SHA-256:
  `d1c60102ffc0ad902e5b2749c29c7b9831bdeb8e4c2de16204a0461a19de0b1d`;
- zero-provider result hash:
  `5ef5464693bc957eb548232c7a4dfacaf2f80f6e07dc53d48c183f5fc2cfe678`;
- zero-provider result file SHA-256:
  `62454c972923bcd2f1e3575415fe0770f6d0049983d4731c379c18f05f9b1354`;
- scanner passed with no detected secrets;
- command and verifier runtime network: `none`.

v66 authorizes no provider request. A PR-166 real-model attempt requires a distinct successor
authorization after these changes merge and all eight post-merge `main` job classes pass. Formal
collection, SFT training, and production readiness remain false.

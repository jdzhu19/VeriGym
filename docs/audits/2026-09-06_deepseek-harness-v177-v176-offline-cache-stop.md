# DeepSeek Harness v177 audit of the v176 offline cache stop

Date: 2026-09-06

## Decision

Freeze the sole v176 invocation as an infrastructure-invalid offline builder stop. V176 consumed
its one authorized invocation and must not be retried, reconstructed, or relabeled. The builder
diagnostic proves that the external Dockerfile frontend dependency was removed, but the complete
generic builder closure was not available to the network-none build. No open-toolchain
qualification contract exists.

PR-1816 remains task- and provider-unconsumed. V176 started no DinD daemon, imported no HWE task
image, prepared no source or workspace, ran neither the open diagnostic nor official verifier,
created no model process, and made zero provider calls. It produced no candidate or trajectory.
Formal collection, formal collection start, collection start, SFT admission or mixing, training,
GPU work, benchmark-score claims, and production readiness remain false.

## Reviewed authorization and invocation

The v176 implementation commit is
`64f39c7bb5794ae14d9e38df7cde65678081d954`, merged as
`2f91bd36df322064118c4ddf5369e1749a0e5e72`. Post-merge `main` run `33985343935` completed all
eight workflow classes successfully before the launcher was invoked. The manifest hash was
`df3b74b1fd353e45d4a69c5458d5e242d42658662cc0961c02494be76a037b14`, and the executed source
commit in the terminal report is the exact merge commit.

The launcher was invoked once with the reviewed post-merge run ID. The exact pre-output gates
passed: clean merged source, the seven-file user-owned untracked inventory, the complete v174
tree, v175 audit, v172 task/tool inputs, completed archive and sidecar, OCI/source/image locks,
canonical DinD repository digest and platform, accepted open-tools image, and fresh v176
resources. Headroom, archive, and reference-patch compatibility receipts were written before the
builder command.

## Bounded builder finding

The v176 builder used the hash-bound
`docker/open-rtl-tools/Dockerfile.v176` with SHA-256
`30563566a5b697d8ff69f32dcd42796bbcdbdcb9a0f317abc9294855b30189e3`. This file is the frozen
generic builder Dockerfile after deletion of only its external `# syntax` line and following blank
line. The command required `--network none`, `--pull=false`, target `iverilog-builder`, and the
fresh v176 tag.

The command returned exit code 1. The content-free diagnostic classified it as
`offline_cache_miss`, not `external_frontend_resolution_failed`, `builder_timeout`,
`output_bound_exceeded`, or `sensitive_output_detected`. The classification means the bounded
capture contained at least one reviewed network/cache-miss marker; because the raw capture was
intentionally discarded, it does not identify which Dockerfile step or dependency was absent.
No narrower causal claim is supported.

The diagnostic records:

- format `verigym_deepseek_harness_hwe_v176_builder_diagnostic_v1` and hash
  `880c73e20541bab3926d1ca03ac524f574f94d445aec5bd80db4ec0ba7dec7a4`;
- file SHA-256
  `3c0d2b23db380f9f1e30abb0271e567dc39030f1c58f71d2b74d505df2920389`;
- zero stdout bytes with the canonical empty SHA-256;
- 4,716 stderr bytes with SHA-256
  `185f146fa144423061cf6ab6e3a1d82bdff74c0b87bae01d0fd8eebf9e2a400b`;
- a one-MiB output limit, no timeout, and output within the bound;
- `credential_scan_passed=true`, `raw_output_persisted=false`, and no persisted command arguments,
  environment names, or environment values.

The stderr contents must not be inferred, recovered, or fabricated from its hash. The digest is
only an equality identity for the safely scanned capture.

## Frozen v176 evidence

The immutable result root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v176-open-toolchain-qualification-repair-v1`

It has tree hash
`46b385dfcb7b1e245bed5ed7b38833a9e2c91099974a52016414b5cb22834a3e`, mode `0700`, owner
UID/GID `1004:100`, and exactly six ordinary mode-`0600` files:

- `archive-receipt.json`:
  `a74732ebd3a3751b4463fad864fbb0fb0903f5c93f789313856de554146d508c`;
- `builder-diagnostic.json`:
  `3c0d2b23db380f9f1e30abb0271e567dc39030f1c58f71d2b74d505df2920389`;
- `headroom.json`:
  `f1aa7bb73100afea95190dc2dee21c778a41ed68785f948ea3429c7250f62ac8`;
- `materialization-progress.json`:
  `b279ff04645092ad5687fd845a18adeaf906b94904fdb1f48fd6ec31f7ab7d67`;
- `reference-patch-compatibility.json`:
  `e5e8aa3a47f0716b019dac51882db009573ba98ed1941fdbaca703c4e81696b7`;
- `zero-provider-report.json`:
  `b279ff04645092ad5687fd845a18adeaf906b94904fdb1f48fd6ec31f7ab7d67`.

The sealed report hash is
`c2b166dc092c9b628aa2dbeff0697b3f5e37ff8b1373d047ab26f2a5256802ff`. Both report copies
recompute to that hash and record `cleanup_complete=true`, `provider_calls=0`,
`model_process_count=0`, `qualification_contract_published=false`, and every collection/training
flag false. The archive receipt again confirms a completed non-partial local archive and no
registry access. The reference patch remains metadata-compatible.

No qualification contract, source tree, official-qualification directory, open comparison,
security scan, image lock, DinD runtime, task receipt, candidate, trajectory, or verifier decision
exists. The v176 scratch root and DinD backing root are absent. Both v176 volumes, the builder and
final tags, and the v176-labeled container inventory are absent. Cleanup did not alter the seven
user-owned untracked files.

## Successor requirements

This audit authorizes no download, build, task, verifier, or provider execution. A separately
reviewed v178 or later zero-provider successor must not repeat the v176 builder command until it
can bind a complete immutable local builder closure.

The preferred route is a completed, hash-bound upstream source/build-input archive or builder
image acquired as a distinct artifact and then consumed with `network=none`. If acquisition is
necessary, it is permitted only as one separately reviewed command after verifying in memory that
the selected route avoids the VPN and that Docker daemon proxying does not redirect it. The
dedicated `verigym-hwe-net` bridge must be used where a controlled container network is required;
the default bridge must not be repaired or restarted. The command may not print, persist, or hash
proxy or credential values. If a safe bypass or fully pinned input cannot be established, stop and
ask the user to provide the completed artifact.

Any successor must use fresh output, scratch, DinD backing, volumes, tags, manifest, scan, and
diagnostic identities; bind this exact six-file tree and the eventual v177 audit merge and green
post-merge `main` run; keep HWE verification on `network=none`; and preserve the distinction
between the open agent-only result and official authoritative verifier. Qualification still
requires both PR-1816 routes to reproduce base-FAIL/reference-PASS. A research canary moves to
v180 or later and requires another independent audit. Collection, SFT, training, and production
readiness remain unauthorized.

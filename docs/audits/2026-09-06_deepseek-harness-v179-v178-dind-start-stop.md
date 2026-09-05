# DeepSeek Harness v179 audit of the v178 DinD start stop

Date: 2026-09-06

## Decision

Freeze the sole v178 invocation as an infrastructure-invalid outer-DinD command stop. V178
consumed its one authorized invocation and must not be retried, reconstructed, or relabeled. No
open-toolchain qualification contract exists.

PR-1816 remains task- and provider-unconsumed. V178 made zero provider calls and created no model
process, task source, workspace, candidate, trajectory, verifier decision, or HWE image import.
Formal collection, SFT admission or mixing, training, GPU work, benchmark-score claims, and
production readiness remain false.

## Reviewed authorization and invocation

The v178 implementation commit is
`3dbd7533671ea1549b5a7fd40e73d519a80f22f1`, merged by PR 204 as
`4cb8c538377f97d4619ff033319027a9a82e0664`. Post-merge `main` run `33988896836` completed all
eight workflow classes successfully before the launcher was invoked. The v178 manifest hash was
`2107ab1537df8d1d70ffa9513b2bd055bd06f521709d4f571ae7e71ffa60ac84`, and the executed source
commit in the terminal report is the exact merge commit.

The launcher was invoked exactly once with the reviewed post-merge run ID. Its clean-main,
seven-file user-owned untracked inventory, predecessor, archive, sidecar, Docker config, source,
image, repository-digest, reference-patch, and fresh-resource gates passed. The headroom receipt
records 13,003,603,968 available root bytes, 36,072,851,537,920 available `/data2` bytes, and
`capacity_satisfied=true`.

The completed `/data2` builder archive passed its eleven-member inventory, config/image ID, two
rootfs diff IDs, canonical-history, sidecar, ownership, mode, and SHA-256 gates. Its receipt hash
is `9a6c4b3f882cc23fdd779883ecb4b70f878548bac85ad6aad329f09d623546eb`.

## DinD start finding

V178 stopped at the outer `docker run`, before an outer DinD container was created. The inherited
v172 command rendered writable bind mounts as:

```text
--mount type=bind,src=<path>,dst=<path>,rw
```

The installed Docker CLI rejects the bare `rw` mount field because `--mount` requires either the
default writable mode with no field or an explicit key/value form. A separately named, bounded,
zero-provider v180 diagnostic reproduced exit code 125 and the marker
`invalid field 'rw' must be a key=value pair`. A minimal container using the same immutable DinD
image, privileged mode, `network=none`, PID bound, empty TLS setting, VFS driver, and group setting
started successfully and was immediately removed. The complete reproduction using the same
three inherited bind-mount forms failed before container creation. Its fresh diagnostic volumes
and empty `/data2` paths were then removed.

This evidence supports category `invalid_mount_write_flag`, not image absence, image corruption,
capacity exhaustion, DinD readiness timeout, default-bridge failure, builder archive failure,
HWE verifier failure, or provider failure. The diagnostic command contained no credential,
provider, proxy, task, source, HWE image, or model surface. Raw diagnostic output was not persisted.

## Frozen v178 evidence

The immutable result root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v178-local-builder-qualification-v1`

It has tree hash
`9fcf31e1af26c3daaac657003306145c6ec10c79a74e09749f847f1cf589cdf6`, mode `0700`, owner
UID/GID `1004:100`, and exactly six ordinary mode-`0600` files:

- `archive-receipt.json`:
  `a74732ebd3a3751b4463fad864fbb0fb0903f5c93f789313856de554146d508c`;
- `headroom.json`:
  `e796459d843e4b8d76f94aa02216715ea3ad312359c2e5dd7f59a810f63ea12b`;
- `local-builder-archive.json`:
  `5d5e42de01642761ecd1a4f441314eb0b4a6be142e5391bf9416605e85750dba`;
- `materialization-progress.json`:
  `faeb12103531ec73d4864c50cf65ca625a0f2fa5e307287cb6c5ba5af8cc2b66`;
- `reference-patch-compatibility.json`:
  `e5e8aa3a47f0716b019dac51882db009573ba98ed1941fdbaca703c4e81696b7`;
- `zero-provider-report.json`:
  `faeb12103531ec73d4864c50cf65ca625a0f2fa5e307287cb6c5ba5af8cc2b66`.

The sealed report hash is
`cd43d763a0c6da672abb6645d0f3067e8eb354a7bff6474b2ea7bc66edf3e2c5`. Both report copies
recompute to that hash and record `cleanup_complete=true`, `provider_calls=0`,
`model_process_count=0`, `qualification_contract_published=false`, and every collection/training
flag false. The HWE archive receipt confirms a completed non-partial local archive and no registry
access. The reference patch remains metadata-compatible.

No qualification contract, source tree, official-qualification directory, open comparison,
builder runtime binding, security scan, image lock, DinD runtime receipt, task receipt, candidate,
trajectory, or verifier decision exists. The v178 scratch and DinD backing roots are absent. Both
v178 volumes, the campaign builder/final tags, and the v178-labeled container inventory are absent.
Cleanup did not alter the seven user-owned untracked files or the persistent `/data2` builder
archive.

## Narrow v180 successor authorization

This audit authorizes a separately reviewed v180 zero-provider successor to change only the three
outer DinD bind mounts from a trailing bare `rw` field to Docker's default writable form with that
field omitted. V180 must bind this exact six-file tree, the eventual v179 audit commit and merge,
and a new successful post-merge `main` run. It must use fresh output, scratch, DinD backing,
volume, container, tag, manifest, receipt, and report identities.

All other v178 locks and behavior remain unchanged: completed local archives only, no registry or
download, outer/build/probe/agent/verifier network `none`, no host Docker socket in the DinD,
non-root read-only builder probe, no HWE-tool inheritance, and distinct agent-only versus official
verifier roles. Qualification still requires both PR-1816 routes to independently reproduce
base-FAIL/reference-PASS and complete cleanup before an atomic contract may be published.

V180 authorizes no model or provider execution. A successful v180 qualification requires an
independent v181 audit and another green post-merge `main` run before any research-only canary can
be considered. Collection, SFT mixing, training, and production readiness remain unauthorized.

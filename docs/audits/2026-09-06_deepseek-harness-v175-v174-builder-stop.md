# DeepSeek Harness v175 audit of the v174 offline-builder stop

Date: 2026-09-06

Status: v174 is infrastructure-invalid and permanently sealed; PR-1816 and the provider remain
unconsumed.

## Authorized boundary

PR #200 merged the v174 authorization as
`1a228923cb696e1a2e41c6fb728dc43bf383af8e` after all 16 PR checks passed. Its post-merge
`main` Actions run `33983004262` completed all eight required job classes successfully. The
implementation commit was `86d6b44699a1f2880ab587a5ed12fa45fdeddabb`, the successor manifest
hash was `c37283cdeacd5aca01696cbfb4e99e82c1e8c415c922a442dd63e5d5e819b759`, and the manifest file
SHA-256 was `3017882852b3bc59e1d75f628798d1b978338f3f91cdd1d3282abb6bea38b2f5`.

The documented launcher was invoked once with that post-merge run ID. It removed all provider and
ambient Docker endpoint names before entering the child. The child verified clean merged source,
the seven allowed user-untracked paths, the frozen v172 stop tree, v173 audit, corrected exact
`docker@sha256-digest` binding, DinD image ID, `linux/amd64` platform, completed PR-1816 archive,
tool archives and executable, accepted open-tools image, fresh v174 resources, and capacity.

After output and scratch creation, it persisted the capacity, archive, and reference-patch
compatibility receipts. It then attempted to materialize the generic Icarus builder from the
frozen VeriGym open-tools Dockerfile with `--network none --pull=false`. That command returned
nonzero and the v174 runner fail-closed with `ConfigurationError` during `offline_tool_builder`.

## Classification and evidentiary limit

This is an offline builder-materialization infrastructure failure. It is not a capacity failure,
archive or patch incompatibility, PR-1816 task result, official-verifier rejection, open public
test result, Harness result, or model result.

The frozen helper deliberately sent build stdout and stderr to null. The stop receipt therefore
correctly retains only the exception class and does not contain raw build output. No unique lower
level cause can be proved from v174 evidence, and this audit does not relabel the stop as a
Dockerfile-frontend, package-cache, source-cache, daemon, or compiler failure. Read-only host
inventory confirms the pinned Debian digest and accepted open-tools image remain present, the
campaign builder tag is absent, and there is no `docker/dockerfile:1` image tag. Those observations
may guide a successor but do not establish causality.

The host build was limited to a generic open-source builder stage and occurred before a DinD
daemon, image-transfer archive, HWE image load, source preparation, task workspace, open test, or
official verifier could exist. It did not expose task RTL or reference contents to a host runtime.

## Frozen v174 evidence

The immutable result root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v174-open-toolchain-qualification-repair-v1`

It has tree hash
`afdc5db0dacdc6e50e59de73e107c014aa02893eaa15d2e4d7b8951db34884f5`, mode `0700`, owner
UID/GID `1004:100`, and exactly five ordinary `0600` files:

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
`b7128918f2c5c4b1e8e34dc3dd8464e84360a1e19f1582d492bb5169b42e1780`. It records
`cleanup_complete=true`, `provider_calls=0`, `model_process_count=0`,
`qualification_contract_published=false`, and every collection/training flag false. The archive
receipt confirms the completed archive SHA-256 and sidecar, OCI manifest/config, registry lock,
repository base, and `partial_archive_used=false`, `registry_accessed=false`. The patch receipt
records `compatible=true`, one text patch file, and no Docker or network access.

No qualification contract, source tree, official-qualification directory, open comparison,
security scan, image lock, DinD runtime receipt, task receipt, candidate, trajectory, or verifier
decision exists. The v174 scratch root, DinD backing root, data and socket volumes, builder tag,
and labeled container inventory are absent after cleanup. The seven pre-existing user-untracked
files remain the only untracked repository files.

## Consumption and state

V174 consumed its single authorized command invocation and may not be retried. It performed one
generic host builder command, but crossed neither the task-image boundary nor any provider/model
boundary:

- zero DinD daemons, image-transfer archives, HWE image loads, prepared sources, or task attempts;
- zero open-tool tests or official verifier runs;
- zero model processes, provider episodes, calls, tokens, or retries;
- no candidate, trajectory, verifier result, SFT admission, or qualification contract.

PR-1816 remains task- and provider-unconsumed. The open-tool qualification has not passed, and no
research canary is authorized. Formal collection, formal collection start, collection start, SFT
mixing, training, and production readiness remain false.

## Successor requirements

This audit authorizes no execution by itself. A separately reviewed v176 zero-provider
qualification successor may preserve the v174 task, archive, source, tool, image, isolation,
dual-route, scan, binding, cleanup, and closed-state contracts while replacing all campaign paths,
volumes, tags, output identities, and audit bindings.

The successor must avoid an external Dockerfile frontend lookup by using a hash-bound builder
Dockerfile without a `# syntax` directive, still require `--network none --pull=false`, and fail if
the complete frozen builder closure is not already local. It must capture only a bounded,
credential-scanned diagnostic category and output hash on a builder failure; raw output and
environment values remain non-persistent. It may not download, pull, contact a registry, use a
partial input, or fall back to a host tool.

V176 must use a fresh output, scratch, DinD data/socket backing, volume, builder tag, final image
tag, and scan identity. It must revalidate this complete evidence tree and the eventual v175 audit
merge and green post-merge `main` run before any build. Success still requires both PR-1816 routes
to reproduce base-FAIL/reference-PASS and requires an independent v177 result audit. Any DeepSeek
research canary moves to v178 or later. Collection, SFT, training, GPU work, and production
readiness remain unauthorized.

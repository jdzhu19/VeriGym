# DeepSeek Harness v183 audit of the v182 bounded build diagnostic

Date: 2026-09-06

## Decision

Freeze the sole v182 invocation as a successfully completed, task-free diagnostic whose bounded
result category is `missing_executable`. V182 achieved its observability and cleanup objective,
but it did not build the final open-tool image and does not qualify PR-1816 or authorize a
DeepSeek canary. Do not retry, resume, reconstruct, or relabel v182.

The category is intentionally less specific than a root cause. Its classifier found the fixed
`command not found`/`: not found` marker after excluding sensitive output, overflow, timeout,
recognized storage exhaustion, recognized compiler-kill markers, and a missing make target. The
receipt does not retain the matching span or executable name, and the category has precedence over
the generic compiler/linker categories. This audit therefore does not assert which executable was
missing or that no secondary error occurred.

PR-1816 remains task- and provider-unconsumed. V182 loaded no HWE image or task metadata, prepared
no source, ran no verifier, created no model process, and made zero provider calls. It published no
qualification contract. Formal collection, SFT mixing, training, GPU work, benchmark-score claims,
and production readiness remain false.

## Authorization and execution binding

The v182 implementation commit is `0b92e078834097f17be0457cac5a5baf78e099eb`, merged by PR 208 as
`8f630d54f26e4193568f0da14dc4a80079436c74`. Post-merge `main` run `33994458259` completed all
eight workflow classes successfully before invocation. The manifest content hash is
`0f11424b5daef309535680695550412d8d9211996be908c499f0795ffe580255`; its file SHA-256 is
`ee7241826c9b90ae6620ae50341548ae1a3cb3c5103cf37eb97a13096c29c4f0`. The runner SHA-256 is
`58aee4b96056178b97529e6dee360ecd80c2e0fe465b6ef67818d06609bc6028`.

The launcher was invoked exactly once with that post-merge run ID from clean merged `main` and the
expected seven unrelated user-owned untracked files. Immutable-input preflight bound the frozen
v180 seven-file result, v181 audit, exact v180 Dockerfile, accepted open-tool image, completed local
builder archive, Verilator archive, ripgrep archive, and Docker 23.0.6 DinD image. The headroom
receipt recorded 10,987,556,864 available control-root bytes and 36,007,932,420,096 available
`/data2` bytes, with `capacity_satisfied=true`.

The isolated DinD daemon passed its exact five-mount inspection with outer `network=none`, no host
Docker socket, and no provider/proxy environment. Only the accepted open-tool image and the
dependency-only builder archive were imported. The builder archive and its mount-free, non-root,
read-only, `network=none` probe passed before the final build began.

## Bounded diagnostic result

The exact v180 Dockerfile ran with `--network none`, `--pull=false`, and plain progress. The client
returned 1 before its 3,600-second limit. Capture stayed within the 16-MiB aggregate bound and
contained zero stdout bytes and 105,787 stderr bytes. The active-value and secret-marker scan
passed. The controller retained no raw output, command arguments, environment names, or
environment values; it retained the safe stdout SHA-256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` and stderr SHA-256
`1afba88edc5d20ff0894ec0ee117d504486124fd9c2b16955beaf383628c3873`.

The fixed category is `missing_executable`. Build diagnostic hash:
`a66b52c6e63700e73b30e8e9f2a336a21d0b6181702e7229830dc2991051660a`.

## Cleanup and frozen evidence

The cleanup helper was required and passed its pre-start inspection. It used the immutable
accepted open-tool image, `network=none`, a read-only root, one writable bind to the exact v182
backing parent, user `0:0`, cap-drop `ALL`, only `CHOWN`, `DAC_OVERRIDE`, and `FOWNER`,
no-new-privileges, private IPC, and fixed resource/output bounds. It emitted no detected sensitive
output. Both named volumes, all v182-owned containers, the backing parent, and scratch were
removed. Cleanup hash: `47341cfc3ff71b8eb9cf67961ff947b407e43fd417e5391c940f884aea3eac78`.

The frozen result root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v182-bounded-open-build-diagnostic-v1`

It has tree hash `7b8a0be1463c9e94133607b8a36e55ba6ca9dfc70e6430f87af19dca2554dfa0`,
mode `0700`, owner UID/GID `1004:100`, and exactly seven ordinary mode-`0600` files:

- `build-diagnostic.json`:
  `4c77a0989eabe36503aa94a370bd03d4116ecea0fad98ed8444c454291b9d92d`;
- `cleanup.json`: `d6ddd32b006a4a90bb8cdd8ce86b80f7df9fcdd5ba212055bf2891a74de88c17`;
- `dind-runtime.json`:
  `642be1a5312b80dd20bf19b77b8cbd74eb7d7739f37145bf8061d5be77027397`;
- `headroom.json`: `2372ab17498ade84ee2b458653c6fabf69886cedbb627b5c9b60efdb7e353405`;
- `local-builder-archive.json`:
  `70e056130f471e60d1629b873022e5b4f299eb7b1b99e37fff01a39f6a3def57`;
- `local-builder-binding.json`:
  `d814c3ca29f51240422f5fe2b7060830ad427c20c7174693a002a0600c3314c9`;
- `materialization-progress.json` and byte-identical `zero-provider-report.json`:
  `acee3fbfc653a2c6a2d4e53927945536e902ae55994b0b4d7a49932326c55f58` each.

All eight embedded receipt/report hashes validate. The terminal report hash is
`8b479287edee59ea51e715385321c0db4627a5f44886eb92200e5a35cb71b4c4`. There is no final-image
lock, security scan, HWE archive receipt, task source, candidate, verifier result, trajectory,
qualification contract, or SFT-admission receipt.

## Narrow successor boundary

V183 authorizes no repaired qualification and no canary. After this audit is merged and a new
post-merge `main` run passes all eight classes, a separately versioned v184 identity may perform
one zero-provider, task-free missing-executable disambiguation using the exact v182 inputs and
isolation. It may rerun the final build only to classify an exact missing command against a
manifest-bound allowlist; it must persist no raw line, arbitrary token, path, command arguments, or
environment value. Unknown or multiple matches must fail closed to fixed categories.

V184 must preserve v182's time/output bound, active credential/proxy scan, terminal-report
guarantee, and inspected exact-path cleanup. It must also probe the allowlisted build commands in
the isolated builder before compilation and distinguish a missing prerequisite from a generated
binary absent after a prior build failure. Only an independent v185 audit may decide whether a
fresh dependency repair is sufficiently identified. PR-1816, its official HWE comparison, and the
DeepSeek research canary remain unauthorized. All formal and training flags remain false.

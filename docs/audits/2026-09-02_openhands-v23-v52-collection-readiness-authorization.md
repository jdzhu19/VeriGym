# OpenHands v23 / v52 zero-provider authorization

Date: 2026-09-02

Status: **implementation and zero-provider materialization authorization only**. No provider canary,
formal collection, SFT export, or training is started by this change.

## Predecessor boundary

The v51 stopped audit was merged as `2921d04586a375fd2c15ff1a944034e576ab71c4`.
Post-merge `main` run `33528870018` passed all eight required job classes. The v51 identity remains
frozen. Its stopped transfer created no source workspace, ran no verifier, called no provider, and
created no benchmark disposition for PR-2728. V52 may therefore re-run public qualification for
PR-2728 under a distinct identity; it may not resume or relabel v51.

## V23 behavior boundary

`auto_public_thought_atomic_recovery_v23` is a new protocol and does not reinterpret v17-v22.
Ordinary chat requests omit `tool_choice`, leaving the provider default `auto`. A single
content-only response may be retained in-session; only its recovery request uses `required`, and
that recovery must contain one canonical tool call. Ordinary decisions may contain concise public
rationale and one or more canonical HWE v2 calls. Every sibling is validated before the response
reaches OpenHands, and OpenHands executes accepted siblings serially in decision order.

Provider hidden thinking remains disabled. Private reasoning fields, foreign tools, non-canonical
arguments, raw host paths, or a `finish` sibling fail closed before dispatch. The SDK condenser is
disabled and its stuck detector is enabled. Before the first effective editable-file modification,
action 16 receives one fixed progress checkpoint and action 32 terminates as `no_progress`. The
action-32 gate is permanently released after the first effective modification.

Provider limits remain 64 calls, 1,000,000 total provider tokens, 65,536 context tokens, 2,048
output tokens, temperature zero, and zero provider/episode retries. The materialized contract also
freezes OpenHands SDK 1.42.1, LiteLLM 1.93.0, and tiktoken 0.7.0; the latter is required by the
broker's observation counter. Model-visible reads are bounded
to 400 lines and 128 KiB. Shell stdout and stderr are each projected as a 64 KiB head and 64 KiB
tail with omitted-byte and full-output SHA-256 accounting; complete raw output remains private and
subject to the existing 32 MiB per-command ceiling.

V23 SFT targets remain complete assistant decisions. Public rationale and every sibling call in a
successful decision are supervised together. Content-only recovery messages and failed tool
decisions remain context with loss disabled. Exact Qwen tokenization must keep every supervised row
at or below 65,536 tokens; truncation is forbidden.

## V52 authorized sequence

The hash-bound authorization is
`configs/training/qwen35_hwe_openhands_v52_v23_canary_materialization_v1.json`, with authorization
hash `20a504cb526c0eb45083ce1daf69debd78dafef8a7f6b330d8a0b40e5dc62bcc`. It binds the
official dataset and PR-2728 record, execution image, crane binary, dedicated download network,
ripgrep release, current v2 scanner profile, and all three sealed v33 PR-3204 input files. With its
explicit
opt-in, the atomic runner performs exactly:

1. PR-2728 image transfer using a fixed persistent content-addressed cache;
2. PR-2728 base-FAIL/reference-PASS public qualification with verifier network `none`;
3. the v2 Codex, credential, hidden-asset, and network scan;
4. PR-2728 command-image lock materialization;
5. exact digest/source/source-lock/command-lock/scanner revalidation of the sealed v33 PR-3204
   lock;
6. atomic publication of the v23 canary contract.

The executable entry point is
`scripts/materialize_cva6_openhands_v52_v23_canary.py`. PR-2728 has no historical agent-image
identity to reuse, so v52 creates a new `verigym_hwe_command_source_lock_v1` from the qualified
task/source/verifier binding, the prepared source image-lock digest, and an offline bounded
toolchain inventory. The command-image scanner accepts that minimal source lock while retaining
its historical `HweAgentImageLock` path unchanged for v32/v33 evidence.

Layer downloads enter task-specific staging. A layer is published by same-filesystem atomic rename
only after its digest and size validate. Persistent receipts contain only bounded digest, size, and
cache-hit facts. Raw transfer stderr is temporary; failure receipts retain only its byte count,
SHA-256, and one of `dns`, `tls`, `timeout`, `http_status`, `disk_full`, `permission`, `checksum`,
`tar_write`, or `unknown`. Each temporary archive has one cleanup owner and exactly one cleanup.

If any stage fails, the staging tree is removed and no partial canary contract is published. The
v52 identity then freezes and a successor version is required.

## Canary and collection gates

The materialized happy-path schedule is training PR-2728 followed by validation PR-3204, using
DeepSeek v4 Flash, seed 498, and sample 14. Provider hidden thinking stays disabled. The provider
canary requires a separately merged v53 authorization after the v52 result audit and another green
post-merge eight-class `main` run.

At most two infrastructure/security-valid OpenHands behavior failures are allowed. A second
OpenHands canary requires a concrete offline fake-provider or sealed-structure reproduction of a
scaffold defect plus a regression test and primary upstream evidence; it uses a fresh task, seed
499, and sample 15. Without that reproduction, or after a second valid behavior failure, the route
falls back to a separately qualified Harness v3 successor.

This authorization keeps `formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and `production_training_ready=false`.

## Pre-merge local verification

The implementation was verified without provider credentials, benchmark network access, Docker
transfer, or v52 materialization:

- `ruff check .` and `ruff format --check .`: 753 files already formatted, no lint findings;
- core `mypy src`: 209 source files passed;
- HWE Bench, Harness, and OpenHands mypy: 9, 7, and 50 source files passed respectively;
- core credential-free pytest: 1,080 passed, 1 skipped, 52 deselected;
- HWE Bench pytest: 52 passed;
- Harness pytest with the frozen tiktoken 0.7.0 environment: 14 passed;
- OpenHands pytest with the frozen SDK/LiteLLM environment: 561 passed, 66 skipped because the
  corresponding sealed local artifacts were absent;
- both v52 runner scripts passed direct Python 3.12 mypy checks and the runner's direct CLI help
  path worked with `PYTHONPATH` removed;
- the core and OpenHands package audits passed, and independently rebuilt core wheels and source
  distributions were byte-identical.

The v52 opt-in remains closed. Post-merge `main` must pass the required eight job classes before
the one authorized zero-provider materialization may run.

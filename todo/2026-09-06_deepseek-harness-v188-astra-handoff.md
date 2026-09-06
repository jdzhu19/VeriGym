# DeepSeek Harness continuation — 2026-09-06

The objective is to restore a real research trajectory using open agent tools and the official HWE
verifier. Offline build development can reuse intermediate results; a provider-started task is
consumed and must never be retried or relabeled.

## Current state

| Step | Result |
| --- | --- |
| Control-root headroom change | Merged in PR 216; `/` floor is 4 GiB and `/data2` floor remains 50 GiB. |
| Original v188 execution | Git repair passed; final Verilator compilation failed; cleanup completed; all provider/HWE/task/verifier counters remained zero. |
| Focused offline successor | Missing flex C++ header repaired; image scan and archive validation passed; archive exported; cleanup completed. |
| PR-1816 official qualification | Base FAIL, reference PASS, no infrastructure error. |
| PR-1816 open-tool qualification | Base FAIL, reference PASS, zero provider calls. |
| Research canary `503/19` | Consumed and structurally incomplete: 13 provider calls, 26,793 tokens, 14 tool operations, `finish_reason=max-tokens`, zero edits and zero finish calls. No valid teacher transcript; final candidate verification was skipped. Cleanup completed. |

The implementation and execution notes are in
[`docs/hwe_open_research.md`](../docs/hwe_open_research.md) and
[PR 218](https://github.com/jdzhu19/VeriGym/pull/218).
The single research canary has run. Do not rerun this task, delete its consumption marker, relabel
the attempt, fabricate a finish action, or admit its incomplete observations to SFT.

## Evidence and identities

[PR 216](https://github.com/jdzhu19/VeriGym/pull/216) merged as
`2adb9447e49f98edb0584a4ea678cf0e522f626e`; post-merge main run `34020540010` passed all eight job
classes. The focused v188 tests passed (25 tests), followed by the existing launcher invocation.

Original v188 terminal receipts remain unchanged at:

```text
/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v188-git-builder-repair-v1
```

Its report hash is `9b92b274955e77cb51d3ed81d0badfdd9fe9edd26dbdc4858bfd09a41b19230e`.
The old classifier reported only `no_command_context_marker`. Do not invoke the v188 identity
again or represent the successor as a successful v188 run.

The focused successor retained compiler diagnostics and object files in one isolated work session.
The actual failure was `FlexLexer.h: No such file or directory`. The repair adds the unmodified
header from flex 2.6.4 commit `ab49343b08c933e32de8de78132649f9560a3727`, SHA-256
`ee9859d6b3027ed565f98f42744e438ab31b2cd2e9f797ddf870029ca2021686`.
Build and runtime operations used `network=none`; no HWE image or provider was used during repair.
Its actual build phases, source provenance, scan, archive receipt, and cleanup are recorded under:

```text
/data2/jiadongzhu/Agent/experiments/hwe-open-tools-offline-repair-20260906-v1
```

The final image is
`sha256:70e7346e9819b6d4fa978a48ca618a1414a076412caffb607a308189a3d6dd90`.
Its 887,967,744-byte archive is:

```text
/data2/jiadongzhu/Agent/datasets/tools/open-builder/research-20260906/open-rtl-tools.tar
```

Archive SHA-256: `e69da96975b1d9ddc81facbf29c04969f803fe9144e4d01cf6a550004127f51e`.
Image lock hash: `3cac97f263cbe6d9ec2404db3c281326f503906f6c31bd77191f3ad993e4672b`.
The research runner independently cross-checks these receipts and actual cleanup before loading
HWE inputs. This is the narrow receipt/artifact review requested by the earlier handoff; no extra
audit framework or historical test sweep is needed.

## Qualification and canary

Research output:

```text
/data2/jiadongzhu/Agent/experiments/deepseek-harness-pr1816-open-research-s503-v1
```

`official-qualification/smoke-report.json` establishes official base-FAIL/reference-PASS. Its SHA-256
is `671efde28c37991e0e128b530971a930b6f4b83d3557b096f408d3998e347f4b`.
`open-comparison.json` establishes the same result on open tools, receipt hash
`8973eaa14b0871d2bc1c991e1949ee25f21fa3b8264bb6828941389af8e6017b`.
`qualification.json` binds both results to the task and images.

The single-use marker is:

```text
/data2/jiadongzhu/Agent/experiments/pr1816-open-research-s503-consumed.json
```

The runner command is `python scripts/run_hwe_pr1816_open_research.py --run-canary` for a fresh
identity. `--resume-canary` is restricted to an unchanged successful qualification, clean previous
cleanup, no episode marker, and no research run. It preserves previous stop receipts. These are
usage references, not instructions to rerun this identity after it is consumed.

The task remains `hwe-bench/repo-repair-v1/lowRISC__ibex__pr-1816`, instance
`lowRISC/ibex:pr-1816`. The frozen task manifest records source commit
`7b1be3354d650bc5b23dff6f439459c353288e4f`; the prepared archive records runtime base commit
`70186c57aeff46ff47b80e8f3d6e2c3d849f2e5b` and repository hash
`75c1418baec53fccbf9055e52880e21d4813b0f4875f0687372e24e6a62de9fa`.
The authoritative verifier is
`sha256:7ad60e4cd099379b038d99def95f3a310d2f636116d8790f778b1f93ee2f20f7`.
The agent sees only the repaired open tools. Task/verifier execution is networkless inside the
isolated Docker endpoint. The trusted Harness controller uses the canonical host Docker socket
and its existing provider network. Credentials remain confined to that controller path.

All trajectories remain research-only. Formal collection, SFT admission, training, and production
readiness are outside this continuation. VCS remains safety-prework only; do not run untrusted HWE
RTL through host `LocalRuntime`.

## Actual canary outcome and remaining work

The consumed run used source commit `65d6e0e` and the native Harness v4 adapter. Its
`research-canary.json` and `artifacts/deepseek_harness/collection_evidence.json` record:

- 13 provider calls: 20,440 input tokens + 6,353 output tokens = 26,793 total;
- 14 tool operations: 8 reads, 5 shell commands, and 1 other inspection; zero mutations;
- the provider returned `max-tokens` under the pinned 2,048-token per-response cap;
- one permitted format-recovery interval within the same episode, zero whole-episode retries;
- no explicit `finish`, failure category `incomplete_harness_trajectory`, no valid teacher
  transcript, and final candidate verification skipped because the candidate was quarantined;
- passed artifact security scan, no formal collection/SFT/training, and complete physical cleanup.

`result.json` says `research_canary_completed` because the invocation finished; it does **not**
mean the model completed the repair. Both `resolved` and `transcript_valid` are false. The two
qualification routes succeeded, but a complete training trajectory has not been recovered.

The next work is the Harness completion/output-budget behavior, not another image build or
qualification replay. Use offline fixtures to examine truncated typed-tool output and the
2,048-token response cap. Any later real experiment needs a different, unconsumed task with its
own frozen identity and budget; it must not reuse or relabel PR-1816 `503/19`.

Three earlier stops preceded the consumption boundary and are preserved under
`pre-canary-stops/1`, `/2`, and `/3`: socket canonicalization, complete ripgrep version matching,
and the required nonempty initialization system prompt. Their fixes were tested before the one
provider-started episode. Successful qualification was reused unchanged.

## Existing local assets and unrelated work

The complete public HWE image collection remains under
`/data2/jiadongzhu/Agent/hwe-bench-public-images`: 177 tar archives, 177 SHA-256 sidecars, and no
incomplete downloads in the prior inventory. The completed-download `crane-layer-cache` was
removed earlier, reclaiming about 57.1 GiB. Reuse these archives; do not download them again.
The pre-existing suspended downloader was neither stopped nor resumed.

PR-1816 archive: `docker-tar-archives/lowrisc_m_ibex/pr-1816.tar`, SHA-256
`91395d522a65b0ae35f9c4504d74aa5a460242ab6629bcdfb1155c6cbc6821ed`.
The v188 git package closure remains available locally with SHA-256
`315102c5bf97a839d7f4fcedfed79fd788ac20796e4f7008e84928c2b7541773`.

Preserve these seven unrelated user-owned untracked paths; do not stage or edit them:

```text
configs/training/qwen35_hwe_openhands_v56_direct_oci_provisioning_v1.json
integrations/verigym-openhands/src/verigym_openhands/hwe_v56_direct_oci_provisioning.py
scripts/download_hwe_bench_public_images.txt
src/verigym/hwe/oci_resumable.py
src/verigym/hwe/public_ghcr.py
tests/unit/test_hwe_oci_resumable.py
tests/unit/test_hwe_public_ghcr.py
```

The root `AGENTS.md` is deliberately ignored by the repository and remains a local working guide.

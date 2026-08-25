# CVA6 Codex HWE container-native v2 campaign

Date: 2026-08-21

## Frozen identity

- campaign: `cva6-codex-hwe-native-shell-v2`
- model/reasoning: GPT-5.4, `xhigh`
- seed/sample policy: 484, one sample per task
- collection/observation/tool: `hwe_standard_v2`,
  `hwe_repository_observation_v2`, `hwe_native_shell_v2`
- prompt: `codex_cli_hwe_native_shell_context_v3` version 3.0.0
- client: Codex CLI 0.147.0
- tokenizer: `tiktoken==0.7.0`, `o200k_base`

Eleven distinct task-keyed agent images were derived offline from the local immutable verifier
images. Every final image has a distinct immutable ID and v2 lock. The image-level configuration
contains only the five Docker baseline environment entries; the trusted runtime supplies
`CODEX_HOME` when it creates the container. All images passed non-root, network-none,
read-only-rootfs, cap-drop, no-new-privileges, private PID/IPC, bounded-resource, single-workspace
mount, source-whiteout, asset-absence, hash, `rg`, `make`, Verilator, parent-read, and absolute-read
checks. The lock/receipt/security-scan bundle passed the context-aware secret scan with zero hard
leaks and zero scanner errors.

## Actual collection result

An initial zero-model-call preflight failed during image resolution because the first image config
incorrectly declared runtime-owned `CODEX_HOME`. That failed campaign is retained separately as
`campaign-preflight-failed-image-environment`; its report hash is
`61ca28e24eb42c21dc438000ee01eda8b2b6692d134d7104dba51864a4637329`.
The rootfs layers were not rebuilt or changed during the config-only repair, and all repaired
images were rescanned and relocked.

The restarted real campaign reached one external GPT-5.4 call on PR 2032 (2,880 input and 187
output tokens). The exec-server then issued a non-workspace direct filesystem metadata probe that
the broker rejected as `hwe_protocol_filesystem_path_outside_workspace`. The attempt is therefore
infrastructure-invalid, not a verifier rejection. Its run hash is
`1611bda1c314fb138f397b76220bc4609ddcaceef1bdb95127545a4a472b7f77`, and the campaign report hash
is `fdd448f566cc158c3e0f94da48f4e656936778df6bb4f8a97d6448bc9c97032b`.

Because the model-call count is one, the one-sample rule forbids an automatic PR 2032 retry. The
campaign stopped with zero verifier passes, zero normalized successes, and zero primary-eligible
examples. This is not a benchmark score, and no HPC/GPU job or training handoff was submitted.

## Follow-up implementation state

The v2 broker maps non-workspace direct read-only filesystem discovery to a fixed nonexistent
workspace path. This exposes no container metadata or file contents and does not widen patch or
persistent-write boundaries. Container-native reads remain available through `shell`, including
`find ..` and absolute paths. Regression tests verify both sides of that boundary, and legacy v1
keeps its original fail-closed behavior.

The stopped campaign and its mode-0400 private audit artifacts remain immutable evidence. This
compatibility fix was validated but was not used to post-process or rerun the consumed PR 2032
sample.

## Final validation

- `ruff check .` and `ruff format --check .` passed.
- Core mypy passed for 191 source files; Codex, HWE-bench, and training-reference mypy passed for
  22, 9, and 28 source files respectively.
- Core pytest passed 912 tests, with one real-Codex opt-in test skipped and 52 opt-in tests
  deselected. Codex passed 5 tests, HWE-bench passed 34 tests, and training-reference passed 91
  tests with one optional-rLLM test skipped.
- Fresh wheel and sdist builds passed the core, Codex, HWE-bench, and training-reference
  distribution audits.
- A context-aware scan of the 31 public campaign artifacts (11,675,675 bytes), excluding the
  candidate source tree and `private-audit/`, passed with zero hard secret leaks and zero scanner
  errors. No public transcript, dataset, or binding was produced. The raw event stream remains a
  mode-0400 file of 7,887 bytes under `private-audit/`.

## Metadata-fix campaign

The separately frozen `cva6-codex-hwe-native-shell-v2-metadatafix1` campaign was authorized and
started from PR 2032. It made one GPT-5.4 call (2,880 input and 268 output tokens) and then stopped
with the same `hwe_protocol_filesystem_path_outside_workspace` infrastructure classification. The
run hash is `61beb4d9025dbf8085b93d35c7d82bd8aae7dfb2a5bb0f4aa330771fca3c8017`; the campaign report
hash is `dd0c4afec76db3c235d390d9130caa0d6d3fe6ba9232cc9f4fafe116dd10a37c`.

The private protocol sequence proved that all preceding metadata requests completed and that the
rejected request failed before registration. The v2 broker therefore applies the fixed absent-file
mapping to `readFile`, `readDirectory`, `walk`, `open`, `getMetadata`, and `canonicalize`. Such
probes expose no data and are not training actions. Direct mutations still fail closed, and a safe
request-method classification is retained for future fail-closed diagnostics. This second
consumed sample was not rerun or post-processed.

After this repair, the full core suite passed 912 tests (one real-Codex test skipped and 52 opt-in
tests deselected), and ruff, format, and core mypy passed. A separate context-aware scan of the 31
public metadata-fix campaign artifacts (11,676,117 bytes) passed with zero hard secret leaks and
zero scanner errors. Its private raw stream remains mode 0400 and is absent from the public scan.

## Superseding campaign status

Subsequent campaigns remain immutable under separate directories and campaign IDs. They exposed
and then closed protocol gaps involving heredocs, streamed-process event ordering, successful
terminal turns without a provider final message, causal patch rejection, shell-local status and
loop variables, frozen toolchain environment reads, and shell assignment-position parsing. None
of the failed attempts was rewritten, resumed under a different identity, or relabeled as a
verifier outcome.

The final infrastructure repair in this series permitted the non-secret, fixed-workspace `PWD`
read while retaining fail-closed handling for `HOME`, `OLDPWD`, credential variables, and
environment injection. The targeted regression, 241-test HWE/Codex suite, and five-test Codex
integration suite passed before the new campaign started.

### `pwdfix1` pilot

The separately frozen campaign
`cva6-codex-hwe-native-shell-v2-pwdfix1` completed all three pilot samples with exactly one
GPT-5.4 `xhigh` model call per task. Its report hash is
`311a5e40c9a23a36cd0cd772497d0eb6fd4465d7e7025f8974d1cd23651b3328`.

| Task | Infrastructure | Verifier | Normalization | SFT tokens | Bucket |
| --- | --- | --- | --- | ---: | --- |
| PR 2032 | valid | passed | successful | 64,950 | long-context candidate |
| PR 2549 | valid | rejected | not eligible | n/a | verifier rejected |
| PR 2944 | valid | passed | successful | 57,055 | long-context candidate |

PR 2032 used 73 decision steps and six compile-classified steps. PR 2944 used 65 decision steps,
nine compile-classified steps, and first mutated the workspace at normalized sequence 21. PR 2549
was recorded as a benchmark verifier rejection rather than an infrastructure or materialization
failure.

The pilot therefore met the three-infrastructure-valid and two-verifier-pass gates, but produced
zero examples at or below 32K. It stopped with
`pilot_requires_three_infrastructure_valid_two_verifier_pass_one_primary`; production sampling
did not start, and no HPC/GPU job or training handoff was submitted. This pilot is not reported as
a benchmark score.

### Length attribution

An earlier verifier-passed PR 2032 trajectory contained 83,283 SFT tokens across 92 decision
steps. Tool observations accounted for about 69.3K tokens, including about 67.1K from shell
observations. The largest single observation was 4,350 tokens; none exceeded 8K. Only two command
instances and one observation were exact duplicates, so the excess was not caused by a runaway
single output or repeat-folding failure.

Two bounded inefficiencies were identified. Repeated result headers accounted for about 10.4K
tokens, of which command duplication contributed about 2.9K. Ten read-only search pipelines that
were conservatively classified as generic shell output would save about 7.1K tokens under a
simulated search top-20 projection. Applying both estimates still leaves that trajectory near
70K. The successful `pwdfix1` trajectories likewise remain around 49K after estimated header and
pipeline savings. Observation compaction can be improved in a new version, but it cannot honestly
turn these records into 32K primary examples.

The collection is therefore stopped at a normative gate rather than an unresolved infrastructure
fault. Continuing with 32K--64K verifier-passed rollouts as acceptance units would require an
explicitly versioned rollout/training-length policy; existing campaigns and their primary counts
must remain unchanged.

### Action-conditioned masking analysis

The versioned `hwe_action_preserving_observation_masking_v1` derivation was run read-only over the
two verifier-passed `pwdfix1` transcripts with exact `tiktoken==0.7.0/o200k_base` counting. It
preserves every assistant action and compares recent-observation windows 8, 10, and 16 while
pinning at most four current-epoch mutation/diff/compile/simulation/failure observations.

| Window | Maximum input tokens | Maximum input + target tokens | Both trajectories <=32K |
| ---: | ---: | ---: | --- |
| 8 | 26,217 | 26,778 | yes |
| 10 | 26,377 | 26,796 | yes |
| 16 | 29,920 | 29,968 | yes |

The deterministic selection rule chooses the largest safe tested window, so the experimental
default is `M=16`. At that window PR 2032 has a 29,968-token maximum action record and PR 2944 has
a 25,930-token maximum. The sealed report is
`campaign-pwdfix1/hwe-observation-masking-analysis-v1.json`; its analysis hash is
`1fc86a9ee1fd52f6d021c037f2082f363f6660b2e3d9f7babce4dfcd579f02e1`.

This result does not modify either source transcript, does not change either long-context bucket,
does not count as a benchmark score, and does not establish counterfactual next-action equality.
The new action-conditioned format is explicitly experimental and primary-ineligible. The current
Codex app-server path also cannot inject retroactive masking into the already-owned live provider
history, so the report records `live_rollout_masking_applied=false` and
`counterfactual_next_action_validation=not_run`. No dataset handoff, HPC job, or GPU job was
created. A standalone context-aware scan of the 7,236-byte analysis report found zero hard secret
leaks and zero scanner errors; its scan-report hash was
`ebf19266ecd875e08b556ede78a06fe7af30155fe5fb7ec1aa200a8ccefca2ad`.

### Validation after `pwdfix1`

- Core ruff and format checks passed for 489 files; core mypy passed for 191 source files.
- Core pytest passed 917 tests, with one real-Codex opt-in test skipped and 52 opt-in tests
  deselected. The focused HWE/Codex suite passed 241 tests with the same real-Codex skip and 11
  deselections.
- Codex, HWE-bench, and training-reference mypy passed for 22, 9, and 28 source files. Their test
  suites passed 5, 34, and 91 tests respectively; training-reference skipped one optional rLLM
  test.
- The Codex wheel and sdist rebuilt successfully and both contain the package's `py.typed` marker.
- The context-aware public artifact scan covered 79 files and 25,229,458 bytes, excluding
  `private-audit/` and candidate repository copies. It passed with zero hard secret leaks and zero
  scanner errors; its report hash is
  `07efe545e5672d008ba905ddab18b0aef036d7c5a33cb3c9fb11afc541d293a7`.
- The three raw event streams are retained only under `private-audit/`, sealed mode 0400, and have
  sizes 1,015,181 bytes (PR 2032), 950,488 bytes (PR 2549), and 687,141 bytes (PR 2944).

## Completed M1/P1 action-conditioned campaign

The separately frozen campaign
`cva6-codex-hwe-action-conditioned-v1-m1p1-v9-lifecycle2-1` completed on 2026-08-21 with prompt
`codex_cli_hwe_native_shell_context_v9` 9.0.0, exec lifecycle
`hwe_exec_process_lifecycle_v2`, and history policy parameters `M=1`, `P=1`. Its report format is
`verigym_hwe_cva6_codex_action_conditioned_campaign_report_v3`; the sealed report hash is
`643cabc4f984cb1c515f6005834ef6ec1b3382b5c9e9ca4f27b542e8d7379b71`.

The pilot tasks PR 2032, PR 2549, and PR 2944 passed the gate 3/3. Production then accepted PR
2248, PR 2282, PR 2468, PR 2469, and PR 2589. All eight attempts used one external GPT-5.4 call,
passed the benchmark verifier, normalized successfully, and remained infrastructure-valid. There
were no policy rejections, retries, best-of-K choices, or model substitutions. Aggregate API
accounting was 327,852 input tokens, 6,252 output tokens, and 334,104 total tokens. The pilot is
not a benchmark score.

The unmodified source transcript buckets are two primary (PR 2248 and PR 2468), five
long-context candidates, and one audit transcript (PR 2032). The M1/P1 derivation exported 419
action-conditioned records from all eight trajectories; the maximum record is 26,486 tokens, so
every record fits the 32,768-token hard limit without truncation. The dataset hash is
`3a0905c578ca70b9af0ac5a17d0bf100d21e4357445882321616bf26f55fe841`, and the bindings hash is
`0303fac03456edb9daf25a2379a7c98024f1563cbac478aba38d80128aaf6e5d`.
These records remain explicitly `experimental_action_conditioned`, `primary_eligible=false`, and
`counterfactual_next_action_validation=not_run`.

The eight raw event streams total 4,642,868 bytes. Each is retained only in its run's
`private-audit/raw-events.ndjson`, sealed mode 0400, and excluded from reports, bindings, and the
dataset. The generated handoff hash is
`666556ed466d2417b28f5a5e69c703695e4e92fc269d76bf98484dde692525a5`; it requires a separate
quality gate and records `training_config_enabled=false` and `hpc_jobs_submitted=false`. No HPC or
GPU training job was launched.

### Final validation for the completed campaign

- `ruff check .` passed; `ruff format --check .` reported 492 files already formatted; core mypy
  passed for 193 source files.
- Core pytest passed 925 tests, with one real-Codex opt-in test skipped and 52 opt-in tests
  deselected. Codex passed 5 tests, HWE-bench passed 34 tests, and training-reference passed 92
  tests with one optional-rLLM test skipped. Their mypy checks passed for 22, 9, and 28 source
  files respectively.
- All 419 action-conditioned records passed Pydantic and JSON Schema validation. Record, ledger,
  per-trajectory manifest, dataset, bindings, report, and handoff hashes were recomputed; exact
  `o200k_base` token counts were recomputed from every message list. The concatenated dataset is
  byte-identical to the eight sealed per-trajectory JSONL files.
- The context-aware export scan covered 22 files and 29,288,602 bytes; the public Codex runtime
  scan covered 120 files and 22,577,520 bytes; the private-raw scan covered 8 files and 4,642,868
  bytes. All three passed with zero hard secret leaks and zero scanner errors. Their report hashes
  are `57ae0c21d30a275c7ea161864af3fb37e4918f1fc645190b31965ee14223d6a9`,
  `a8aefbae107b86377c4774b811e81c107ed7eaf7546ae6948573b5ef1f998798`, and
  `5628c29dc3c74b865d23eb7c7c42161e9c6c8d490550fb91046a8a31d608bdb8`.
- Fresh core, Codex, HWE-bench, and training-reference wheels and sdists were built with the
  already-installed, requirement-compatible backend after the configured package-index proxy
  returned HTTP 502 to isolated build-environment bootstrap. All four repository distribution
  audits passed with zero issues.
- The opt-in real Docker image test passed against the immutable PR 2032 agent image. It verified
  non-root execution, `network=none`, read-only rootfs, cap-drop, no-new-privileges, one visible
  workspace mount, source whiteout and hidden/reference/verifier absence, plus functional
  `find ..`, `rg`, `make`, and Verilator diagnostics.

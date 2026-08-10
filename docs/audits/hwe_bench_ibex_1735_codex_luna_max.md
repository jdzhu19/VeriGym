# HWE-Bench Ibex PR 1735 Codex smoke

- Date: 2026-08-10
- Scope: one official task, one sample, no retry or best-of-K selection
- Agent: Codex CLI 0.146.0, observed `gpt-5.6-luna`, reasoning effort `max`
- Task: `lowRISC/ibex:pr-1735`
- Runtime: credential-free Docker agent with `network=none`; separate suite verifier
- Policy: `docker_runtime_isolated_workspace_policy_v3`

The model process completed normally and changed only
`repository/rtl/ibex_cs_registers.sv` (+41/-3). Candidate freeze and both event/workspace policy
checks passed. The suite-managed `hwe_bench.simulate` verifier then ran for about 27 seconds and
reported `test_failed` with no infrastructure error. The resulting outcome is therefore an
eligible negative trajectory, `incorrect_policy_compliant_candidate`, rather than a platform
failure or a solved benchmark task. The run used 187,860 input and 3,088 output tokens.

An earlier single sample under policy v2 is retained separately as invalid evidence: repository-
local `git status` was rejected before verification. It is not pooled with this result. That
compatibility finding led to commit `a630553`, which permits repository-local shell, Python, and
Git inspection only inside the sealed Docker boundary while retaining network and protected-path
checks.

## Observable trajectory

The sealed export contains one eligible record and 121 bounded events, including command and
patch event categories plus the `hwe_bench.simulate` verifier result. Validation and source replay
made zero model, runtime, verifier, network, or public-launcher calls.

- Dataset hash: `5f30eeb1cd1cb3099be3d5476ed0ba0361ef0806ebbbb3947c5c253a7f9a4f1e`
- Agent-version hash: `bb02e18b5c9b7393b98a1f4c3b55eca199f655a93096f2b95548634b46385b0c`
- Split-manifest hash: `70a1dc31707d5801cc018e9d208ba6415a90a86a1a02ddd4b1eb1bbce6dfddf9`
- `dataset-manifest.json`: `d6fb9210158a42fe5fba09bdb8afa19b678432fa6e04f3584829ac9c3faeb4c1`
- `SHA256SUMS`: `cbe761c3b0727d1f701d76cf5405b52982da75243a025a2f8b279e2a7ff0e1f6`

The exported dataset passed the context-aware security gate with zero hard leaks and zero scanner
errors; known hidden-test fragments were absent. The raw run tree is intentionally not a
publishable dataset: a full-tree diagnostic found two lexical secret-assignment matches in
vendored upstream source and one local `suite_source.source_root` value. No recoverable suspected
value was emitted, and none of these fields is present in the sealed export.

## Run evidence hashes

- `sampling-plan.json`: `92719f4a3f8de012d28bf26aa7d34958b512dd3449f254d93b54253fae8570e3`
- `sampling-summary.json`: `4e4622d800b0ceca1c1c4b68447f89aa48227e7c72b93ce72212347acb5e13c0`
- `run_manifest.json`: `189c774ea578001cf3baf64807bc61e6ce077df02b58f6c3a0de872ea70f3557`
- `scorecard.json`: `cb8276fb1e05dd291c35a2e6bda4aabebd1905216fd18cd6b028671b8c997d34`
- `trace.jsonl`: `52dc5a6a33b34fff892991e9b3510a0c46a79fa42871885f2100de9a78532812`

This smoke validates the real repo-level execution and trajectory path only. It is not a full
HWE-Bench campaign or a model-quality claim.

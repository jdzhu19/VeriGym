# OpenHands HWE PR-2944 trajectory qualification

Date: 2026-08-25

This qualification ran one real OpenHands SDK agent loop against the frozen CVA6 PR-2944
training task, submitted the resulting candidate to the ordinary network-disabled Docker
verifier, exported the verifier-passed model-visible trajectory, and materialized exact Qwen
decision-only SFT rows. It is a bounded integration qualification, not a benchmark score or a
claim about dataset scale.

## Frozen execution identity

- VeriGym source commit: `3e0cc0a22f7005ba8b4573b80b08b1f46971ed3f`
- branch: `agent/openhands-trajectory-collector-v1`
- task: `hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2944`
- model transport: `openai/deepseek-v4-flash`
- model identity: `deepseek-v4-flash`
- OpenHands SDK / LiteLLM: `1.42.1` / `1.93.0`
- seed / context / maximum output: `484` / `65,536` / `2,048`
- sampling: temperature `0`, top-p `1`, no whole-episode retry
- tool contract: `hwe_native_shell_v2`, exactly six MCP tools
- agent image: `sha256:d20ffcf6ba42570d225ec9fe0757f501f654c222250c83e3fd83ab70918834e3`
- verifier image: `sha256:91a135852c3ab371c24e2f49fad382568ffb830167d3c26006c26f88fe190b6a`
- verifier repository digest:
  `ghcr.io/pku-liang/openhwgroup_m_cva6@sha256:920a2e91246e88b109f90c1a86d0a065af2ae8db8b8fe39f9da3b2e9144e7e80`
- verifier runtime network: `none`

Provider thinking was disabled. The exported trajectory contains public model-visible text and
typed tool semantics, but no private reasoning, raw provider events, hidden assets, reference
patches, credentials, or raw host paths.

## Result

The ordinary verifier resolved the candidate with one of one verifier tests passing and no
infrastructure error. The candidate changed only
`repository/core/issue_read_operands.sv`, with one added and one deleted line and no changes
outside the expected files.

OpenHands completed 21 decision steps, 22 broker tool calls, three patch calls, and a typed
`finish`. The normalized trajectory contains 20 supervised assistant decisions and 22 canonical
tool actions; two decisions contain sibling tool calls. The trajectory is verifier-gated and SFT
eligible.

- transcript hash: `7ed148bf5e206d214d7abfdd5612275283e1e2e0643c8b8df3d5dcd5107c7416`
- trajectory file SHA-256:
  `ccc8bbf307b5cd674a39161475f428201c9bbc77ac85f5e78e948ccc25d56771`
- collection report hash:
  `7f6e06b379b57683826588cfde57e0bda0188b5233710529ddf05bc852eaa773`
- qualification report hash:
  `1a9c537ed9217c12245d3a96ac413d94dfda6fa64c8f68e772173c2d34e64435`

The end-to-end collection wall time was 308.26 seconds. The OpenHands process used 246.15
seconds and the verifier used 40.46 seconds.

## Exact SFT materialization

All 20 rows were rendered with the exact six tool schemas and the complete assistant decision as
the target. Input tokens are masked from loss; all target tokens, including public assistant text
and every sibling tool call, are supervised. Truncation is an error.

The persisted rows were independently re-tokenized with the official Transformers checkout
`e8ea728a3eeeb903e77c7d1bd29267c80a1be71f` and the frozen local Qwen3.5 tokenizer. Every token-ID
hash and loss-mask hash matched.

- dataset hash: `e1331ed287cedc76141d9f882992c4a159b76c759371170d259aa6d15492f511`
- rows / canonical actions / sibling decisions: `20` / `22` / `2`
- maximum observed length: `13,107` tokens
- records over 32,768 / 65,536 tokens: `0` / `0`
- truncation applied: `false`
- exact loader dry-run receipt hash:
  `4ab90a7062ba888f791c5aeb29289fd6d259ddfdb8888393920ae9c4014b2ddf`

The full dataset remains under the designated local datasets root and is not committed. Only
sanitized receipts were mirrored into the HPC experiments root. The remote sync receipt hash is
`53b0286b4674afe892387e99ce2d8b803cb50207823259318fc95fa176c9077b`.

## Safety and readiness boundary

An exact-value credential scan covered 7,222 files and 146,678,517 bytes across the experiment
and dataset outputs. Both configured provider values had zero matches. Credential values were not
persisted or hashed.

Existing LSF job `466876` was re-observed as `RUN`; this qualification did not use its GPUs,
submit a new HPC job, or release the allocation. GPU time and peak GPU memory for this run were
both zero.

The result establishes that the real OpenHands collection, inference, verifier gate, trajectory
normalization, sibling-call handling, and exact local dataset loader are working. It does not yet
make this new OpenHands dataset format development-training-ready: the format still needs explicit
registration in the rLLM/veRL dispatcher and the single trajectory is not sufficient training
scale. Accordingly, `production_training_ready=false`, `training_started=false`,
`optimizer_steps=0`, `checkpoint_written=false`, and `adapter_written=false`.

## Checks

- OpenHands integration pytest: 20 passed
- OpenHands integration Ruff and format checks: passed
- OpenHands integration strict mypy: passed
- dataset SHA256SUMS: passed
- frozen-Transformers exact re-tokenization: passed
- sanitized HPC mirror hash verification: passed

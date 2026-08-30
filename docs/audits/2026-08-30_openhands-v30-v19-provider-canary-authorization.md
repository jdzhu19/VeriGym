# OpenHands v30 authorization for the v19 provider canary

## Authorization boundary

This change authorizes one execution of the already materialized v19 canary, and only after this
authorization pull request is merged and all repository protection checks pass. The orchestration
identity is `openhands-hwe-v30-v19-provider-canary-v1`; the campaign, agent, protocol, qualification
and static canary identities remain unchanged:

- campaign `openhands-hwe-v19-required-tool-canary-v1`
- agent `openhands-deepseek-v4-flash-hwe-v19-canary-v1`
- PR-2330 training followed by PR-3204 validation
- seed 489 and sample index 5
- DeepSeek v4 Flash, OpenHands SDK 1.42.1, LiteLLM 1.93.0, tiktoken 0.7.0
- temperature zero, 64 provider calls per episode, 1,000,000 cumulative provider tokens,
  65,536 context tokens, 2,048 output tokens, and zero retries

The authorization hash is
`3619b56bbaf3dc5577c8511865e6f0a681f9d03a53b80b261d77e359f01994d8`. It permits at most two
provider-bearing episodes. It does not authorize formal collection, another reserve, a fallback
identity, held-out loading, SFT, GPU work, or adapter publication.

## Exact predecessor evidence

The runner accepts only the v29 result-audit merge
`33b30172999ef5b7e99e0df26d709deaf6bcd117` and the following local evidence chain:

- materialization progress: canonical hash
  `42f85402c9e509a687ec32c953b24a026f978b5bf0684eb877f32876d0d302f0`, file SHA-256
  `f2992d89c13de3ce4a55cb15f4c4985be8c7dd2c0402ea1b675bb793f55b00f2`
- v19 qualification receipt: canonical hash
  `3eea3a1b0fc2bb3d2027c4c9c97549012ce32c484b3b7d07bdb15fc5260e59cb`, file SHA-256
  `c56201069b55e1eb1bf5d7532dbfe891d54aa562c2ee980a83e3340f3b05d9e8`
- source catalog: canonical hash
  `7d708bb0c7ac86e0562899e42abce671cde0c9c5b1d96fa21420cfed1fed400f`, file SHA-256
  `09abccc6d25f20abd9866d9bd8a7004727566a10bf3aa87af02077637931836a`
- v19 canary contract: canonical hash
  `cf6ba5b011f35ec958eaef319ee79ee4f8cd2fcbab77f0dae62f6dbd2c202efc`, file SHA-256
  `c65e4f10d243c0efb3e56fb2217c4c65f350cd58cd51aa0f69b13b3f12854a8a`

The PR-2330 and PR-3204 image-lock files, source `image-lock.json` files, Qwen3.5-9B model lock,
model snapshot and exact tokenizer are separately file/hash bound. The runner requires a clean
tracked checkout whose `HEAD` equals `origin/main`, local digest-addressed images, explicit opt-in,
and the exact frozen package versions. It performs a zero-provider Docker preflight with
`network=none` before creating any episode.

## Efficiency and fail-closed behavior

The previous canary runners could finish the full schedule before applying an ordinary-result gate.
This runner recomputes the six result planes after each task. If PR-2330 fails benchmark,
required-tool protocol, exact trajectory, security, SFT admission, or exact-64K materialization,
the runner seals the failure immediately and does not spend the PR-3204 episode. Infrastructure or
security invalidity also stops immediately. A passed first task is the only path to the second task;
both tasks must pass all six planes before formal collection can be authorized.

Provider accounting is recovered from each run's persisted accounting file even if a protocol
violation prevents a protocol receipt. This prevents an interrupted or over-budget provider
response from being reported as zero calls. Full messages, exact tool schemas and model-visible
recovery context remain in the trajectory; abnormal assistant prose and environment recovery
feedback are input-only, while canonical tool decisions are supervised. Decision materialization
rejects any row over 65,536 tokens and never truncates.

## Integration defect fixed before authorization

The v19 protocol and settings parser already froze `max_provider_tokens=1_000_000`, but the generic
plugin-options sanitizer classified the word `token` in that public integer budget field as a
credential-bearing key. The real agent options therefore could not cross the execution boundary.
This change adds only `max_provider_tokens` to the existing narrow list of public token-count
fields. Actual `token`, `access_token`, and `refresh_token` values remain rejected. A core regression
and the v30 agent-options test cover the distinction.

## Security and reporting

Each successful episode requires an independently valid v19 protocol receipt, actual verifier
results, a verifier-gated exact trajectory, exact decision records, and a passing artifact scan.
The report records the independent benchmark, protocol, trajectory, infrastructure, security and
SFT-admission planes. Provider endpoint and credential values are checked in memory for accidental
persistence and are never printed, persisted or hashed. Verification and both agent runtimes use
`network=none`; held-out assets are never loaded.

The run output must be a new directory under `/data/jzhu484/Agent/experiments/`. A passing canary
still does not itself start formal collection. Its sanitized result and hashes require a separate
audit pull request and the same repository protection checks. `production_training_ready=false`
and `benchmark_score_claimed=false` remain fixed.

## Pre-review verification

Credential-free checks performed so far:

- v30 and plugin-options regressions: `11 passed`; combined v19/v30 regressions after the final
  sealing fix: `33 passed`
- complete OpenHands Python 3.12 zero-model suite: `306 passed`
- ordinary credential-free repository suite: `1035 passed`, `10 skipped`, `43 deselected`
- HWE credential-free suite: `50 passed`
- strict mypy: core `206` files, HWE `9` files, OpenHands `29` files, v30 runner `1` file
- tracked-source Ruff and format: `672` Python files; Git diff hygiene: passed
- persistent-schema drift: none; documentation/schema contracts: `2 passed`
- core, OpenHands and HWE wheel/sdist package-content audits: passed
- core wheel and sdist reproducibility: both byte-identical
- read-only materialized-evidence check: all four v29 hashes and both task image locks validated;
  the v19 agent version constructed successfully
- an isolated Python 3.12 runtime overlay was assembled without network access from the existing
  locked wheelhouse and verified OpenHands 1.42.1, LiteLLM 1.93.0, tiktoken 0.7.0,
  transformers 4.57.6, tokenizers 0.22.2 and NumPy 2.2.6
- premature execution on the unmerged dirty branch stopped at the merged-source gate before output
  creation, Docker preparation or provider accounting; provider calls remained zero
- provider calls, verifier runs, canary episodes, collection, training and held-out loads: zero

The repository's eight GitHub protection classes remain the authoritative merge gate. The canary
must not execute until both push and pull-request checks pass and this authorization is merged.

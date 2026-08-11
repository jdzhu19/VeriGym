# HWE repo-level DeepSeek held-out v1 campaign

- Date: 2026-08-11
- Status: three samples completed; three ordinary rejections; not a benchmark score
- Code commit: `0668a4d0ba806eb3d75090ff8c8cdf5881c47479`
- Agent: `deepseek-api-hwe-heldout-v1`, `deepseek-v4-flash`, thinking disabled
- Split: `hwe-repo-heldout-deepseek-v1`
- Sampling: one sample per task, base seed 3, no retry, no best-of-K

## Independent freeze and request policy

This line is independent of the Luna campaign. Its agent-version hash is
`e1a3fbc12e695ec5f5bd7883e735feecd40e17ca2c1faf69dacd086bd869095c`, its split
manifest hash is `fcc8d12c0387c3c6a27ccc4e6fdb632a99943390aea69ad84f912764bc7fbfc1`, and its
content-free repository freeze hash is
`9ccd005e4f7eda3f086943d357cc6d91e06470fcbae61342cfe9c20229d6d65e`. The freeze
contains exactly Ibex PR222, CVA6 PR2945, and Rocket Chip PR3065, with empty training and
validation splits.

The frozen API request policy hash is
`d59f95d9cb255ed3216b8272df26291ebe4f38d3bc070872c6ef3962ef436fc9`. It binds the
OpenAI-compatible transport, the exact returned model, disabled thinking, a 4,096-token output
cap, 10-second connect and 120-second read/request timeouts, a 1 MiB response bound, and zero
retry or best-of-K behavior. Authentication and endpoint configuration came from the named
`VERIGYM_DEEPSEEK_API_KEY` and `VERIGYM_DEEPSEEK_API_BASE_URL` environment variables. Their
values were never included in the freeze, prompt, run artifacts, or audit.

The campaign plan hash is
`c1c45dbaac9b405e1d45b1b3dc986a9acbd1e7ed50c14eaf34ca4fa8d9bd2dbb`. All three
provider calls returned the requested `deepseek-v4-flash` identity; none was classified as an
infrastructure failure.

## Outcomes

| Task | Provider finish | Usage (input/output) | Agent outcome | Resolved |
| --- | --- | ---: | --- | --- |
| Ibex PR222 | `length`, 18.05 s | 1,487 / 4,096 | output ended before a valid action | no |
| CVA6 PR2945 | `length`, 19.26 s | 8,392 / 4,096 | output ended before a valid action | no |
| Rocket PR3065 | `stop`, 5.32 s | 10,133 / 560 | patch path violated the editable-root policy | no |

Ibex and CVA6 produced no patch. Rocket returned a parseable patch action, but its path omitted
the required repository-root prefix, so the workspace rejected it without applying any change.
The official digest-locked verifier then ran against each unchanged base candidate and returned
an ordinary failure. These are model/protocol rejections, not infrastructure-invalid samples.

The campaign completed exactly three samples with zero resolved, three rejected, and zero
infrastructure-invalid results. It did not stop early. The sampling summary hash is
`2806dfa2cdf946ab32bf3965944c82397ce5063b5e953bb0a998a67ac79edc98`.
The 4,096-token cap is visibly too small for the first two responses; evaluating a larger cap
would require a new agent version and a separately identified campaign, not a retry of this one.

## Offline replay, training exclusion, and safety

Visible replay passed for all three runs. Observable trajectory export, validation, and source
replay completed with zero additional model, network, runtime, verifier, or public-launcher calls.
The dataset hash is `95107ffb3ba2dfa21cfa16854caafd8ce03e3a503d6d88242ec4a20a5f9dd325`.
Its three records are structurally eligible observable trajectories because none is
infrastructure-invalid, but every record remains assigned to the frozen `heldout` split.

The external training-reference preparation therefore rejected the dataset with
`no_eligible_training_trajectories`, exit code 2, and created no training bundle. The exclusion
report hash is `ba23ac512d9f15c062cec67860ee33271f48497f6e09ae68efa7c39676f79fd3`.

The final context-aware scan covered the exported campaign metadata, patches, traces, frozen
identities, trajectory dataset, and post-processing reports: 84 files and 16,158,448 bytes. Raw
benchmark repository inputs were not treated as exported artifacts. The scan passed with zero
hard secret leaks and zero scanner errors under report hash
`758c9664fead852377f9c714f0e186faf23e7ddb3b26ef618fcf730d46634bd8`.
No managed verifier container or campaign volume remained.

This is a bounded three-task evaluation-line validation and negative result, not a formal model
score or a basis for expanding RL.

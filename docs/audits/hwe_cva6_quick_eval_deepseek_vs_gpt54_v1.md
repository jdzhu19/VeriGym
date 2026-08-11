# HWE CVA6 quick evaluation: DeepSeek versus GPT-5.4

- Date: 2026-08-11
- Status: six samples completed; DeepSeek resolved zero; GPT-5.4 resolved two
- Code commit: `3d39d52993435f39dac98570b193687938c36f65`
- Sampling: the same three tasks, one sample per task, base seed 3, no retry, no best-of-K
- Scope: bounded quick evaluation, not a benchmark score or a basis for expanding RL

## Selection and zero-model qualification

Selection was restricted to CVA6, one-file reference repairs of at most 20 changed lines, and
excluded CVA6 PR2170 and PR2945 because Codex had already seen them in earlier development or
held-out work. Candidate images that could not satisfy the frozen CVA6 source profile were rejected
before any model call. The resulting task set was CVA6 PR2374, PR3107, and PR3171, with reference
changes of 2, 3, and 6 lines respectively.

The prepared source lock SHA-256 is
`13ad3ea6ae5af351db5564bbd5f058ec3d9b0f47e539e66cad145b9d0c537d80`. The official
digest-locked verifier images were:

| Task | Manifest digest | Local image ID |
| --- | --- | --- |
| CVA6 PR2374 | `sha256:085817b4e272e1033f3bbfa2a44340a70e79466ac0dabfd34d8dd9286d0c32ca` | `sha256:e8bf0a516e0b4b0a1d8d1054d154140ce2e063b3603c0bed57f41f980fa1deed` |
| CVA6 PR3107 | `sha256:a603a942eae67bc796aab76d3179ed78db6824188c53b0a144b84e9f69dfcc6f` | `sha256:c00770dc6572530b9565732f69ee11994aa553ac10e32f0fa969f7c47672edff` |
| CVA6 PR3171 | `sha256:42fe58d2e1738718472cbc45136cc5cf2a84b4ccdadd5a2eaad6efc1fd8a31f6` | `sha256:7515393292f7ef5c46151057ff329203c057b78eb84faa77bda045325aa3774e` |

All three official Docker verifiers ran with networking disabled. Each base candidate failed and
each reference repair passed, with zero model processes and zero infrastructure failures. The
qualification report hash is
`b01d1557e03837b6c07ea4a2a75b1a5d2bd0a1c38ecbb583ea84135f2cd7ad68`.

## Independent frozen evaluation lines

The DeepSeek line used agent `deepseek-api-hwe-cva6-quick-eval-v1`, exact provider model
`deepseek-v4-flash`, thinking disabled, and a 16,384-output-token request cap. Its agent-version
hash is `e434d43865a859169cc0f772adf3d42f88f87a0c297426e9ccd26bc4599b27d2`, split
manifest hash is `f154eae771a05237442546deb2f988206e23f661319af002ee6282c5a709a780`, and
content-free freeze hash is
`f70512593449137218e9746d81b02334ee93e0c8b99b31a3e29d17e3ef743f67`. Authentication
and endpoint configuration came from the named `VERIGYM_DEEPSEEK_API_KEY` and
`VERIGYM_DEEPSEEK_API_BASE_URL` environment variables; their values were never persisted or
hashed.

The Codex line used agent `codex-gpt54-xhigh-hwe-cva6-quick-eval-v1`, observed model `gpt-5.4`,
and reasoning `xhigh`. Its agent-version hash is
`8241730ed747ab9580d47c23f37d70c7ecf717923567eb16e1d8a01ae4a8e6de`, split manifest
hash is `33110c8decc25ede26c60be887113701616ab11dd16bbfa3648d48aa10274341`, and
content-free freeze hash is
`028bdcf3582f0fa4c89e0e1ecbaaa8e564b540db71f45e4e41381c0f3c51d303`.

## Outcomes

| Task | DeepSeek result | DeepSeek usage and latency | GPT-5.4 result | GPT-5.4 usage and agent time |
| --- | --- | ---: | --- | ---: |
| CVA6 PR2374 | rejected; no changed file; response reached `length` | 6,110 / 16,384 tokens; 68.01 s | passed; one changed file | 230,081 / 358 tokens; 384.93 s |
| CVA6 PR3107 | rejected by workspace policy; no changed file | 2,874 / 104 tokens; 2.24 s | verifier rejected; one changed file | 213,977 / 252 tokens; 130.97 s |
| CVA6 PR3171 | rejected; no changed file; response reached `length` | 3,070 / 16,384 tokens; 67.51 s | passed; one changed file | 219,167 / 508 tokens; 100.92 s |

Usage columns are provider-reported input/output tokens. All three DeepSeek calls returned normally
from the endpoint, and all three Codex processes exited normally without timing out. Neither line
had an infrastructure-invalid sample. DeepSeek completed zero of three repairs: two responses
consumed the full 16K output budget without yielding a usable candidate, and one violated the
workspace materialization policy. GPT-5.4 completed two of three repairs; PR3107 was an ordinary
verifier rejection.

The DeepSeek plan hash is
`51b4cc19646fe7aed4674fa71fecc1a164a4166e9324bef5806d170f8e29fcfa`, with sanitized
summary hash `2e0b2ddc3b7aff24e8a09da7f1a601707b684f2efb206b402c1a20b807e4b593`. The GPT-5.4
plan hash is `845ded34b177d836d9bffbb52b0b14d81023c2b0d5a3a4abc9db566927019348`, with sanitized
summary hash `994a59c15a2b9ceb77c31d4bacf24e1ed21b322f696b073fc5715e26cbd5510c`.

## Replay, training exclusion, and safety

Visible replay passed for all six stored runs. Offline trajectory validation and source replay
agreed on dataset hash
`41bfd22bc879c777e0837efe24fc02f00668d107050cd3b9c692394938a61a62` for DeepSeek and
`964291171365cc6252c9b4897a30a147796a581c50fe825ba6629827eaa10509` for GPT-5.4. Both
datasets contain exactly three records assigned to their independently frozen `heldout` splits.

Training-reference preparation exited with code 2 for both datasets because there were no eligible
training records, and it created no training bundle. The exclusion report hashes are
`1696a44ecca635bbb100496c4a099f62f7dce1ab5f32b072d579d88f6aa06915` for DeepSeek and
`b569cfdc59933a09309a9e687ed4295d97742c8f67a4bde1574ff5530a8555db` for GPT-5.4.

The context-aware export scans covered 29 files and 98,865 bytes for DeepSeek, and 30 files and
151,469 bytes for GPT-5.4. Both passed with zero hard secret leaks and zero scanner errors, under
report hashes `63ac9d68576f9ac50072858609eb1638963e9fb43a2f2f6b8a6687fc19a55573` and
`ca055950757dfc816b18bbc32101d97a590ad81c14a3db9a6966c6a4ca16199e` respectively.
Raw third-party repository workspaces were not treated as exportable artifacts.

This pilot supports using GPT-5.4 with `xhigh` as the default Codex fallback when Luna is unstable.
It also shows that the DeepSeek endpoint itself is reachable and stable, while the current
single-response repository protocol is not effective for these three small CVA6 repairs.

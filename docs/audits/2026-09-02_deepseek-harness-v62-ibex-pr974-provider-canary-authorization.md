# DeepSeek Harness v62 Ibex PR-974 provider canary authorization

Date: 2026-09-02

## Decision

Authorize exactly one real DeepSeek Harness episode for
`hwe-bench/repo-repair-v1/lowRISC__ibex__pr-974`, with seed 499 and sample index 15,
only after this authorization is merged and the post-merge `main` workflow passes all eight
required job classes. This audit does not authorize a retry, formal collection, SFT training, or
any provider call for another task.

The OpenHands route remains closed after the audited PR-54 behavior failure. PR-974 is a fresh
Harness fallback task and was not consumed by the OpenHands attempt.

## Frozen inputs

- Authorization identity:
  `deepseek-harness-hwe-v62-ibex-pr974-provider-canary-v1`
- Authorization hash:
  `6bf16888b107fdfe26da968a053e9dc371c9cf30c5cfb76b80db3caca07b0b74`
- Qualification merge: `e63b72b83568ba442148f139955daace518a62c6`
- Qualification post-merge main run: `33625137601`, all eight job classes passed
- Task hash: `fe8cb6e6b8ea27a0a443322107ad0163fc315c66f899b9cb56ceb9c820000284`
- Source hash: `0bb584274d5584dca886a00e377920e27f4c971f175487c9baa1b36fcb9b5221`
- Command image lock:
  `ce72dd5277f44407a2c2b64bc2b3989e30625cd2727c2d87b7b8829dc9e4fd22`
- Command image:
  `sha256:d888a3faa8fe5d6cf3717f8488a96e5a8ce5d3122d0da321dcb3fbafe8ae6bab`
- Verifier image:
  `sha256:ac668cbaf8b16e2804adf222834a06965282841bc30927fe5f98e3a2239b431b`
- Security scan ID:
  `7b0bccf29d490b1b22a104c0ba29a2df34486484644ce6d17e15635db86690dc`
- Harness upstream revision: `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`
- Harness tracked-tree hash:
  `22df3762b332f3651107756dc80a9397f27741c1256e83ca32614729f27bd566`
- Model: `deepseek-v4-flash`, provider hidden thinking disabled
- Qwen tokenizer hash:
  `440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e`

The frozen Harness checkout was copied without network access to
`/data2/jiadongzhu/Agent/datasets/deepseek-harness/` and resolves to the same upstream commit.
The runner, integration changes, tests, and future trajectory/SFT work are under the `/data2`
workspace. VPN state and the independent public-image downloader are not changed.

## Behavior and limits

The new `deepseek-harness-hwe-agent-v4` identity derives from the successful v3 behavior path
without altering historical v3 transcripts. Ordinary requests retain provider-default automatic
tool choice, concise public rationale, and one-or-more typed sibling calls executed in emitted
order. One same-session content-only recovery remains available. Private reasoning, foreign tools,
escaping paths, hidden assets, credentials, and task-tool network access fail closed.

The v4 route adds these bounded controls:

- request 65 is blocked before provider dispatch;
- total observed provider input plus output tokens must not exceed 1,000,000;
- each response is limited to 2,048 output tokens at temperature 0;
- provider-request and whole-episode retries are zero;
- action 16 injects the fixed pre-edit checkpoint when no effective change exists;
- action 32 terminates `no_progress` when no effective change exists;
- after the first effective modification, the action-32 pre-edit gate is permanently released;
- command tools run through the scanned Verilator image with `network=none`.

## Admission and stopping rule

A successful canary requires all six planes: benchmark verifier, protocol, trajectory,
infrastructure, security, and SFT admission. Every supervised assistant decision is re-tokenized
with the exact frozen Qwen tokenizer, must fit 65,536 tokens without truncation, and keeps all
sibling calls in one target. Failed-tool and recovery decisions remain input context but are not
supervised.

Any post-provider verifier, policy, empty-patch, trajectory, provider-budget, or exact-64K failure
consumes and permanently freezes PR-974. Infrastructure or security invalidity stops closed. The
runner never opens formal collection or starts training.

## Credential-free checks before merge

The authorization change must pass:

```text
ruff check integrations/verigym-deepseek-harness \
  scripts/collect_ibex_hwe_deepseek_harness_v62_provider_canary.py \
  scripts/collect_cva6_hwe_deepseek.py \
  integrations/verigym-deepseek-harness/tests/test_v62_provider_canary.py
ruff format --check integrations/verigym-deepseek-harness \
  scripts/collect_ibex_hwe_deepseek_harness_v62_provider_canary.py \
  scripts/collect_cva6_hwe_deepseek.py \
  integrations/verigym-deepseek-harness/tests/test_v62_provider_canary.py
mypy integrations/verigym-deepseek-harness/src/verigym_deepseek_harness \
  scripts/collect_ibex_hwe_deepseek_harness_v62_provider_canary.py
pytest -q integrations/verigym-deepseek-harness/tests \
  tests/unit/test_hwe_deepseek_harness.py
```

No provider request is allowed while validating this authorization pull request.

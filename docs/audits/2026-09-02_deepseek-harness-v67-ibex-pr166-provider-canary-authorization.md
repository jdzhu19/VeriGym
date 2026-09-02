# DeepSeek Harness v67 Ibex PR-166 provider canary authorization

Date: 2026-09-02

## Decision

Authorize exactly one real DeepSeek Harness episode for
`hwe-bench/repo-repair-v1/lowRISC__ibex__pr-166`, with seed 501 and sample index 17, only after
this authorization is merged and the post-merge `main` workflow passes all eight required job
classes. This audit authorizes no retry, other task, formal collection, or SFT training.

PR-222 crossed the provider boundary under v65 and is permanently consumed. Its post-process stop
was reproduced offline as two concrete scaffold defects: the missing v4 integration-track literal
and rejection of the core-added `content_truncated: false` marker field. v66 repaired both defects,
added regressions through the real core bridge, qualified fresh PR-166 as base-FAIL/reference-PASS,
and sealed its command image. PR #101 merged v66 as
`64c3883eab594eab23a9ccc6452705ae4381c52f`; post-merge run `33641643247` passed all eight job
classes.

## Frozen identity and inputs

- authorization identity: `deepseek-harness-hwe-v67-ibex-pr166-provider-canary-v1`;
- authorization hash:
  `51914255de5d7ad8994b0e58cbc8f2a8b6c20703dab48369a6bf36e7ad3bb246`;
- seed/sample: 501/17;
- model: `deepseek-v4-flash`, hidden thinking disabled;
- Harness revision/version: `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e` / `0.1.1-rc.2`;
- VeriGym Harness integration: `0.5.0`;
- task hash: `d3c05fdf9be2c8c9dae301f702de207c0986dc222625a0c573e1745b14b45d24`;
- source hash: `205b4e61416e4bca5bd7ef8a52167637845b1817e09e960e746b572c7814f18a`;
- command-image lock: `d174aa1ce310c672cafa5820197351250b2b9b7b9fecdc61b1b0f01845a4864f`;
- command image: `sha256:1b5c838add1f3f969ce7e6887fe68c5c84078b2b2920535856751c7bff632809`;
- verifier image: `sha256:b7894597216546304802a6470aab76b0db297854704854b21fa32de3fd80a240`;
- security scan ID: `60277eaa6168466c9b4789374c3a5fab56e049c516360b4efa992dd2a377563e`;
- exact Qwen tokenizer hash:
  `440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e`.

The source, command image, verifier image, security receipts, tokenizer, and base-model lock are
content-bound. Command tools and verification run with `network=none`. The VPN state and the
independent public-image downloader are not changed.

## Boundary accounting and admission

PR-166 becomes consumed only after the fixed private provider marker and its exact four-field
bounded public event establish that at least one provider request started. Entry into the episode
does not consume the task. A pre-marker infrastructure failure leaves it unconsumed; any later
failure consumes and freezes it. Provider and whole-episode retries are zero.

The episode retains automatic tool choice, concise public rationale, atomic pre-validation and
ordered serialization of sibling calls, one same-session content-only recovery, and fail-closed
handling of private reasoning or unsafe tools. Limits remain 64 provider calls, 1,000,000 provider
tokens, 65,536 context tokens, 2,048 output tokens, temperature 0, and a one-hour process timeout.

A successful trajectory requires benchmark, protocol, trajectory, infrastructure, security, and
SFT-admission planes all true. Every supervised assistant decision must fit the exact frozen Qwen
tokenizer at 65,536 tokens without truncation. Failed and recovery decisions remain context-only;
sibling calls remain one supervised decision. Even success leaves formal collection and training
closed pending a separate audit.

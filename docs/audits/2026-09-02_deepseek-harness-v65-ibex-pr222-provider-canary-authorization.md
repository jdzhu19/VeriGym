# DeepSeek Harness v65 Ibex PR-222 provider canary authorization

Date: 2026-09-02

## Decision

Authorize exactly one real DeepSeek Harness episode for
`hwe-bench/repo-repair-v1/lowRISC__ibex__pr-222`, with seed 500 and sample index 16, only after
this authorization is merged and the post-merge `main` workflow passes all eight required job
classes. This audit does not authorize a retry, formal collection, SFT training, or a provider call
for any other task.

The OpenHands route remains closed after the audited PR-54 behavior failure. The earlier Harness
PR-974 attempt stopped before the atomic provider-request boundary and is frozen administratively.
PR-222 is a fresh, provider-unconsumed Harness fallback task.

## Frozen inputs

- authorization identity: `deepseek-harness-hwe-v65-ibex-pr222-provider-canary-v1`;
- authorization hash:
  `197c69d1f0c6b765ba1d555509f419b7a0c206420559ce68d162fe7c9bf4fa05`;
- qualification merge: `f325894e6552f1039858fc6255052478056c5ef6`;
- qualification post-merge main run: `33635765073`, all eight job classes passed;
- task hash: `7e62a998631bf29c57260dbeefbdb9fb442b6828a9f6f548aa92ea2751a4a682`;
- source hash: `196991d6eebeb73106594898bd4e6068d8f5d6ee02417bb7b90eab19386e5c8e`;
- command-image lock:
  `ccd1570f4614f57e1c4df6d4a26510081ca9486a6409e7474a0e52a134cbd5ed`;
- command image:
  `sha256:6502d4239228942b702724c596c54938352c90a69f65891291761e3d18ceff04`;
- verifier image:
  `sha256:cde141cb0f4c8458dc1f0339c2834090126e70101adfca7b4910d23b54046c58`;
- security scan ID:
  `c8dc75f9b69b82f1327e16da3359b9ef49583b410bad50167e4da4113fa4d14b`;
- Harness upstream revision: `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`;
- Harness tracked-tree hash:
  `22df3762b332f3651107756dc80a9397f27741c1256e83ca32614729f27bd566`;
- VeriGym Harness integration: `0.4.0`;
- model: `deepseek-v4-flash`, provider hidden thinking disabled;
- exact Qwen tokenizer hash:
  `440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e`.

The frozen Harness checkout remains at `/data2/jiadongzhu/Agent/datasets/deepseek-harness/`.
The runner, trajectory artifacts, and later SFT work remain under `/data2`. The VPN state and the
independent public-image downloader are not changed. Command tools and benchmark verification use
`network=none`.

## Provider-boundary accounting

The runner does not mark PR-222 consumed when it enters the episode or starts the Harness process.
Consumption begins only when the v64 atomic marker is observed and its bounded event appears in the
public trace. The private marker is emitted after the first `agent/request` boundary and contains
only a fixed format and ordinal. The derived public event contains only fixed booleans and a lower
bound of one request. Neither contains a credential, endpoint, prompt, response, timestamp, or
secret hash.

If startup fails before that marker, the result is pre-provider infrastructure-invalid and PR-222
remains provider-unconsumed. If the marker is present, any subsequent failure consumes and freezes
PR-222. Marker payload drift fails closed. Provider-request and whole-episode retries remain zero.

## Behavior, limits, and admission

The frozen v4 route retains provider-default automatic tool choice, concise public rationale,
one-or-more typed sibling calls serialized in emitted order, and one same-session content-only
recovery. Private reasoning, foreign tools, escaping paths, hidden assets, credentials, and
task-tool network access fail closed.

The episode is limited to 64 provider calls, 1,000,000 provider tokens, 65,536 context tokens,
2,048 output tokens, temperature 0, and one hour of Harness process time. Action 16 injects the
fixed pre-edit checkpoint when no effective modification exists; action 32 terminates
`no_progress` while that condition continues. The no-progress gate is permanently released after
the first effective modification.

A successful canary requires all six planes: benchmark verifier, protocol, trajectory,
infrastructure, security, and SFT admission. Every supervised assistant decision is re-tokenized
with the exact frozen Qwen tokenizer and must fit 65,536 tokens without truncation. Sibling calls
remain one target; failed-tool and recovery decisions remain context-only. Formal collection and
training remain closed even after a successful canary until a separate audited materialization.

## Credential-free checks before merge

The authorization change must pass Ruff, formatting, Mypy, the full credential-free Harness test
suite, the HWE decision tests, and the repository's eight required Actions classes. No provider
request is allowed while validating or reviewing this authorization pull request.

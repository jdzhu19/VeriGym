# Verilator public-feedback qualification v1

## Outcome

The optional Verilator public-feedback backend is qualified as a deterministic, candidate-only
compile/lint path for VerilogEval and RTLLM. It is exposed through separately identified variants,
does not change historical variants, keeps final hidden functional verification on Icarus 12, and
does not enable PPA.

One real Codex CLI 0.147.0 episode was also executed with exactly one model process and zero
automatic retries. The runtime and model-call identities were valid, but the episode was not an
end-to-end success: Codex returned a machine-event item type that the frozen scoring adapter did
not accept before any repository tool call. That result is retained as a valid failed episode and
is not represented as Verilator or multi-turn qualification.

## Frozen scope and boundaries

- VerilogEval variant: `v2-spec-to-rtl-agent-eval-verilator-v1` (156 tasks).
- RTLLM variant: `v2-agent-eval-verilator-public-v1` (50 tasks).
- Public action: fixed, shell-free `verilator --lint-only --timing` compile/lint contract over
  candidate source only.
- Final hidden action: the pre-existing isolated Icarus compile/regression verifier, reached only
  after typed `finish`.
- Public functional smoke: not added by this variant.
- PPA: disabled.
- Result interpretation: `diagnostic_only=true` and `benchmark_score_claimed=false`; a lint pass is
  not a functional-correctness verdict.

The aggregate identities computed over the loaded task and public-contract maps were:

| Suite | Task count | Task-map SHA-256 | Public-contract-map SHA-256 |
| --- | ---: | --- | --- |
| VerilogEval | 156 | `e0ec8a2fb4a66ccb82fb965d2f6da7f74023b832f8920b3bbbcfcbfcb6d19328` | `7e8f47e5dbe6a05f884984bab0136cceef786a28eccd8cfa08a42be8833a5f43` |
| RTLLM | 50 | `dabdf0f9bcab3c8063f49a030eec0c41207be13a195b6f582a771522cc02938b` | `6bd118b0f00b5229d484720a2441a57739c248424b5e732b17c9bc48d7053b60` |

The historical v1 launcher remains byte-for-byte unchanged at
`e3276ee142e7de78fd60bf4078138152d1974c93f72f27fd2eb95a3f6493b407`. Verilator contracts use the
new v2 launcher identity
`32e16ea6c1664e5f9f968d6d05a884b91c60b4337ef5cfb0080b4f91cadff705`.

## Tool and image identities

The qualified local public image was
`verigym/rtl-verilator:5.052-iverilog12-r1`:

- image ID: `sha256:9bd1ce7fdbb3c7cbcf82cc53fb5092513669b9c5ca5001d4089d2931d985f58a`;
- image size: 244,393,260 bytes;
- runtime user: `10001:10001`;
- Verilator output: `Verilator 5.052 2026-09-05 rev vUNKNOWN-built20260905-ea338be`;
- Verilator peeled source commit: `ea338be98e1e838d3518809ce8899f85a009963c`;
- Icarus base digest:
  `sha256:44d5e56dc4ecede0aa9b53fd1dc63b2bdfb153b140084ace6b4847edbb673269`.

The source archive and license set are included. Network-none/read-only/non-root runtime smoke,
image-history marker scanning, and the absence of Codex from the public image all passed.
`verigym doctor` reported `docker:iverilog`, `docker:vvp`, `docker:verilator`, and
`tool:verilator.compile` healthy.

The Codex-bearing repository-agent image remains local-only:

- tag: `verigym/codex-repository-agent-verilator:0.147.0-v1`;
- image ID: `sha256:fc25b267ebc6052d291faefc13a7f7eda54805c5e93b23ca2cd85598ae75551f`;
- image size: 502,691,290 bytes;
- host npm launcher SHA-256:
  `134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477`;
- container-native Codex SHA-256:
  `cb0a15567e9a60a5820d54b0f6ae86d504dc3805c1eab21a47f70e3eb7b73a40`.

No Codex authentication, provider credential, dataset, task workspace, hidden verifier asset,
commercial asset, or trajectory is part of either committed build context. The Codex composition
is intentionally excluded from public publication.

## Functional qualification

The exact Verilator 5.052 image ran one bounded, network-none, read-only, non-root container over
412 verdicts:

| Partition | Expected accept | Expected reject | Result |
| --- | ---: | ---: | --- |
| VerilogEval reference / syntax mutant | 156 | 156 | all correct |
| RTLLM reference / missing-module mutant | 50 | 50 | all correct |

The bounds were 2 GiB memory and swap, 2 CPUs, 256 PIDs, and a 128 MiB `noexec`, `nosuid`, `nodev`
temporary filesystem. A separate zero-model repository-agent bridge check used the shipped v2
launcher and returned exit 0 for the reference and exit 1 for the syntax mutant, with Verilator
identified in both structured results.

Regression and static checks:

- ordinary repository tests: 1,748 passed, 1 real-Codex test skipped, 54 opt-in tests deselected;
- RTLLM plugin tests: 125 passed, 29 external/site tests skipped;
- VCS/MCP regression: 15 passed, 1 site-bound opt-in test skipped;
- Ruff check and format check: passed;
- core mypy (223 files) and RTLLM mypy (6 files): passed;
- generated schema drift and `git diff --check`: passed.

## Real Codex CLI episode

Campaign `verilog-eval-verilator-public-codex-gpt54-xhigh-smoke-v1` executed one bounded
`Prob001_zero` episode with requested model `gpt-5.4`, reasoning effort `xhigh`, seed 0, one Codex
process, and zero retries. The observed host CLI identity was `codex-cli 0.147.0` with the frozen
launcher hash above; the external repository-agent image and Verilator/Icarus identities resolved
successfully.

The process ended after 6.107 seconds with exit code 1. Five CLI machine events and one external
model call were accounted, but no MCP tool event was accepted. The terminal classification was
`scoring_event_ineligible` / `scoring_event_unsupported_item`. Consequently:

- no repository read, patch, public-test call, or typed `finish` occurred;
- final hidden Icarus nodes were correctly skipped;
- infrastructure validity remained true;
- offline replay integrity and the host-path leakage scan passed;
- the candidate was unresolved and no benchmark score was claimed.

This run demonstrates that the selected Codex 0.147.0 event stream is not yet compatible with the
frozen scoring parser. A future fix must first add and fixture-test the newly observed event shape,
then use a new separately identified campaign if another model episode is authorized. This failed
episode must not be retried or rewritten.

## Publication

The committed workflow publishes only the open RTL image as
`ghcr.io/jdzhu19/verigym-rtl-verilator:5.052-iverilog12-r1`, refuses to replace an existing release
tag, attaches SBOM and provenance attestations, pulls the digest back, and repeats the
network-none security smoke. Publication run `33980342720` completed successfully for source
commit `c7d5f1694bd07fa9edf3bb0c9c2241a529fa22f3`. The immutable OCI index digest is
`sha256:4b33e502e12c8cfb5df752ca822b1bf0287337b61db9029d74988885280600ca`; its `linux/amd64` image
manifest is `sha256:47ce9b5ad74e907e9140681e6386f9e8462b6a038beaaded0ea93377a8f2e271`.

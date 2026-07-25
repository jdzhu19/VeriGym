# Codex CLI conformance smoke audit

Audit date: 2026-07-25. This audit is separate from the historical VeriGym
v0.1.0 release-candidate bundle, which was not modified or reinterpreted.

## Scope and baseline

- Audited baseline: `0a1948f96b44811afa00cc87743c22b6d0396f33`
- Implementation revision: `bd2b686b5630d98469bd3f6044f6b80fdd9d4b24`
- Work branch: `codex-cli-conformance`
- Tracks: `codex_cli_model_proxy` and `codex_cli_external_agent`
- Mandatory real plan: two toy RTL tasks by two tracks, one attempt each
- Retry, best-of-K, shared sessions, and outer-agent repair: disabled

Track A is a CLI-mediated model proxy, not a direct API benchmark. Track B is
an external coding agent evaluated only after VeriGym’s ordinary candidate
freeze and separate hidden-verifier flow.

## Real zero-call capability evidence

The installed-wheel `verigym-codex doctor` ran only `--version`, `--help`, and
`exec --help`. It recorded three diagnostic processes and zero model calls.

- CLI: `codex-cli 0.144.6`
- Executable SHA-256:
  `134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477`
- Capability fingerprint:
  `c7512f2de09ca94c410a878155b1003ab0bca3a4e9ca68172f4ee9a48c43a5d8`
- Required read-only/workspace-write sandboxes and JSONL/stdin protocols:
  discovered

## Mandatory real smoke status

At execution time, `VERIGYM_RUN_CODEX_CLI_TESTS`,
`VERIGYM_CODEX_BINARY`, `VERIGYM_CODEX_MODEL`,
`VERIGYM_CODEX_AUTH_MODE`, and the sealed-capability environment selection
were unset. No model or authentication choice was invented. The all-or-none
launcher was therefore not executed: zero real model processes, zero real run
directories, and no real per-run outcomes, replays, scans, or reports exist.

This is an external-prerequisite block, not a fake-test substitute and not a
real-smoke pass.

## Offline and regression evidence

- Codex CLI, reporting, release-contract, and sampling tests: 98 passed,
  1 real-test opt-in skip.
- Ordinary non-daemon regression suite: 328 passed, 10 prerequisite skips,
  13 deselected.
- Ruff format/lint, strict mypy (134 core and 13 plugin modules), schema drift,
  YAML parsing, patch hygiene, and local Yosys (2 tests): passed.
- Docker Milestones 7/8 regression: 13 passed and 1 expected optional-data
  skip during branch verification.

The final installed fake flow made exactly three diagnostics and four fake
model processes. All four runs were terminal with zero infrastructure
failures; Track A resolved both candidates and proved zero tool use, while
Track B submitted two unchanged candidates that failed ordinary hidden tests.
All 20 flow checks, four integrity checks, secret/host/hidden scans, four
model-free replays, and JSON/CSV/Markdown reports passed. Its frozen plan hash
is `2d3199b1c9027501ae7202efc55304d04be14a49a412b57150ec98625682dcb2`.

## Package evidence

Both archives passed bounded distribution scans, installed entry-point
discovery, `pip check`, and the full installed-wheel RTL public API example
with Icarus Verilog.

- Core wheel: `970059e3503beae6a2ec245f28f5a68926211bfa30cc2776c5b0d238a88dfd97`
- Core sdist: `088d26a0b9ed662633f45b9a3b6267eb831eb0ea3e201748346ce66b81d9a019`
- Plugin wheel: `c3aa3609d8d8c8d4700c00a672eb92f9250d946d03e970fa74f53603204e6505`
- Plugin sdist: `c9f9ce8547d7892083ab7ccc6a28610d5ee28085f73440c6deaa5cf4bce22afd`

PEP 517 isolation could not reach the configured package-index proxy, so the
recorded clean-revision builds used installed build requirements with
`--no-isolation`; installed verification used offline dependency resolution.

## Larger pilot

The protected plan contains 30 items from five frozen
[VerilogEval V2 spec-to-RTL tasks](https://github.com/NVlabs/verilog-eval/tree/main/dataset_spec-to-rtl).
Source commit `c498220d0a52248f8e3fdffe279075215bde2da6` and dataset hash
`432b712cea110d4b5d35521f691db1bc3e726a77c6fc72fc1c916a85361ddbf2`
were verified. Plan hash:
`c6d6f46e4bba4a7c5e21e9eb805e5d0a5d7878051f3774f2d467f0f372936354`.
Both execution guards were absent, so it created no run directories and made
zero model calls.

CODEX CLI CONFORMANCE SMOKE: BLOCKED

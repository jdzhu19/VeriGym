# Codex CLI release and audit index

Index date: 2026-07-26.

This index records the durable Codex CLI semantic-conformance state. It does not replace,
reinterpret, or modify any sealed evidence bundle or historical verdict.

## Final semantic baseline

- Source commit: `1deea550815603f72f68887b8db3577ea9c72462`
- Source tree: `d4546c218d95b59c53029a71b7c81f97f5d7d35e`
- Branch: `codex-cli-conformance`
- Final gate: **PASS**
- Codex CLI: `codex-cli 0.144.6`
- Executable SHA-256:
  `134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477`
- Capability fingerprint:
  `4d30738d855263862736d0468e28b183f12d1990089e56b28697b6de9baf0bcb`
- Frozen four-run plan:
  `621103d54fa7adf6c61c5a27a9a7eeda6b4910d0933c0aff8d16f17cb20a5529`

`codex-cli-readonly-agent` is a read-only, single-turn Codex CLI agent. It is not a
`ModelClient`, ChatEval path, pure API evaluation, or direct API benchmark.
`codex-cli-agent` is the external coding-agent track that may edit only the visible task
workspace before VeriGym freezes the candidate and runs the hidden verifier. Direct API model
evaluation remains a separate future integration.

The final campaign launched exactly four frozen processes, with no optional probe, retry, resume,
candidate repair, model substitution, API key, or Best-of-N selection. Both read-only-agent runs
satisfied the typed event policy. Both workspace-writing runs reached candidate freeze and
compilation; their hidden-test failures were preserved as benchmark outcomes, not integration
failures. All four terminal runs replayed with Codex unavailable and zero replay CLI/model calls.
Integrity, hidden-asset, secret, proxy-value, host-path, and source-immutability checks passed.

## Sealed evidence

- Bundle:
  `verigym-autonomous-codex-track-a-semantic-1deea55-20260726T054713Z`
- Audit manifest SHA-256:
  `2b6d13d74818bc8db3dfa482b5276d87e65590d3b2576d629be0465990e6d32e`
- `SHA256SUMS` SHA-256:
  `0282e0993c57623695ce828c83e30bf5eaa0903ae0d14726f3fbb4648820be88`
- Verified entries: 251

The baseline package seal recorded:

- Core wheel:
  `a996584aba5fae19b29997372f9c5f1a2db2d4f7f28401eb50489e4e77dd070d`
- Core sdist:
  `160ac7e36102bd5540c6cebfad96eca752ca0bd4e8d9a3f8f683ebca4b2ddfe8`
- Plugin wheel:
  `124cf598fa88da2951ca74669a7faca5b273c33a45089886f002eb178f426426`
- Plugin sdist:
  `48542db5d2b19c20db4deea4cc7af480860762ecad826b01b36cf67b12938196`

## Historical verdict ledger

Historical verdicts are append-only. A later semantic correction does not turn an earlier
BLOCKED or FAIL campaign into a PASS.

| Revision | Verdict | Durable interpretation |
| --- | --- | --- |
| `bd2b686b5630d98469bd3f6044f6b80fdd9d4b24` | BLOCKED | Initial fixed smoke lacked the required external execution selections; zero real model processes ran. |
| `b459e4bbcb2cc02f6c21b930a42fce2160144d3d` | FAIL | Four authorized processes ran once and timed out; no retry or repair occurred. |
| `f52009ba634d37058a2489c88c9491548941ca6f` | BLOCKED | Preflight stopped before real execution while proxy and timeout handling were stabilized. |
| `aeaa1797075d89579f184ab53743cfe5a4557cdc` | FAIL | The sealed campaign correctly failed its then-current Track A zero-tool rule after one run emitted six CLI tool events. |
| `1deea550815603f72f68887b8db3577ea9c72462` | PASS | Track A was truthfully reclassified as a read-only agent and the bounded final campaign passed semantic conformance. |

The sealed `aeaa179` bundle remains
`verigym-autonomous-codex-conformance-aeaa1797075d89579f184ab53743cfe5a4557cdc-20260726T034607Z`;
its audit-manifest hash is
`e36e3d212ceeba6894f99b78cf293b99c5ce8a3ad3a8ef18032d2f46a17dbf84`.

## Preserved initial BLOCKED audit

The 2026-07-25 audit used audited baseline
`0a1948f96b44811afa00cc87743c22b6d0396f33` and implementation revision
`bd2b686b5630d98469bd3f6044f6b80fdd9d4b24`. Its then-current track labels were
`codex_cli_model_proxy` and `codex_cli_external_agent`; those labels are historical provenance,
not the final semantic classification.

Its installed-wheel doctor made three diagnostic calls (`--version`, `--help`, and
`exec --help`) and zero model calls. It recorded capability fingerprint
`c7512f2de09ca94c410a878155b1003ab0bca3a4e9ca68172f4ee9a48c43a5d8` against the same CLI
version and executable hash listed above. Required execution selections were absent, so the
fixed real launcher did not run: zero real processes, run directories, replays, scans, or
reports. The verdict remains **BLOCKED**.

Offline evidence recorded 98 Codex/reporting/contract/sampling tests passed with one real-test
opt-in skip; 328 ordinary tests passed with 10 prerequisite skips and 13 deselections; and Ruff,
strict mypy, schema drift, YAML, patch hygiene, local Yosys, and relevant Docker checks passed.
The installed fake flow completed four terminal fake runs, 20 flow checks, four integrity
checks, four model-free replays, and leakage scans under plan hash
`2d3199b1c9027501ae7202efc55304d04be14a49a412b57150ec98625682dcb2`.

The preserved initial package hashes are:

- Core wheel:
  `970059e3503beae6a2ec245f28f5a68926211bfa30cc2776c5b0d238a88dfd97`
- Core sdist:
  `088d26a0b9ed662633f45b9a3b6267eb831eb0ea3e201748346ce66b81d9a019`
- Plugin wheel:
  `c3aa3609d8d8c8d4700c00a672eb92f9250d946d03e970fa74f53603204e6505`
- Plugin sdist:
  `c9f9ce8547d7892083ab7ccc6a28610d5ee28085f73440c6deaa5cf4bce22afd`

Its protected, unexecuted 30-item VerilogEval plan used source
`c498220d0a52248f8e3fdffe279075215bde2da6`, dataset hash
`432b712cea110d4b5d35521f691db1bc3e726a77c6fc72fc1c916a85361ddbf2`, and plan hash
`c6d6f46e4bba4a7c5e21e9eb805e5d0a5d7878051f3774f2d467f0f372936354`.

## Deferred scope

The prepared 30-run VerilogEval pilot remains unexecuted. No direct API evaluation or other
Milestone 10 work is part of this baseline.

CODEX CLI SEMANTIC CONFORMANCE BASELINE: PASS

# MVP compliance matrix

Statuses reflect executed baseline or stabilization checks, not file existence. Final command
records and logs are copied to `release_audit/`; the baseline is
[`audits/mvp_baseline.md`](audits/mvp_baseline.md). A real external VerilogEval checkout and
Python 3.12/3.13 interpreters are unavailable in the current audit environment, so the overall
release-candidate gate remains failed.

| Requirement | Status | Implementation and automated evidence | Acceptance command / evidence ID | Limitation |
|---|---|---|---|---|
| Clean Python 3.11 install | blocked | `pyproject.toml`; `scripts/installed_conformance.py` | `installed-wheel`; `clean-dependency-install` | Wheel works offline with audited system dependencies; a fresh resolver cannot access an index. |
| `doctor` without commercial tools | pass | `src/verigym/cli/doctor.py`; installed conformance | `installed-wheel` | Optional components are diagnostic. |
| Toy ChatEval | pass | `SingleTurnAgent`; `tests/integration/test_milestone5.py` | `offline-core` | Static offline model only. |
| Same task in AgentEval | pass | `VeriGym.run`; `tests/integration/test_vertical_slice.py` | `offline-core` | `LocalRuntime` is trusted. |
| Visible tools; hidden verifier isolation | pass | `Environment`, separate sessions; workspace/security tests | `offline-core`, `docker-icarus` | Docker trusts host kernel/daemon. |
| Separate verifier execution context | pass | orchestrator freeze/reverify paths; Docker session tests | `offline-core`, `docker-icarus` | No formal isolation proof. |
| Complete run artifact layout | pass | run writer plus `artifact_manifest.json`; integrity tests | `offline-core` | Older artifacts are `legacy_unverified`. |
| Known-good/known-bad distinction | pass | verifier/scoring schemas and integration tests | `offline-core`, `docker-icarus` | Candidate failure remains exit 1. |
| Budget and termination enforcement | pass | `BudgetTracker`; budget/trace/environment tests | `offline-core` | Wall-time accuracy is host dependent. |
| Replay without model call | pass | `replay_run`; replay/reverify tests | `offline-core`, `docker-icarus`, `docker-yosys` | Exact optional runtime/tool must exist for reverification. |
| External-path VerilogEval | blocked | adapter/source tests; real-checkout test marked `external_benchmark` | `external-verilog-eval` | No real checkout was supplied; synthetic conformance passed only. |
| Independent sampling and canonical pass@k | pass | sampling service/equation; sampling tests | `offline-core`, `synthetic-verilog-eval` | Infrastructure errors invalidate pass@k. |
| Optional Yosys quality | pass | Yosys tool/profile; local and Docker tests | `local-yosys`, `docker-yosys` | Educational mapped area only. |
| Correctness-gated PPA eligibility | pass | projection/comparison/report partition tests | `offline-core`, `docker-yosys` | Timing/power/WNS/TNS stay null. |
| Unit/integration/conformance/determinism/security | pass | `tests/` plus security audit | `offline-core`, opt-in runtime checks | External real-data coverage is blocked separately. |
| Extension/profile documentation | pass | `docs/adding_*`, `plugin_api.md`, `ppa_profiles.md`; docs test | `quality-docs` | External plugins are trusted installed host code. |

## Release-only requirements

Schema drift, sanitized golden compatibility, embedded provenance, artifact integrity, package
scans, reproducible archives, installed external plugins, and the public API have dedicated
evidence IDs. A `pass` above does not override a blocked required release check. The authoritative
gate and reasons are in `release_audit/audit_manifest.json`.

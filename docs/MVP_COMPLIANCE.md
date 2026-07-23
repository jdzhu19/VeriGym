# MVP compliance matrix

This matrix maps each Milestones 0–9 contract to executable evidence. It does not declare a
release result: the sealed historical `release_audit/` remains a failed audit, while each newly
generated bundle records its own authoritative classifications in `audit_manifest.json`.

| Requirement | Implementation and required evidence | Limitation |
|---|---|---|
| Clean installed Python | `python.3.11`, `python.3.12`, `python.3.13`, and `package.clean-dependency-install` create isolated venvs, resolve from a hashed offline wheelhouse, run `pip check`, and import from site-packages. | The wheelhouse is prepared separately and supplied explicitly. |
| `doctor` and full public API | `package.installed-wheel` checks CLI help/doctor, installed plugin origin and policy, one RTL run, model-free replay, sampling/pass@k, a frozen experiment, and reports. | Full conformance requires actual `iverilog` and `vvp`; their outputs are recorded. |
| Toy ChatEval and AgentEval | `local.icarus` exercises `SingleTurnAgent` and `VeriGym.run`. | Static offline model; `LocalRuntime` is trusted. |
| Hidden verifier isolation | `offline.core-no-tools` and `docker.icarus` test separate workspaces, sessions, and hidden-asset boundaries. | Docker trusts the host kernel and daemon. |
| Complete, integrity-bound artifacts | Offline integrity, golden compatibility, and schema-drift checks cover run, replay, batch, experiment, and report artifacts. | Older artifacts remain `legacy_unverified`. |
| Error distinctions and budgets | Local/Docker checks preserve candidate failure, infrastructure failure, budget, and termination semantics. | Candidate failure remains process exit 1. |
| Model-free replay | Local and exact-image Docker Icarus/Yosys checks verify replay without another model call. | Reverification needs the recorded runtime/tool identity. |
| External VerilogEval | `verilog-eval.external` uses a clean, exact-commit checkout and records license/content hashes, known-good/bad results, hidden isolation, and replay model-call counts. | The external corpus is never bundled or used by ordinary CI. |
| Sampling and pass@k | Local and synthetic-batch checks exercise independent samples and canonical pass@k. | Infrastructure errors invalidate pass@k. |
| Yosys comparison safeguards | Local/Docker Yosys and profile checks enforce correctness-gated toy-area eligibility. | Timing, power, WNS, and TNS remain null. |
| Batch, resume, and reporting | Offline and Docker batch checks cover frozen plans, resume, aggregation, and reports. | No distributed execution is included. |
| Extension documentation | Documentation checks cover suite, tool, agent, runtime, plugin, and PPA-profile interfaces. | Installed plugins are trusted host code and remain policy-bound. |

## Release-only requirements

Clean Git identity, frontend and reproducible builds, embedded `dirty=false` provenance,
distribution scans, package hashes, security checks, and bundle self-validation are required.
Only an audit whose every required evidence entry is `passed` may report `PASS`.

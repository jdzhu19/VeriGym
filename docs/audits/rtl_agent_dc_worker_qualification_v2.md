# RTL AgentEval disposable DC worker qualification v2

Qualification date: 2026-08-28. This record covers bounded infrastructure qualification for the
two pinned RTLLM AgentEval tasks. It is not a model campaign, does not measure optimization
quality, and must not be reported as a benchmark score.

## Scope and identities

- VeriGym branch: `agent/rtl-agenteval-v1`.
- RTLLM source commit: `41b26896e33b536940116a975626455eed3de65e`.
- Tasks: `rtllm/counter_12_agent_eval_v1` and
  `rtllm/up_down_counter_agent_eval_v1`.
- Commercial synthesis identity: Design Compiler T-2022.03-SP1 with the existing explicit-power
  v4 `compile_ultra` flow.
- Isolation kind: one disposable LSF job and one private workspace per uncached candidate.
- Worker-launcher SHA-256: `406417743767715fb36bbfcc6894002b516fb9e25952c120aa42051288c5bd17`.
- Worker code-identity SHA-256:
  `2166f538115e173b9a8ce98a9835c4de7c8b04e3899d9b5d82b8881354632551`.
- Isolation-profile SHA-256:
  `80d606ec2bb20632277c4c9960bf364783a9a2fc8ac3662e5f52826c37394a7c`.
- Combined worker-contract SHA-256:
  `241c0e4a8d752788ab12c4cfd602fd1364c4a3c152cb0e600d22b76e64345cff`.

The site wrapper, scheduler configuration, profile files, PDK/library, SDC, license material,
commercial binaries, benchmark checkout, raw reports, and trajectories are not committed. The
worker contract describes its network boundary as `site_license_controlled`; it does not claim
network isolation.

## Evidence

### E-001: external design reference

The review used the official [POSTEDA-Bench repository](https://github.com/pengjas/posteda-bench)
at commit `51884e5f20e6e199219cec87c1c779a3dfab95bc` and the corresponding
[paper](https://arxiv.org/abs/2605.06936). The relevant concepts were explicit lower-is-better
PPA dimensions, framework-specific iteration semantics, dispatch-based accounting, and retaining
the last valid result after a dispatched failure.

### E-002: credential-free contract tests

The ordinary tests construct fake transports, launchers, workers, and scheduler processes. They
verify all of the following without a Synopsys installation, network, benchmark corpus, or
credential:

- the agent-feedback profile is rejected unless it binds a disposable worker contract;
- the launcher executable, loaded Python source trees, and sanitized isolation contract are
  hash-bound and rechecked inside the worker;
- a cache hit counts as a PPA action but not as a synthesis execution;
- an error before dispatch consumes no execution, while timeout or failure after dispatch does;
- each uncached dispatched request creates exactly one scheduler job;
- success, candidate rejection, timeout, and infrastructure failure require a cleanup receipt;
- the response contains structured candidate metrics but no reports, netlist, raw diagnostics,
  stdout, stderr, scheduler job identifier, PDK path, license value, or reference metric;
- the historical v1 open-feedback ledger and six-action registry remain compatible.

### E-003: real disposable-worker qualification

Two reference candidates and two deliberately invalid candidates were sent through the final fixed
MCP transport and disposable LSF worker path. All four scheduler jobs reached `DONE`; an independent
post-run check found no child workspace under the bounded worker root.

| Task | Reference | Invalid syntax | Metric presence | Returned artifacts |
| --- | --- | --- | --- | --- |
| `counter_12_agent_eval_v1` | Passed | `compile_failed` | area, delay, WNS, power | None |
| `up_down_counter_agent_eval_v1` | Passed | `compile_failed` | area, delay, WNS, power | None |

The frozen client-profile hashes were
`11cd4581db96e2251c9487d1fad0b1225376913118b14fe25ac5c0bbc68a7457` for `counter_12` and
`4c7116516284b4f408a41dc3ada0f2ef584ab695be685c5513dd064d19eeaf21` for `up_down_counter`.
Their resolved toolchain hashes were respectively
`6c344a240d083da16ea812bbaca0ab7e7c547e2938090e84436355432d182f8f` and
`731837351a9ee70e41929c47fb24031878bd6e765aa5b1ddcb13d427d0cc18d8`.
These identities partition results; metrics from the two profiles or from open Yosys/OpenSTA are
not mutually rankable.

### E-004: disclosure and cleanup inspection

The returned worker envelopes were checked for artifacts, raw output, diagnostics, commercial
paths, license material, scheduler job identifiers, and reference information. Only candidate
metrics, units, sanitized status/category, contract identity, duration, and a completed cleanup
receipt crossed the worker boundary. The raw scheduler identifier is represented only by a
one-way hash inside the verifier control plane and is not included in the AgentEval observation.

An earlier pre-final qualification attempt exposed a cleanup race: LSF could write its scheduler
error file while the launcher removed the same per-run directory. That attempt failed closed and
was not accepted as qualification evidence. The final launcher sends scheduler stdout/stderr to
`/dev/null`, restricts deletion to the exact dedicated root and generated prefix, retries bounded
cleanup, and waits for one second of stable absence before signing the receipt. The one identified
stale temporary directory was checked for active workers, removed, and the final four-job run plus
independent zero-child check then passed.

## Findings

### F-001: isolated commercial feedback is eligible for explicit opt-in

Evidence E-002 through E-004 supports enabling `synopsys.dc.mcp` as agent-visible PPA only when
resolution returns the exact v2 disposable-worker contract. The normal final candidate/reference
DC/MCP mode remains a distinct trusted verifier-control-plane path.

### F-002: iteration accounting is now unambiguous

Evidence E-001 and E-002 supports recording both PPA tool actions and dispatched synthesis
executions. Repeating an identical candidate/profile can reuse cached metrics but still consumes a
tool action. A failure after dispatch consumes an execution, and the last valid metric observation
is retained for audit. VeriGym deliberately retains its default three and hard maximum eight
executions rather than copying another benchmark's budget.

### F-003: LSF is not a kernel security boundary

Evidence E-003 establishes one-job lifecycle and workspace cleanup, not VM-grade containment.
Scheduler policy, host kernel, site filesystem permissions, the fixed launcher, MCP server, DC,
and license infrastructure remain in the trusted computing base. Deployments that require stronger
tenant separation must select a separate VM/container worker contract and qualify it independently.

## Control path

The qualified path is:

1. `run_public_test("compile")` passes for the latest candidate revision.
2. `run_public_test("ppa")` checks the candidate/profile cache and execution allowance.
3. The verifier control plane sends bounded RTL to the fixed, hash-checked MCP transport.
4. The MCP server invokes its fixed no-argument, hash-checked launcher.
5. The launcher rechecks code/isolation identity, stages one request, and dispatches one bounded
   LSF job.
6. The inner worker rechecks the identity, runs one DC synthesis request, and deletes its private
   workspace.
7. A strict envelope returns candidate metrics plus a completed cleanup receipt.
8. AgentEval emits only sanitized metric semantics, values, units, identities, budget state, and
   last-valid status.

Steps 1-2 are covered by E-002, steps 3-7 by E-002 through E-004, and step 8 by E-002 and E-004.
Any hash mismatch, missing cleanup receipt, forbidden output, malformed envelope, or unsupported
worker contract fails closed before the result becomes an agent observation.

## Reproduction boundary

Credential-free verification is reproducible with:

```bash
pytest
(cd integrations/verigym-synopsys && pytest && mypy src)
ruff check .
ruff format --check .
mypy src
```

Real commercial reproduction additionally requires authorized site profiles, licensed Synopsys
tools, the exact PDK/library and SDC assets, an approved fixed transport, and an approved disposable
worker launcher. It therefore remains an explicit operator action and is never part of ordinary
`pytest`.

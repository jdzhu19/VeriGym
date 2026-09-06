# RTLLM L2 batch-one qualification v1

Date: 2026-09-01

Status: passed. This is zero-model qualification of an independently authored public functional
projection for three frozen RTLLM tasks. It is not a model campaign, native RTLLM score, PPA
qualification, or evidence that the remaining RTLLM tasks have L2 coverage.

## Scope and selection

The new variant is `v2-agent-eval-functional-l2-batch1-v1`, with task IDs of the form
`rtllm/v2-agent-eval-functional-l2-batch1-v1/<task-name>`. It contains:

- `Arithmetic/Adder/adder_pipe_64bit`;
- `Memory/Shifter/LFSR`;
- `Miscellaneous/Others/serial2parallel`.

The source checkout remained frozen at commit
`41b26896e33b536940116a975626455eed3de65e`. Its 50-task, 207-file inventory hashes are unchanged.
These three tasks were selected from the preceding 12-task L1 Codex pilot because each reached a
typed `finish`, passed candidate-only public compilation, and was then rejected by the hidden
functional verifier. No no-finish episode was treated as a functional failure or used for this
promotion decision.

The variant records `gym_qualification_level=L2_functional_smoke`, `diagnostic_only=true`, and
`benchmark_score_claimed=false`. PPA is explicitly disabled in both task scoring and the AgentEval
tool contract. This stage invoked neither Yosys/OpenSTA nor VCS/Design Compiler.

## Public contracts

Each task has one repository-relative candidate file, one independently authored public smoke,
and its original verifier-only hidden testbench. The public smoke was derived from the upstream
prompt and reference contract without copying hidden vectors, expected-output tables, or pass/fail
logic.

| Task | Public coverage | Public smoke SHA-256 |
| --- | --- | --- |
| `adder_pipe_64bit` | 65-bit sum/carry, back-to-back enables, bubbles, reset, four-edge validity alignment | `88adcd3f90593f9666ae41ac0da44f375f102f07e9446c077a3039a135783c83` |
| `LFSR` | zero reset, left shift, XNOR taps `out[3:2]`, sequence evolution, mid-sequence reset | `9ce56236593435d22094b1389ccf8e96ffcaa1303b4671bad9ac3ecce5f513c6` |
| `serial2parallel` | MSB-first order, partial-frame discard, valid latency/pulse, multiple words, reset | `c2f61e7deb14b929a3aa21e22cb018c06805317ea8764cb700970da1ed850361` |

The separately appended projection notes resolve prompt ambiguity without changing the upstream
prompt bytes. They define the adder's fourth-edge result alignment and the serial converter's
eight-consecutive-valid framing and following-cycle output pulse.

| Task | Frozen task manifest hash | Public contract hash | Projection-note hash |
| --- | --- | --- | --- |
| `adder_pipe_64bit` | `df61640d471a1c3d4773ed4f2050ca56fc296497448b75fbb6ed434398cd8ad8` | `e3bb4d0923fa6bb26cce0d623f1ae86db582bbe8166bb9abb532874366c12ec1` | `2061723fa56cd183d609cee54a0a5668d2271a2724e908a434689f3744f9ec9c` |
| `LFSR` | `5588da2161283ee3fa26ccc675c2cc4ec51ccb1cd7d7645e300a7f93f6ceba9a` | `304cdcd25093c3c63dbb7a7b9e1a7c35c5711ae8c28093633c98cba365a173ec` | `827a91329153257f738a772610dbe7e8757c6596ea284327c9b3453000cb0144` |
| `serial2parallel` | `504828d61820f47dcf7359c2b0738db6e84d5da851c21c8707924e43ea1bc76b` | `3f226f354a55f57565f1c03591b11104b9cf049a3576c832beb7cb5730e5124a` | `e2dc7d233448eb9c05a5c442667e4e384767c974117e76f84975672761914e99` |

Public assets are mounted through the hash-bound read-only public-test mount. They are not
editable candidate files. Hidden testbenches remain outside the visible workspace and are staged
only after typed `finish`; all three tasks carry `verification_requires_final_submission=true`.

## Qualification result

Qualification used `verigym/open-rtl-tools:iverilog12-yosys067-opensta310`, resolved as
`sha256:e33186333e904f120cad7651c56c45be6715df1cc9745a93b137d82b9a5a05f1`.
Every short-lived container used networking disabled, a non-root user, a read-only root
filesystem, dropped capabilities, and bounded resources.

For each task, the upstream reference had to pass both the public smoke and original hidden
verifier. Four independently authored negative controls had to be rejected by both paths:
stuck-zero, reset error, protocol/latency error, and task-specific functional error.

| Check | Cases | Result |
| --- | ---: | --- |
| Reference public smoke | 3 | passed |
| Reference hidden verifier | 3 | passed |
| Four known-bad categories, public smoke | 12 | rejected |
| Four known-bad categories, hidden verifier | 12 | rejected |

Each final task-specific qualification run made no model call and used no automatic candidate
retry. During development, two initially weaker protocol controls were public-rejected but
hidden-accepted: an adder with combinational result/enable and an LFSR updating on the falling
edge. The final controls use a non-retained adder result and a half-rate LFSR respectively,
preserving the error category while making the error observable to both frozen paths. These were
qualification-code revisions, not repeated model episodes. The hidden testbenches were not
modified.

Ordinary integration checks passed with 53 tests and nine opted-out external/commercial cases;
Ruff, format checking, and strict mypy passed for the integration. The repository-wide ordinary
test run passed 1,231 tests with one real-Codex opt-in skip and 52 deselected external cases.

## Interpretation

The three tasks now provide useful repeatable functional feedback before final submission, while
retaining a separately gated hidden verdict. This closes the specific L1 feedback gap observed in
the pilot. It does not imply that the remaining 41 tasks without an existing functional variant
are L2-ready: each still needs an independent public smoke, four-category negative-control
qualification, and a new frozen variant or batch identity.

PPA remains a separate L3/L4 stage. Enabling it later requires task-specific synthesis-top and
clock qualification under a distinct profile and variant identity; L2 qualification does not
silently authorize either open or commercial PPA.

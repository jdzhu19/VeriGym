# Harder unseen Codex RTL multi-episode diagnostic v4

## Scope

This audit records a diagnostics-only comparison over four VerilogEval tasks that were not used in
the preceding 14-slot strength diagnostic. It is not a benchmark score. The approved replacement
design is four tasks by three independent episodes per cell, so the completed matrix contains 12
processes per cell and 48 processes in total; it must not be described as a new 14-run campaign.

The frozen v5 tasks were `Prob140_fsm_hdlc`, `Prob144_conwaylife`, `Prob153_gshare`, and
`Prob155_lemmings4`. `Prob156_review2015_fancytimer` was excluded at zero-model qualification
because its official reference emitted the native timeout marker after 200,000 samples with zero
mismatches. The verifier timeout was not weakened to admit it.

Every episode used:

- VerilogEval variant `v2-spec-to-rtl-agent-eval-functional-v5`;
- one Codex CLI process, zero automatic retries, and one requested-only identity observation;
- at most 40 typed tool calls, 20 patch calls, and 300 seconds of task wall time;
- public compile plus a specification-derived functional smoke during iteration;
- a terminal, model-invisible hidden verifier execution at most once per verifier node;
- Codex CLI `0.147.0`, prompt hash
  `14635a854a76a46c8260572cf3a303c0672da77e8b52cdae09427582e79b8ee9`, and tool-policy
  fingerprint `6a0cf3b44d0bdb1b6ba2a016607db639e857af8979389ece947c8bea55415ef4`.

The three `gpt-5.4-mini` cells form the same-model reasoning comparison. The `mini-low`,
`mini-high`, and `full-xhigh` cells form the broader strength comparison. Model and reasoning
support were frozen after checking the official [GPT-5.4 mini][gpt54mini] and [GPT-5.4][gpt54]
documentation. Codex CLI does not expose an auditable provider seed here: episode indices 0, 1,
and 2 identify independent VeriGym processes but are not claimed as provider seeds.

## Completed v5 matrix

| Cell | Model / reasoning | Resolved | Typed finish | Visible failed-to-passed repair | Timeout | Policy / infrastructure | Wilson 95% |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `mini-low` | `gpt-5.4-mini` / `low` | 8/12 | 8/12 | 3 | 0 | 0 / 0 | 0.391–0.862 |
| `mini-medium` | `gpt-5.4-mini` / `medium` | 7/12 | 10/12 | 4 | 2 | 0 / 0 | 0.320–0.807 |
| `mini-high` | `gpt-5.4-mini` / `high` | 9/12 | 10/12 | 4 | 2 | 0 / 0 | 0.468–0.911 |
| `full-xhigh` | `gpt-5.4` / `xhigh` | 12/12 | 12/12 | 6 | 0 | 0 / 0 | 0.758–1.000 |

Task-level resolved counts were:

| Task | Mini low | Mini medium | Mini high | Full xhigh |
| --- | ---: | ---: | ---: | ---: |
| `Prob140_fsm_hdlc` | 3/3 | 3/3 | 3/3 | 3/3 |
| `Prob144_conwaylife` | 3/3 | 3/3 | 3/3 | 3/3 |
| `Prob153_gshare` | 2/3 | 1/3 | 2/3 | 3/3 |
| `Prob155_lemmings4` | 0/3 | 0/3 | 1/3 | 3/3 |

All 48 processes have one valid identity observation, zero retries, and no policy or infrastructure
failure. Provider usage is complete for 44/48; the four incomplete records are the contained
`mini-medium`/`mini-high` timeouts. Offline replay, exact leakage scanning, and redaction audits
passed independently for all four cells. Each summary records `diagnostic_only=true` and
`benchmark_score_claimed=false`.

The same-model mini results are not monotonic: medium resolved one fewer episode than low, while
high resolved one more. The task-level results and wide, overlapping Wilson intervals show why a
single small cell cannot establish a reasoning-effort ranking. In this fixed diagnostic, however,
full GPT-5.4/xhigh resolved all 12 episodes, including all gshare and Lemmings episodes, while the
three mini cells did not.

## Direct multi-turn evidence

The matrix contains 17 directly attested public `test failed -> patch -> re-test passed` loops.
Sixteen of those terminal candidates also passed the one-shot hidden verifier. The exception is
`mini-medium` Lemmings episode 2: it repaired the v5 public smoke and reached typed `finish`, but
the hidden verifier rejected it.

The repair distribution is informative:

- all four cells repaired all three FSM HDLC episodes after an initial public failure;
- full GPT-5.4/xhigh additionally repaired and resolved all three Lemmings episodes;
- mini/high repaired and resolved one Lemmings episode;
- mini/medium repaired one Lemmings episode publicly, but it remained hidden-rejected.

Thus the useful multi-turn unit is RTL-functional interaction, not merely multiple chat messages:
read and locate, patch a candidate, observe public compile/functional feedback, patch again,
revalidate, typed `finish`, then terminal hidden verification. The full/xhigh 12/12 result still
contains six repair loops, so the visible feedback is materially used even by the strongest cell.

This interaction shape is similar to [PostEDA-Bench][posteda], whose agents edit design inputs and
rerun DRC/OpenROAD flows over multiple iterations and independent attempts. VeriGym differs by
using a typed repository protocol, bounded public feedback, frozen identity evidence, redacted
artifacts, and a model-invisible terminal hidden verifier. The upstream [VerilogEval][verilogeval]
repository remains the source-format and native-regression reference; it documents the v2
specification-to-RTL layout and Icarus Verilog 12 environment used here.

## Failure and Gym attribution

The v5 failures include both model limitations and two public-smoke coverage gaps:

- Mini/low produced four contained model failures before typed `finish`: one gshare and three
  Lemmings candidates did not satisfy the visible v5 feedback. Mini/medium and mini/high each used
  the full wall-time budget on two Lemmings episodes. These failures had actionable public errors
  and are model/time-budget outcomes, not hidden-only Gym failures.
- Three mini gshare candidates passed public feedback but failed hidden verification. All three
  reset the pattern-history table to strongly-not-taken `00`, although the public specification
  requires weakly-not-taken `01`. The v5 smoke observed only the prediction bit and did not
  distinguish those states. This was both a model error and a Gym coverage gap.
- The hidden-rejected mini/medium Lemmings candidate used a wrapping 5-bit fall counter. It could
  survive after a sufficiently long fall even though the public specification states that there is
  no upper limit on falling distance. The v5 smoke checked the 20/21-cycle boundary but not a
  post-wrap long fall. This was also both a model error and a Gym coverage gap.

The earlier v4 Lemmings smoke gap was closed before this matrix by v5 checks for irrelevant-side
bumps and exact 20/21-cycle splatter behavior. The two gaps discovered by the completed v5 matrix
were closed afterward without mutating v5 evidence:

- functional v6 / adapter `0.7.0` adds a gshare reset-state discrimination check: one taken
  training update from reset must immediately cross into a taken prediction;
- functional v7 / adapter `0.8.0` inherits v6 and adds a 40-cycle Lemmings fall that must splatter,
  detecting finite-counter wraparound.

A zero-model, network-none v7 qualification passed:

- 4/4 official references passed public feedback and hidden verification;
- 4/4 trivial known-bad candidates were publicly rejected;
- the three observed gshare hidden rejections and the observed Lemmings long-fall rejection were
  all rejected publicly;
- one correct full/xhigh gshare candidate and one correct full/xhigh Lemmings candidate continued
  to pass publicly.

No v7 model campaign was started automatically. Future cells must use a newly frozen campaign and
agent/suite identity; v7 outcomes must not be spliced into the immutable v5 comparison.

## Interruption recovery

An external session interruption occurred after the first nine mini/medium processes completed.
The tenth slot had only `episode_started` and initial observation events: no Codex process artifact,
identity observation, candidate hash, feedback evaluation, or scorecard existed. A strict resume
path now:

- accepts only a contiguous, frozen completed prefix plus at most one authorized-but-proven-
  unstarted next slot;
- archives pre-agent staging evidence and records `model_retry_performed=false`;
- rejects any pending slot with process evidence, identity evidence, a scorecard, unexpected trace
  events, or a run/ledger gap;
- compares normalized runtime identity while retaining image, isolation, resource, and tool
  identities, excluding lifecycle-only container/session IDs;
- creates broker roots for new campaigns but only reuses already validated roots on resume.

The resumed mini/medium cell therefore contains exactly 12 model processes, not 13, and its
authorization ledger still records zero retries.

## Interpretation

The previous 14-slot single-episode diagnostic was too easy to distinguish strength. This harder,
multi-episode matrix provides better evidence: full GPT-5.4/xhigh completed 12/12 while the mini
cells varied from 7/12 to 9/12, and all cells exhibited real feedback-driven repair. Nevertheless,
four tasks and three independent episodes per task remain too small for a benchmark score or a
precise reasoning-effort ranking.

V7 closes every confirmed public-spec coverage gap found in the v5 evidence; this does not prove
that future public feedback is exhaustive or that the Gym cannot dominate a different sample. The
appropriate discipline is the one used here: preserve the completed revision, investigate every
public-pass/hidden-fail candidate against the public specification, freeze a new revision for any
confirmed coverage gap, qualify it with reference/known-bad/differential checks, and use fresh
unseen cells for the next comparison.

[gpt54mini]: https://developers.openai.com/api/docs/models/gpt-5.4-mini
[gpt54]: https://developers.openai.com/api/docs/models/gpt-5.4
[posteda]: https://github.com/pengjas/posteda-bench
[verilogeval]: https://github.com/NVlabs/verilog-eval

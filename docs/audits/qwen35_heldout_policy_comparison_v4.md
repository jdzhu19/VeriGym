# Qwen3.5 Held-Out Policy Comparison

## Scope

This audit freezes 12 VerilogEval V2 code-completion tasks after policy-v4 was registered. The
split excludes all prior training tasks and is permanently marked ineligible for training. Each
policy used the same seed (`20260809`), temperature (`1.0`), top-p (`0.95`), two samples per task,
96 planning tokens, and 512 solution tokens.

The split manifest hash is
`c8319e374c684ed93167112adb34bf92d41f4cd5be764283e2318e349489a936`. Its comparison report hash
is `8ec32d9f14ff8721b6035ee286ff8bffdc503163c51805347d1907100dff1219`.

## Results

| Policy | Policy version hash | Compile rate | Resolved rate | Task pass@2 |
| --- | --- | ---: | ---: | ---: |
| v2 | `71104d618ce36cde7693190e3c0913cd2b78d9f6d00bdaef9ffdcd7b140fff2c` | 70.8% | 54.2% | 66.7% |
| v3 | `3cfc23e0443ddfcc588d154380483d2ab96fb0fbc982623740286636ac03f3eb` | 70.8% | 50.0% | 58.3% |
| v4 | `085d2ead277c701ec0ffd28f7c9f2eacd6e97ce39485bf2b5bb69b06b746eefb` | 66.7% | 45.8% | 58.3% |

All 72 samples produced valid verifier outcomes; the infrastructure-invalid count was zero. The
result does not show held-out improvement from v2 to v4. This is useful negative evidence: the two
small online updates were interoperability checks, not a convergence claim.

## Reproduction boundary

The external campaign directory contains the frozen public inputs, task split, per-policy
evaluation manifests, scorecards, and `heldout-comparison.json`. Hidden testbenches and reference
solutions were never passed to the policy, and held-out samples must not be reused for SFT or RL.

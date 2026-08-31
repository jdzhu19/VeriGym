# OpenHands v34 provider canary stopped before provider execution

## Result

The one authorized execution of `openhands-hwe-v34-provider-canary-v1` stopped fail closed during
the zero-call control-plane and Docker preflight. No provider episode or request started, neither
scheduled task was attempted, and PR-3204 was not reached.

The authorization merged as PR #45 at commit
`74ee723780423e5ef9a2c052573561c0a959970d`. The command's frozen tiktoken 0.7.0 overlay was
clarified before execution by PR #46; its merge commit and the exact executed source commit are
`0e538ee629fb06009a9aa1918324875d770ef3c4`. Both merge commits passed all eight required
`main` Actions classes before the opt-in was enabled.

The immutable output is
`/data/jzhu484/Agent/experiments/openhands-hwe-v34-provider-canary-v1`. Its final report records:

- `status=stopped_infrastructure_invalid` and
  `failure_reason=zero_call_preflight:ValueError`;
- zero provider episodes, calls, retries and task attempts;
- `canary_passed=false` and `formal_collection_allowed=false`;
- an empty held-out task list; and
- `formal_collection_started=false`, `collection_started=false`, `training_started=false`,
  `production_training_ready=false` and `benchmark_score_claimed=false`.

This is an infrastructure-invalid result, not a benchmark, protocol or trajectory rejection. The
v34 identity and output are sealed and must not be retried or relabelled.

## Artifact chain and security scan

The complete four-file evidence directory hash is
`fd529806fa40590de65bfdd09cd0428399923a3f9f581c5e39533f003a11cf5a`. The files are:

- `canary-report.json` and `canary-progress.json`: byte-identical, 3,086 bytes each, file SHA-256
  `6cd35014c97a65c30411652c577799a99d9213505f81a843ae41a587ca159c00`, embedded report hash
  `e684f04fe14184df0ee47ec48b225dfe965fb48da2c2fc54c898f1a8383af234`;
- `agent-version.json`: 2,121 bytes, file SHA-256
  `c26666e1d00a11c6c623cf1064bd035dcd0bb0b782e06f4c032d0cd930464795`, validated agent-version
  hash `2bfd274afb9e0bc7447719e8cd47575ea25b19ee1a9f266bab9c58ee2a5b22b9`; and
- `contract-receipt.json`: 2,435 bytes, file SHA-256
  `b1a4df4e8b9ce9211b69f0a78dbdb34f56f2c52e03ef94d971259eccc24e81f4`, canonical receipt hash
  `da07395d663dbc20b40f8f19ccea08812f4ab1481499c906acfb90d9207e1c0c`.

The report, contract receipt and agent version all recompute and validate exactly. No symlink and
no v34-managed container remains. An independent in-memory context-aware scan covered all four
files and 10,728 bytes. It included the live provider endpoint, provider credential and active
proxy values without printing, persisting or hashing them. The scan passed with zero hard secret
findings and zero scanner errors; its content-free report hash is
`3bb6a975a3e7520a1a2c0009ee4ee2b2f5daf4508f1b40037e237194ce8bdc6d`.

## Offline root-cause classification

The sealed report deliberately retains only the exception type. The exact preflight order first
calls `_configured_control_root()` and `_configured_mcp_pythonpath()` before constructing or
preparing either Docker runtime. At execution time, read-only environment inspection found both
`VERIGYM_OPENHANDS_BROKER_ROOT` and `VERIGYM_OPENHANDS_MCP_PYTHONPATH` absent. Each corresponding
function raises `ValueError` when its variable is absent. This deterministically explains the
sealed exception class before the Docker loop; it is an offline classification and is not
retrofitted into the v34 artifact.

The integration README already states that real HWE runs require a short broker root and an
explicit MCP Python path. The v34 authorization checked provider and package variables but omitted
these two controller-only prerequisites from its exact command and preflight assertions. No
network, command image, provider or task behavior contributed to this stop.

## Successor requirement

Any successor must use the next unused identity and bind this stopped evidence. Before opt-in it
must validate a short real non-symlink broker directory and an absolute, unique, bounded MCP Python
path whose entries exist and are non-symlinks. Its exact authorized command must set both values,
and its zero-call preflight should emit a content-free stage and exception classification if it
stops. The fixed tiktoken 0.7.0 overlay, v33 command-image evidence, two-task order, budgets, six
planes, exact-64K gate and zero-retry policy remain unchanged.

This audit authorizes no successor, provider call, formal collection, SFT, GPU work or held-out
loading. A new identity, authorization PR and all eight checks are required first; later planned
version numbers shift accordingly.

# OpenHands v47 provider canary stopped before output

Date: 2026-09-01

Status: infrastructure-invalid pre-output stop; v47 frozen with zero provider calls and zero task
attempts.

## Authorized boundary

V47 authorization PR [#75](https://github.com/jdzhu19/VeriGym/pull/75) merged at
`ee45d60171e96f77dcbbbbbe8a3402b745275f5a`. Its push and pull-request workflow runs passed all
eight required job classes, followed by successful post-merge main run
[33499293769](https://github.com/jdzhu19/VeriGym/actions/runs/33499293769). The checked-in
authorization hash was
`bdfb2e6a2f3e7e5ee465e011f73fa50c32f24d0c4d6fab76490b52326dbeab4a`.

Immediately before execution, read-only validation passed for the clean merged commit, all sealed
predecessor trees and hashes, both public source locks, Qwen tokenizer/model lock, fixed dependency
versions, both exact Docker images, Docker root, byte/inode headroom, empty broker and output, and
provider-environment presence without printing, persisting, or hashing either value.

## Failure and accounting

The sole v47 invocation supplied the wrong value for `--stopped-v37-canary-root`: it selected a
nonexistent sibling name instead of the sealed v37 `-pre-output-stop-v1` evidence root. The runner
failed closed in `_safe_directory` while resolving that predecessor, before tokenizer loading,
output creation, zero-call runtime preflight, provider-client construction, or task loading. This
was a launch-argument error, not a benchmark verifier or model result.

The authorized v47 output root was never created. The broker remained empty, no command-runtime
container was created, and the process exited. Provider episodes, provider calls, model processes,
task attempts, PR-2802 starts, and PR-3204 starts are all zero. Consequently both benchmark tasks
remain provider-unattempted, but v47 itself is permanently frozen and may not be rerun in place.

`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`. No trajectory, decision record, SFT input, GPU job, held-out
task, or benchmark score was produced.

## Frozen evidence

The content-free stop evidence is stored outside Git at
`/data/jzhu484/Agent/experiments/openhands-hwe-v47-provider-canary-pre-output-stop-v1`. It contains
one regular `0600` file under a `0700` directory, with no symlink or special file:

- evidence tree hash:
  `decd32eef21aae7b56662aba78e6ae19007b994125d75b5ae9bea2e5072c7482`;
- `stop-receipt.json` SHA-256:
  `ed800f5c027211278b89cae74b030ca7d7e066679baa282b54e75c0d29f82072`;
- canonical receipt hash:
  `f267585dae966952fe72645bd277127745f4f8a0eb6a034ec19ceb01ded3c654`.

The receipt persists the failed argument name and normalized category, but no actual or expected
path value, raw exception, command line, provider/proxy value, or raw subprocess output. A
context-aware scan compared the active provider/proxy-sensitive values and known host roots only
in memory. It scanned one 1,705-byte file and passed with zero hard-secret leaks and zero scanner
errors; report hash
`e84c293e088b104ae6ed191ad7ae14112168ad845c72f4b4186e18b1b2bcc01b`. Suspected values were
neither exported nor hashed.

Two audit helper probes used obsolete convenience attribute names after independently completing
the same passing scan. Both stopped after scanning, wrote nothing, and did not alter the sealed
receipt. The final schema-aware aggregation used `hard_secret_leak_count` and
`scanner_error_count` and reproduced the report hash above.

## Successor boundary

V48 is the minimum successor version. It may propose the same still-unattempted PR-2802 then
PR-3204 schedule only under a new campaign, agent, opt-in, broker, output, report, and authorization
identity that binds this exact stop receipt, merged audit, and green post-merge main run. The
correct sealed v37 evidence root must be fixed in the reviewed command and covered by regression
tests. V48 is not authorized by this audit; provider access remains off until that successor
authorization independently merges and passes all eight main checks.

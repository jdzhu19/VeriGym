# OpenHands v42 PR-2589 canary-image materialization passed

Date: 2026-09-01

Status: sealed zero-provider materialization result; provider execution remains unauthorized.

## Result

The single authorized execution of
`openhands-hwe-v42-pr2589-canary-materialization-v1` completed successfully from clean merged
`main` commit `a694a9c01112b103ecb1067ef13a1351e3c3bc31`. It built, independently scanned,
and locked one Codex-free PR-2589 command image, then sealed the static v22 successor canary
contract in the fixed order PR-2589 training followed by PR-3204 validation. It made zero provider
calls and did not execute either canary task.

Authorization PR [#65](https://github.com/jdzhu19/VeriGym/pull/65) merged before execution. Its
post-merge main Actions run
[33480968906](https://github.com/jdzhu19/VeriGym/actions/runs/33480968906) passed all eight required
job classes: ordinary Python 3.11, 3.12, and 3.13; quality; package; reproducible build; OpenHands
Python 3.12; and Docker external-agent zero-model security.

Full evidence remains outside Git at
`/data/jzhu484/Agent/experiments/openhands-hwe-v42-pr2589-canary-materialization-v1`.
It contains exactly 7 regular files and 17,839 bytes, all with mode `0600`, under mode `0700`
directories, with no symlinks. The complete evidence-tree hash is
`9c1e70a80e0da4368d2fcefa899c949c8729c70c7cac6ee63251da9536f33998`.

## Execution-time gate and terminal state

Immediately before the unique invocation, `HEAD` and `origin/main` both resolved to the merged
authorization commit. The output did not exist. Independent recomputation matched the complete
v33 tree, complete v41 tree, selected v33 PR-3204 binding, sealed v41 failure, PR-2589 legacy lock,
and official ripgrep archive and binary hashes. The required local verifier and validation command
images existed by digest. Docker root `/data/docker`, the control root, scratch root, and output
parent all exceeded their byte and inode thresholds.

The execution-time absolute headroom gate then passed inside the runner before the image build. Its
canonical preflight hash is `0afd5fccb4dd1802161c8ebf29f60d82548a692229353f8e55a4f15dc301da66`
and its file SHA-256 is
`7ec3d2dc76eb7c87ad5d7c9b413aa3f388a7a665ed5305bd46ba66560b58890a`. All observations
satisfied the frozen conservative six-image thresholds. The receipt persisted neither resolved
host paths nor raw command output.

The final `materialization-progress.json` has canonical progress hash
`730714bd3f29a7e0d5346350110f2a241c35c913ceacae8516419a2a1813e837` and file SHA-256
`a12d462a8f3ec36c4b5a2d5fcc294bdc590c95ef4d3671652c712ba1c80a57c3`. Independent
recomputation matched both. Its status is `completed_v22_canary_contract_materialized`; its
provider episode, provider call, and model process counts are all zero.

## PR-2589 command-image lock

The materializer produced command image
`sha256:5632d0b3eac6086244a976fb0def3d49e765de2e8af2cdbc208161991db0fbc1`, lock
`c4034d47e2c1fd976755b2425f945da72c19cb4f4f514041e3c1960d262655a6`, and v2 security
scan `3ef950839998cbbbad67e181e5e95315dd962605990c575e33eb47713b9582dd`. The lock file
SHA-256 is `c8a4a7a671a2adbfe6cb2eda89264fbd2bd999e09a4eabea76fa3c183cf33d76`, the image receipt
file SHA-256 is `7066120c782b7016ccd44b6cfcf28e8a86b749b06ebaf7748bc4b0e05f353af6`, and the
security-scan file SHA-256 is
`e3eaaf29e03e28937a7eea5ba91da2fd93e707e2acaef75b4445b26d9a9870db`.

The lock preserves the frozen PR-2589 task, source, and verifier identities from the qualified
legacy lock. Dockerfile `RUN` networking and runtime networking are both `none`. The v2 scanner
confirmed a read-only root, non-root UID/GID, cap-drop `ALL`, no-new-privileges, bounded resources,
a private IPC/PID boundary, a single visible workspace mount, and the exact allowlisted toolchain.
It found no Codex executable or dependency, provider credential, hidden asset, verifier payload,
reference patch, or undeclared volume. The exact image environment is the frozen five-variable
command environment. Temporary scan containers and workspaces were removed, and no container
remains bound to the derived image.

PR-2589 has no provider attempt under this or any predecessor canary identity. This result does not
relabel or reconstruct a historical trajectory. The command image is new only to the v43 successor
canary identity. A future successful v43 PR-2589 canary trajectory may be imported without formal
re-execution; an ordinary v43 failure instead permanently consumes PR-2589 for this purpose and
requires another unused formal task.

## Catalog, contract, and independent artifact scan

The two-task command-image catalog has canonical hash
`e8deaec6106dd7a07783be23e72f1810a28df04657fcb869c37290c7ebfd287e` and file SHA-256
`b11a4561891e4db5b45a39919ff1162d9a9833b90809aead9f28a552048471fe`. It binds the new
PR-2589 training image and the sealed, still-unstarted v33 PR-3204 validation image. The command
image IDs are distinct. Both use `episode_container_exec_v1`, network `none`, and credential-free
command containers.

The v43 canary contract has canonical hash
`d05128e4d4b7553018a9c6828165239f345e1c0b932150058e32b7a25e64321b` and file SHA-256
`7fe608d5944117b9a115d6e13640a284539c54749fbc1db6ed4e94ec597269e8`. It fixes PR-2589
training before PR-3204 validation, seed 494, sample index 10, DeepSeek v4 Flash, OpenHands SDK
1.42.1, LiteLLM 1.93.0, tiktoken 0.7.0, transformers 4.57.6, NumPy 2.2.6, Pillow 12.1.1,
temperature zero, 64 provider calls, 1,000,000 cumulative provider tokens, a 65,536-token context,
2,048 output tokens, zero provider retries, zero whole-episode retries, no truncation,
first-failure stop, all six result planes, and `required_tool_atomic_shape_recovery_v22`.

An independent in-memory context-aware scan covered all 7 files and 17,839 bytes. It checked the
active provider endpoint, provider credential, active proxy values, and known repository/result/
predecessor host roots without printing, persisting, or hashing those values. It found zero exact
provider-value hits, zero hard secret leaks, and zero scanner errors under report hash
`c829e4a8cd505350b18dbad79e2cba10e1b9ba07884d94f5ca50180276e7d678`.

## Negative claims and next gate

No provider request, canary episode, command execution against a task, verifier run, trajectory,
decision record, formal collection, SFT, inference evaluation, GPU job, or held-out load occurred.
`formal_collection_allowed=false`, `formal_collection_started=false`, `collection_started=false`,
`training_started=false`, `production_training_ready=false`, `canary_executed=false`, and
`benchmark_score_claimed=false` remain fixed.

This result audit authorizes no provider call by itself. A separate append-only v43 runner and
authorization must bind this exact evidence tree, progress, catalog, contract, both command-image
locks, the frozen tokenizer, runtime identity, budget, order, and all six result planes. Only after
that authorization merges and its post-merge main run passes all eight required job classes may
the two zero-retry canary episodes execute.

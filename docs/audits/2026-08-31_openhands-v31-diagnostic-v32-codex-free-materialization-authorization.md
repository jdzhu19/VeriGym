# OpenHands v31 diagnostic and v32 Codex-free materialization authorization

## Outcome and scope

This change authorizes one zero-provider materialization under the fresh identity
`openhands-hwe-v32-codex-free-canary-materialization-v1`, after the authorization commit is merged
to `origin/main`. It may build and security-scan six task-distinct Codex-free command images and
write a successor static canary contract. It may not invoke a model provider, execute the canary,
collect a trajectory, start training, run inference evaluation, or load a held-out task.

The immutable authorization is
`configs/training/qwen35_hwe_openhands_v32_codex_free_canary_materialization_v1.json`. The runner
requires the explicit opt-in environment variable
`VERIGYM_MATERIALIZE_OPENHANDS_HWE_V32_CODEX_FREE_CANARY=1`; validates the authorization hash,
sealed v29/v30 evidence, six legacy image locks, and ripgrep release hashes; and accepts only a
clean `HEAD == origin/main` checkout.

## Why v31 is stopped

During a negative pre-merge test, the first implementation used only `git diff --quiet` and
`git diff --cached --quiet`. Those commands cover tracked changes but did not reject the new,
untracked materializer and authorization files. The test therefore started the PR-2330 build when
it should have failed before output creation. The process was interrupted during sanitization and
sealed as a local diagnostic at:

`/data/jzhu484/Agent/experiments/openhands-hwe-v31-premerge-gate-diagnostic-v1`

Its terminal progress hash is
`5fe56ffedb704e528e12bc8741059c6c252e46c8c4db3fa2eb51f0d2e9915046`; the progress file SHA-256
is `4d3c690d23a1b575cc902467586236b10776753e4e64c0b13d5a9c6a0272ccb9`. It recorded zero provider
calls, zero model processes, no canary execution, no collection, no training, and no held-out task.
The incomplete unsanitized image ID was
`sha256:191a9603e4d37cfb4d822ead20b8181f43fbdfb9f578b5928e1eb80c0aaea4c8`; its tag and one created
sanitizer container were removed after recording their exact identities. Neither the v31 identity
nor its discarded tag namespace may be reused. The content-addressed image itself was not deleted:
two pre-existing generic PR-2330 command-image tags already referenced the same digest. Those
historical tags were left untouched and are not v31 or v32 evidence.

The fix follows the documented distinction between Git's tracked-content diff and index file
enumeration: every execution-critical path is now required to resolve exactly through
`git ls-files --error-unmatch`, remain byte-unchanged from `HEAD`, and pass the existing whole-tree
tracked-change and `HEAD == origin/main` checks. A regression creates a temporary Git repository,
proves that an untracked runner is rejected, then proves the same runner is accepted only after it
is committed. See the official [`git diff`](https://git-scm.com/docs/git-diff) and
[`git ls-files`](https://git-scm.com/docs/git-ls-files) documentation.

## Frozen task and runtime inputs

The v28/v29 qualified public split remains unchanged and is imported without rerunning any
historical task:

- training reserve: PR-2330, PR-3226, PR-3231;
- validation reserve: PR-2989, PR-3059;
- canary validation: the already frozen PR-3204 binding.

Each task receives a distinct image in the new
`verigym/cva6-openhands-v32-command-pr-<number>:rg-15.2.0-v1` namespace. Builds and later runtime
commands use `network=none`. Security locking requires that Codex, provider credentials, hidden
assets, verifier payloads, and reference patches are absent. The command image supports both the
one-command `ephemeral_container_v1` path and the faster per-episode
`episode_container_exec_v1` path. The canary schedule remains PR-2330 then PR-3204, seed 489,
sample index 5, and the frozen v19 required-tool protocol and budgets.

The v32 materializer consumes the v29 qualification receipt instead of repeating public-task
qualification. It records the v30 zero-provider stop and never relabels or imports an old
trajectory. Any build, scan, binding, distinctness, security, or infrastructure failure stops the
one v32 attempt without retry.

## Authorized execution after merge

The one materialization output root is fixed to:

`/data/jzhu484/Agent/experiments/openhands-hwe-v32-codex-free-canary-materialization-v1`

The post-merge command is:

```bash
VERIGYM_MATERIALIZE_OPENHANDS_HWE_V32_CODEX_FREE_CANARY=1 \
python scripts/materialize_cva6_openhands_v32_codex_free_canary.py \
  --authorization configs/training/qwen35_hwe_openhands_v32_codex_free_canary_materialization_v1.json \
  --v29-root /data/jzhu484/Agent/experiments/openhands-hwe-v29-v19-canary-materialization-v1 \
  --v30-root /data/jzhu484/Agent/experiments/openhands-hwe-v30-v19-provider-canary-v1 \
  --validation-image-lock /data/jzhu484/Agent/experiments/qwen35-hwe-openhands-bounded-sft-pilot-v1/image-locks/pr-3204.json \
  --rg-binary /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl/rg \
  --rg-release-archive /data/jzhu484/Agent/datasets/tools/ripgrep/15.2.0/ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz \
  --output /data/jzhu484/Agent/experiments/openhands-hwe-v32-codex-free-canary-materialization-v1
```

The result must be committed only as a sanitized audit containing hashes, bindings, statuses, and
check results. Full image layers, source trees, legacy locks, security scan payloads, and experiment
outputs remain outside Git. A later provider canary requires a separate authorization and must not
start unless this materialization and its result audit both pass all repository protection checks.

## Verification required before execution

Pre-review credential-free results on the authorization branch are:

- v32 targeted regressions: `6 passed`; combined v19, v30, command-runtime, and v32 regressions:
  `52 passed`;
- complete OpenHands Python 3.12 zero-model suite: `313 passed`;
- ordinary credential-free repository suite: `1054 passed`, `1 skipped`, `52 deselected`;
- HWE credential-free suite: `50 passed`;
- strict mypy: core `207` files, HWE `9` files, OpenHands `30` files, and the v32 runner
  `1` file;
- tracked-source Ruff and format: `679` existing Python files plus both new Python files; Git diff
  hygiene: passed;
- real negative pre-merge gate: the untracked v32 authorization was rejected before output
  creation or Docker image creation; the v32 tag namespace remained empty;
- provider calls, verifier runs, canary episodes, collection, training, and held-out loads: zero.

The first local ordinary-suite attempt used a temporary test environment with `tiktoken 0.8.0`
and without the in-repository training-reference package. Its eight environment-caused failures
were reproduced narrowly, corrected by restoring the frozen `tiktoken 0.7.0` and installing the
local package, and then cleared (`12 passed`) before the complete passing rerun above. No source or
frozen campaign setting was changed to accommodate the environment.

The authorization PR must pass the targeted v32 regressions, the combined credential-free v19 and
command-runtime regressions, Ruff, strict mypy for the core and OpenHands integration, the ordinary
credential-free test suites, package/build checks, Docker security checks, reproducible builds,
and all eight required repository protection checks. The real materializer must be invoked once,
only after those checks merge to `origin/main`.

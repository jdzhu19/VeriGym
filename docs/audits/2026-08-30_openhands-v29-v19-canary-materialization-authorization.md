# OpenHands v29 evidence materialization for the v19 canary

## Authorization boundary

This change authorizes exactly one successor evidence-materialization run after its code pull
request is merged and all repository checks pass. The successor orchestration identity is
`openhands-hwe-v29-v19-canary-materialization-v1`; it does not replace or rewrite the stopped v19
public-qualification receipt. The agent and protocol identities remain the frozen v19 identities:

- campaign: `openhands-hwe-v19-required-tool-canary-v1`
- agent: `openhands-deepseek-v4-flash-hwe-v19-canary-v1`
- schedule: PR-2330 training, then PR-3204 validation
- seed 489, sample index 5

The authorized run may build and scan five task-keyed agent images, seal the 3-training/2-validation
reserve receipt, and materialize the static v19 canary contract. It may not invoke a provider,
execute the canary, load held-out tasks, start collection, or start training. The authorization
hash is `7bc664e303c44cb7bc522c3c3963b4ea0ce2e9fe09b9318dbde19317265ea63a`.

## Frozen evidence and source catalog

The runner consumes only the passed v28 qualification progress:

- canonical progress hash:
  `c631e93fd7c002dc47aff45894d24701baabbad599da405b57d5516f8d6ce119`
- progress file SHA-256:
  `f44e11ae449d9c6836c3a86b112492a65b03446039a5d8a38c2b9403231abc70`
- result-audit merge:
  `93881a75d272ce9fcf5dffbe7b7e495b09d6b60a`
- reserves: training PR-2330, PR-3226, PR-3231; validation PR-2989, PR-3059

The five source directories are deliberately not copied into v28. PR-2330 and PR-3226 remain under
the sealed v26 experiment, PR-3231 and PR-2989 under v27, and PR-3059 under v28. Before creating an
output directory, the runner resolves those three read-only roots, rejects symlinks and traversal,
recomputes every source `image-lock.json` SHA-256, and checks repository, verifier-image, and
manifest bindings. It writes only origin labels and relative source paths to a hash-bound source
catalog; host absolute paths are not materialized into that catalog. A read-only validation against
the existing evidence found five tasks and produced source-catalog hash
`7d708bb0c7ac86e0562899e42abce671cde0c9c5b1d96fa21420cfed1fed400f`.

Historical failed candidates remain failed evidence and are not retried or relabelled. The v19
qualification receipt contains only the five independently verifier-qualified reserve bindings.
The historical PR-3204 validation lock is accepted only at file SHA-256
`55ff6b4efb9675a0a6d512b32d0b33d7778d93d81159086c7485b9f3ebe92a6b` and lock hash
`b3fe6732fe4d9b52a6444cda90b25add311665af537acf6b389ad1fdafa1933b`.

## Image and security controls

The materializer requires a clean tracked checkout whose `HEAD` equals `origin/main`, an explicit
opt-in environment name, the frozen Codex 0.147.0 binary hash, and the frozen legacy identity
template hash. It creates one distinct tag and image per reserve. BuildKit `RUN` networking is
`none`; runtime scans also use `network=none`, a read-only root filesystem, non-root identity,
cap-drop `ALL`, no-new-privileges, bounded resources, and one visible workspace mount. Any build,
binding, scan, duplicate-image, or orchestration error atomically stops the stage without retry.

This follows the upstream OpenHands recommendation to use an isolated Docker workspace and a
pre-built image for faster startup, while keeping task customization in a separately built image:
[OpenHands Docker sandbox](https://docs.openhands.dev/sdk/guides/agent-server/docker-sandbox).
Docker's official build reference defines `--network=none` as no network access for Dockerfile
`RUN` instructions, and its `none` network driver isolates runtime containers:
[Docker buildx build](https://docs.docker.com/reference/cli/docker/buildx/build/),
[Docker none network](https://docs.docker.com/engine/network/drivers/none/). Those upstream
patterns support prebuilding once and failing before provider use; this repository additionally
requires digest locks, effective-control inspection, source-role separation, and security receipts.

## Regression and acceptance

The targeted regression covers authorization hashing, provider/canary prohibition, exact reserve
roles, source resolution across all three historical roots, path escape rejection, v19 receipt
compatibility, and the fixed PR-2330 to PR-3204 schedule. The real materializer must not run until
this authorization pull request passes the ordinary credential-free suite and the repository's
eight protection classes. After a successful materialization, its hashes and zero-provider result
must be committed in a separate sanitized audit pull request. Provider canary execution requires a
later, independent authorization based on that exact static contract.

Passing this stage does not start a benchmark, produce a trajectory, authorize formal collection,
or make any dataset production-ready. `production_training_ready=false` and
`benchmark_score_claimed=false` remain fixed.

## Local verification before review

The authorization implementation passed the following credential-free checks:

- v29 targeted tests: `6 passed`; combined v19/v28/v29 regressions: `40 passed`
- complete OpenHands Python 3.12 suite: `299 passed`
- ordinary core suite: `1035 passed`, `10 skipped`, `43 deselected`
- HWE plugin suite: `50 passed`
- strict mypy: core `206` files, HWE `9` files, OpenHands `28` files, materializer `1` file
- schema/document contracts: `2 passed`, zero schema drift
- changed-artifact security scan: `4` files, zero hard leaks and zero scanner errors
- OpenHands and HWE wheel/sdist policy scans: passed
- core wheel and sdist reproducibility: both byte-identical
- read-only evidence preflight: all five source locks and all five local verifier images present;
  historical PR-3204 agent image present; zero implicit pulls
- premature real-run control: rejected the unmerged branch before output/image creation, with zero
  provider calls

The first ordinary-suite invocation inherited a stale editable-install path from an unrelated
experiment and stopped during test collection; explicitly prepending this checkout's `src/` made
the full suite pass. The first HWE invocation similarly paired current plugin code with that stale
core because of an incorrect relative test path; the corrected root-relative invocation passed.
The isolated plugin builders attempted to obtain an already-installed setuptools requirement and
one received the configured package-index proxy's HTTP 502; rebuilding both plugins with the
installed requirement-compatible backend and `--no-isolation` passed their distribution scans.
No provider, candidate verifier, agent image build, canary, collection, or training process ran
during these corrections. GitHub checks from a clean checkout remain the authoritative stage gate.
